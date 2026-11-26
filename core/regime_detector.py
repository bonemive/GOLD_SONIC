"""6-regime Market Intelligence classifier with smoothing, hysteresis, and shock cooldown.

Prevents rapid flip-flopping on noisy ticks while reacting promptly to genuine
structural shifts and abnormal market shocks.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.indicators import MarketFeatures
from core.market_data import DataQuality, MarketSnapshot

logger = logging.getLogger("gold_sonic.regime")


class MarketRegime(str, Enum):
    """Six canonical market regimes for GOLD SONIC."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    COMPRESSION = "COMPRESSION"
    MARKET_SHOCK = "MARKET_SHOCK"


@dataclass(frozen=True)
class ShockEvent:
    """One-shot musical shock trigger with cooldown protection."""

    intensity: float  # 0.0..1.0
    direction: int  # +1 up spike, -1 down drop
    spike_atr: float
    return_zscore: float
    timestamp: float


@dataclass(frozen=True)
class RegimeState:
    """Smoothed, hysteresis-stabilized market intelligence output."""

    regime: MarketRegime
    raw_candidate: MarketRegime
    confidence: float  # 0.0..1.0
    trend_label: str
    volatility_smooth: float  # 0.0..1.0
    momentum_smooth: float  # -1.0..+1.0
    atr_ratio_smooth: float
    trend_strength: float  # 0.0..1.0
    safe_mode: bool
    safe_mode_reason: str
    shock_event: ShockEvent | None
    shock_cooldown_remaining: float
    regime_age_seconds: float


class RegimeDetector:
    """Stateful market regime classifier with EMA smoothing and confirmation hysteresis."""

    def __init__(self, mi_config: dict[str, Any]) -> None:
        self._alpha: float = float(mi_config.get("smoothing_alpha", 0.22))
        self._confirm_cycles: int = max(1, int(mi_config.get("regime_confirm_cycles", 3)))
        self._min_hold_sec: float = float(mi_config.get("regime_min_hold_seconds", 10.0))
        self._shock_atr_mult: float = float(mi_config.get("shock_atr_multiplier", 2.5))
        self._shock_zscore: float = float(mi_config.get("shock_zscore_threshold", 3.2))
        self._shock_cooldown_sec: float = float(mi_config.get("shock_cooldown_seconds", 18.0))
        self._shock_hold_sec: float = 6.0

        self._current_regime: MarketRegime = MarketRegime.SIDEWAYS
        self._regime_entered_at: float = 0.0
        self._pending_regime: MarketRegime | None = None
        self._pending_count: int = 0

        self._last_shock_at: float = -1e9
        self._shock_active_until: float = 0.0

        self._initialized: bool = False
        self._vol_smooth: float = 0.30
        self._mom_smooth: float = 0.0
        self._atr_ratio_smooth: float = 1.0
        self._trend_strength: float = 0.0

    def reset(self) -> None:
        """Reset smoothing and hysteresis state cleanly."""
        self._current_regime = MarketRegime.SIDEWAYS
        self._regime_entered_at = 0.0
        self._pending_regime = None
        self._pending_count = 0
        self._last_shock_at = -1e9
        self._shock_active_until = 0.0
        self._initialized = False
        self._vol_smooth = 0.30
        self._mom_smooth = 0.0
        self._atr_ratio_smooth = 1.0
        self._trend_strength = 0.0

    def update(
        self,
        snapshot: MarketSnapshot,
        features: MarketFeatures,
        now: float | None = None,
    ) -> RegimeState:
        """Update smoothed state and classify market regime with hysteresis."""
        ts = time.monotonic() if now is None else now
        if self._regime_entered_at == 0.0:
            self._regime_entered_at = ts

        # Safe mode when feed is disconnected, stale, closed, or invalid
        if not snapshot.is_usable_for_live_music or not features.valid:
            # Gently relax musical energy toward calm neutral state
            self._vol_smooth = self._ema_update(self._vol_smooth, 0.18, 0.15)
            self._mom_smooth = self._ema_update(self._mom_smooth, 0.0, 0.15)
            self._atr_ratio_smooth = self._ema_update(self._atr_ratio_smooth, 0.85, 0.15)
            self._trend_strength = self._ema_update(self._trend_strength, 0.0, 0.15)
            return RegimeState(
                regime=MarketRegime.COMPRESSION,
                raw_candidate=MarketRegime.COMPRESSION,
                confidence=0.0,
                trend_label="Safe Mode (Waiting for Live Data)",
                volatility_smooth=self._vol_smooth,
                momentum_smooth=self._mom_smooth,
                atr_ratio_smooth=self._atr_ratio_smooth,
                trend_strength=self._trend_strength,
                safe_mode=True,
                safe_mode_reason=snapshot.quality_reason or snapshot.quality.value,
                shock_event=None,
                shock_cooldown_remaining=max(0.0, self._shock_cooldown_sec - (ts - self._last_shock_at)),
                regime_age_seconds=max(0.0, ts - self._regime_entered_at),
            )

        # Initialize or smooth continuous market signals
        if not self._initialized:
            self._vol_smooth = features.volatility_norm
            self._mom_smooth = features.momentum
            self._atr_ratio_smooth = features.atr_ratio
            self._trend_strength = min(1.0, features.adx14 / 40.0)
            self._initialized = True
        else:
            self._vol_smooth = self._ema_update(self._vol_smooth, features.volatility_norm, self._alpha)
            self._mom_smooth = self._ema_update(self._mom_smooth, features.momentum, self._alpha)
            self._atr_ratio_smooth = self._ema_update(self._atr_ratio_smooth, features.atr_ratio, self._alpha)
            self._trend_strength = self._ema_update(
                self._trend_strength, min(1.0, features.adx14 / 40.0), self._alpha
            )

        # 1. Check Market Shock first (with strict cooldown guard)
        cooldown_elapsed = ts - self._last_shock_at
        shock_triggered = (
            features.spike_atr >= self._shock_atr_mult
            or features.return_zscore >= self._shock_zscore
        )
        shock_event: ShockEvent | None = None
        if shock_triggered and cooldown_elapsed >= self._shock_cooldown_sec:
            intensity = min(
                1.0,
                max(
                    (features.spike_atr - self._shock_atr_mult) / 2.0 + 0.55,
                    (features.return_zscore - self._shock_zscore) / 3.0 + 0.55,
                ),
            )
            shock_event = ShockEvent(
                intensity=max(0.35, min(1.0, intensity)),
                direction=features.spike_direction or (1 if self._mom_smooth >= 0 else -1),
                spike_atr=features.spike_atr,
                return_zscore=features.return_zscore,
                timestamp=ts,
            )
            self._last_shock_at = ts
            self._shock_active_until = ts + self._shock_hold_sec
            self._current_regime = MarketRegime.MARKET_SHOCK
            self._regime_entered_at = ts
            self._pending_regime = None
            self._pending_count = 0
            logger.warning(
                "MARKET_SHOCK detected: spike_atr=%.2f z=%.2f dir=%+d intensity=%.2f",
                features.spike_atr,
                features.return_zscore,
                shock_event.direction,
                shock_event.intensity,
            )

        # 2. Classify non-shock candidate regime using multi-factor scoring + hysteresis margins
        candidate, confidence = self._classify_candidate(features)

        if ts < self._shock_active_until and self._current_regime == MarketRegime.MARKET_SHOCK:
            # Stay in MARKET_SHOCK during the short musical accent window
            active_regime = MarketRegime.MARKET_SHOCK
            confidence = 0.95
        else:
            if self._current_regime == MarketRegime.MARKET_SHOCK:
                # Gracefully exit shock into current candidate without waiting for min hold
                self._current_regime = candidate
                self._regime_entered_at = ts
                self._pending_regime = None
                self._pending_count = 0
            elif candidate != self._current_regime:
                if self._pending_regime == candidate:
                    self._pending_count += 1
                else:
                    self._pending_regime = candidate
                    self._pending_count = 1

                hold_elapsed = ts - self._regime_entered_at
                if (
                    self._pending_count >= self._confirm_cycles
                    and hold_elapsed >= self._min_hold_sec
                ):
                    logger.info(
                        "Regime transition: %s -> %s (conf=%.2f, vol=%.2f, mom=%+.2f, adx=%.1f)",
                        self._current_regime.value,
                        candidate.value,
                        confidence,
                        self._vol_smooth,
                        self._mom_smooth,
                        features.adx14,
                    )
                    self._current_regime = candidate
                    self._regime_entered_at = ts
                    self._pending_regime = None
                    self._pending_count = 0
            else:
                self._pending_regime = None
                self._pending_count = 0

            active_regime = self._current_regime

        # Excessive spread adds a subtle caution notice without claiming disconnect
        safe_mode_reason = ""
        if snapshot.quality == DataQuality.EXCESSIVE_SPREAD:
            safe_mode_reason = snapshot.quality_reason

        cooldown_remaining = max(0.0, self._shock_cooldown_sec - (ts - self._last_shock_at))
        trend_label = self._format_trend_label(features)

        return RegimeState(
            regime=active_regime,
            raw_candidate=candidate,
            confidence=confidence,
            trend_label=trend_label,
            volatility_smooth=self._vol_smooth,
            momentum_smooth=self._mom_smooth,
            atr_ratio_smooth=self._atr_ratio_smooth,
            trend_strength=self._trend_strength,
            safe_mode=False,
            safe_mode_reason=safe_mode_reason,
            shock_event=shock_event,
            shock_cooldown_remaining=cooldown_remaining,
            regime_age_seconds=max(0.0, ts - self._regime_entered_at),
        )

    def _classify_candidate(self, f: MarketFeatures) -> tuple[MarketRegime, float]:
        """Score all 5 continuous regimes with hysteresis bias for the active regime."""
        cur = self._current_regime

        # High Volatility check (enter at atr_ratio >= 1.55 or vol_smooth >= 0.72; exit lower)
        hv_enter = 1.55 if cur != MarketRegime.HIGH_VOLATILITY else 1.32
        hv_vol_enter = 0.70 if cur != MarketRegime.HIGH_VOLATILITY else 0.56
        if self._atr_ratio_smooth >= hv_enter or self._vol_smooth >= hv_vol_enter:
            conf = min(1.0, 0.55 + 0.45 * max(self._vol_smooth, (self._atr_ratio_smooth - 1.0) / 1.2))
            return MarketRegime.HIGH_VOLATILITY, max(0.55, conf)

        # Compression check (low ATR ratio + tight price range + weak directional pressure)
        comp_atr = 0.74 if cur != MarketRegime.COMPRESSION else 0.86
        comp_range = 0.72 if cur != MarketRegime.COMPRESSION else 0.85
        if (
            self._atr_ratio_smooth <= comp_atr
            and f.range_compression <= comp_range
            and f.adx14 < 22.0
        ):
            tightness = 1.0 - min(1.0, (self._atr_ratio_smooth + f.range_compression) * 0.5)
            return MarketRegime.COMPRESSION, min(1.0, 0.60 + tightness)

        # Bullish / Bearish trend scoring using EMA alignment, slope, RSI, ADX, and momentum
        bull_score = 0.0
        bear_score = 0.0

        if f.ema_alignment > 0.18:
            bull_score += 0.32 * min(1.0, f.ema_alignment / 0.6)
        elif f.ema_alignment < -0.18:
            bear_score += 0.32 * min(1.0, abs(f.ema_alignment) / 0.6)

        if f.ema20_slope > 0.06:
            bull_score += 0.22 * min(1.0, f.ema20_slope / 0.30)
        elif f.ema20_slope < -0.06:
            bear_score += 0.22 * min(1.0, abs(f.ema20_slope) / 0.30)

        if f.rsi14 > 54.0:
            bull_score += 0.18 * min(1.0, (f.rsi14 - 50.0) / 22.0)
        elif f.rsi14 < 46.0:
            bear_score += 0.18 * min(1.0, (50.0 - f.rsi14) / 22.0)

        if self._mom_smooth > 0.15:
            bull_score += 0.18 * min(1.0, self._mom_smooth / 0.65)
        elif self._mom_smooth < -0.15:
            bear_score += 0.18 * min(1.0, abs(self._mom_smooth) / 0.65)

        if f.adx14 >= 18.0:
            adx_bonus = 0.14 * min(1.0, (f.adx14 - 16.0) / 20.0)
            if f.plus_di > f.minus_di:
                bull_score += adx_bonus
            elif f.minus_di > f.plus_di:
                bear_score += adx_bonus

        bull_thresh = 0.44 if cur != MarketRegime.BULLISH else 0.34
        bear_thresh = 0.44 if cur != MarketRegime.BEARISH else 0.34

        if bull_score >= bull_thresh and bull_score > bear_score + 0.08:
            return MarketRegime.BULLISH, min(1.0, 0.45 + bull_score * 0.55)

        if bear_score >= bear_thresh and bear_score > bull_score + 0.08:
            return MarketRegime.BEARISH, min(1.0, 0.45 + bear_score * 0.55)

        # Otherwise Sideways (range-bound equilibrium)
        neutrality = 1.0 - min(1.0, max(bull_score, bear_score))
        return MarketRegime.SIDEWAYS, max(0.50, min(0.95, 0.50 + 0.40 * neutrality))

    def _format_trend_label(self, f: MarketFeatures) -> str:
        score = 0.55 * f.ema_alignment + 0.45 * self._mom_smooth
        if score >= 0.45:
            return "Strong Bullish"
        if score >= 0.16:
            return "Bullish"
        if score <= -0.45:
            return "Strong Bearish"
        if score <= -0.16:
            return "Bearish"
        return "Neutral / Balanced"

    @staticmethod
    def _ema_update(prev: float, current: float, alpha: float) -> float:
        return (1.0 - alpha) * prev + alpha * current
