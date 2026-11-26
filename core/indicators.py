"""Quantitative market feature extraction for GOLD SONIC.

Computes ATR, EMA(20/50/200), EMA slopes, RSI(14), ADX(14), realized volatility,
rolling price-range compression, momentum, and spike z-scores purely from real
multi-timeframe OHLCV DataFrames.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core.market_data import MarketSnapshot


@dataclass(frozen=True)
class MarketFeatures:
    """Extracted quantitative features from live market data."""

    valid: bool
    price: float = 0.0
    atr_m1: float = 0.0
    atr_m5: float = 0.0
    atr_ratio: float = 1.0
    ema20: float = 0.0
    ema50: float = 0.0
    ema200: float = 0.0
    ema20_slope: float = 0.0
    ema50_slope: float = 0.0
    ema_alignment: float = 0.0  # -1.0 (full bearish stack) to +1.0 (full bullish stack)
    rsi14: float = 50.0
    rsi14_m5: float = 50.0
    adx14: float = 15.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    momentum: float = 0.0  # -1.0 to +1.0
    realized_volatility: float = 0.0
    volatility_ratio: float = 1.0
    volatility_norm: float = 0.35  # 0.0 to 1.0
    range_compression: float = 1.0  # < 0.70 implies coiling/compression
    price_range_atr: float = 1.0
    spike_atr: float = 0.0
    return_zscore: float = 0.0
    spike_direction: int = 0  # -1, 0, or +1
    spread_points: int = 0
    tick_volume: float = 0.0


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=max(1, span), adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(1, period), adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index (0..100)."""
    delta = series.astype(float).diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    avg_gain = gains.ewm(alpha=1.0 / max(1, period), adjust=False).mean()
    avg_loss = losses.ewm(alpha=1.0 / max(1, period), adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss > 0.0, 100.0)
    rsi = rsi.where((avg_gain > 0.0) | (avg_loss > 0.0), 50.0)
    return rsi.fillna(50.0).clip(0.0, 100.0)


def compute_adx(
    df: pd.DataFrame, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Wilder's ADX, +DI, and -DI."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    atr = compute_atr(df, period).replace(0.0, np.nan)
    alpha = 1.0 / max(1, period)

    smooth_plus = plus_dm_s.ewm(alpha=alpha, adjust=False).mean()
    smooth_minus = minus_dm_s.ewm(alpha=alpha, adjust=False).mean()

    plus_di = (100.0 * smooth_plus / atr).fillna(0.0).clip(0.0, 100.0)
    minus_di = (100.0 * smooth_minus / atr).fillna(0.0).clip(0.0, 100.0)

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (100.0 * (plus_di - minus_di).abs() / di_sum).fillna(0.0)
    adx = dx.ewm(alpha=alpha, adjust=False).mean().fillna(0.0).clip(0.0, 100.0)
    return adx, plus_di, minus_di


class MarketIndicatorEngine:
    """Computes normalized market intelligence features from MarketSnapshots."""

    def __init__(self, mi_config: dict[str, Any]) -> None:
        self._ema_fast = int(mi_config.get("ema_fast", 20))
        self._ema_mid = int(mi_config.get("ema_mid", 50))
        self._ema_slow = int(mi_config.get("ema_slow", 200))
        self._atr_period = int(mi_config.get("atr_period", 14))
        self._rsi_period = int(mi_config.get("rsi_period", 14))
        self._adx_period = int(mi_config.get("adx_period", 14))
        self._atr_norm_window = int(mi_config.get("atr_norm_window", 60))
        self._vol_window = int(mi_config.get("realized_vol_window", 20))
        self._mom_window = int(mi_config.get("momentum_window", 10))

    def compute(self, snapshot: MarketSnapshot) -> MarketFeatures:
        """Compute full feature vector from the latest MarketSnapshot."""
        df_m1 = snapshot.candles_m1
        if df_m1 is None or len(df_m1) < 30:
            return MarketFeatures(valid=False, price=snapshot.price)

        df = df_m1.copy()
        live_price = snapshot.price if snapshot.price > 0.0 else float(df["close"].iloc[-1])

        # Incorporate the live mid/last tick into the current forming M1 bar
        last_idx = df.index[-1]
        df.at[last_idx, "close"] = live_price
        if live_price > float(df.at[last_idx, "high"]):
            df.at[last_idx, "high"] = live_price
        if live_price < float(df.at[last_idx, "low"]):
            df.at[last_idx, "low"] = live_price

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        atr_series = compute_atr(df, self._atr_period)
        atr_m1 = float(atr_series.iloc[-1])
        atr_safe = max(atr_m1, live_price * 1e-5, 1e-6)

        # Use a multi-hour baseline window (up to 180+ bars) so prolonged
        # 30-50 minute compressions don't wash out their own baseline.
        norm_win = min(len(atr_series), max(180, self._atr_norm_window))
        atr_baseline = float(atr_series.iloc[-norm_win:].median())
        atr_ratio = atr_m1 / max(atr_baseline, 1e-6) if atr_baseline > 0.0 else 1.0

        # M5 confirmation ATR & RSI when available
        atr_m5 = atr_m1 * math.sqrt(5.0)
        rsi_m5 = 50.0
        if snapshot.candles_m5 is not None and len(snapshot.candles_m5) >= 30:
            atr_m5 = float(compute_atr(snapshot.candles_m5, self._atr_period).iloc[-1])
            rsi_m5 = float(compute_rsi(snapshot.candles_m5["close"], self._rsi_period).iloc[-1])

        ema20_s = compute_ema(close, self._ema_fast)
        ema50_s = compute_ema(close, self._ema_mid)
        ema200_s = compute_ema(close, min(self._ema_slow, len(close)))

        ema20 = float(ema20_s.iloc[-1])
        ema50 = float(ema50_s.iloc[-1])
        ema200 = float(ema200_s.iloc[-1])

        slope_lb = min(5, len(ema20_s) - 1)
        ema20_slope = (
            (float(ema20_s.iloc[-1]) - float(ema20_s.iloc[-1 - slope_lb]))
            / (slope_lb * atr_safe)
        )
        ema50_slope = (
            (float(ema50_s.iloc[-1]) - float(ema50_s.iloc[-1 - slope_lb]))
            / (slope_lb * atr_safe)
        )

        # Continuous EMA stack alignment score in [-1, 1]
        align_fast = math.tanh((ema20 - ema50) / (2.0 * atr_safe))
        align_macro = math.tanh((ema50 - ema200) / (4.0 * atr_safe))
        align_price = math.tanh((live_price - ema20) / (2.0 * atr_safe))
        ema_alignment = float(np.clip(0.45 * align_fast + 0.35 * align_macro + 0.20 * align_price, -1.0, 1.0))

        rsi14 = float(compute_rsi(close, self._rsi_period).iloc[-1])
        adx_s, plus_di_s, minus_di_s = compute_adx(df, self._adx_period)
        adx14 = float(adx_s.iloc[-1])
        plus_di = float(plus_di_s.iloc[-1])
        minus_di = float(minus_di_s.iloc[-1])

        # Realized volatility (log returns rolling std)
        log_ret = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        vol_win = min(self._vol_window, len(log_ret))
        rolling_std_s = log_ret.rolling(vol_win, min_periods=5).std().fillna(0.0)
        realized_vol = float(rolling_std_s.iloc[-1])
        vol_baseline = float(rolling_std_s.iloc[-norm_win:].median())
        volatility_ratio = realized_vol / max(vol_baseline, 1e-8) if vol_baseline > 1e-8 else 1.0

        # Composite normalized volatility in [0.0, 1.0]
        # ratio 0.4 -> ~0.10, ratio 1.0 -> ~0.42, ratio 1.8 -> ~0.78, ratio 2.5+ -> ~0.95+
        blended_vol_ratio = 0.65 * atr_ratio + 0.35 * volatility_ratio
        volatility_norm = float(np.clip((blended_vol_ratio - 0.35) / 2.05, 0.0, 1.0))

        # Price range & compression (recent 12-bar range vs 60-bar average 12-bar range)
        range_win = min(12, len(df))
        rolling_range = (
            high.rolling(range_win, min_periods=4).max()
            - low.rolling(range_win, min_periods=4).min()
        )
        cur_range = float(rolling_range.iloc[-1])
        base_range = float(rolling_range.iloc[-norm_win:].median())
        range_compression = cur_range / max(base_range, 1e-6) if base_range > 0.0 else 1.0
        price_range_atr = cur_range / atr_safe

        # Multi-component smooth momentum in [-1.0, +1.0]
        mom_lb = min(self._mom_window, len(close) - 1)
        roc_atr = (live_price - float(close.iloc[-1 - mom_lb])) / (atr_safe * math.sqrt(mom_lb))
        rsi_comp = (rsi14 - 50.0) / 30.0
        raw_momentum = 0.45 * roc_atr + 0.30 * rsi_comp + 0.25 * (ema20_slope * 2.5)
        momentum = float(math.tanh(raw_momentum * 0.75))

        # Shock / abnormal spike metrics (current 1-bar and 3-bar impulse vs baseline ATR & std)
        prev_close = float(close.iloc[-2])
        bar_delta = live_price - prev_close
        prev_atr = float(atr_series.iloc[-2]) if len(atr_series) >= 2 else atr_safe
        prev_atr_safe = max(prev_atr, live_price * 1e-5, 1e-6)

        bar_spike_atr = abs(bar_delta) / prev_atr_safe
        if len(close) >= 4:
            delta_3 = live_price - float(close.iloc[-4])
            spike_3_atr = abs(delta_3) / (prev_atr_safe * math.sqrt(3.0))
        else:
            delta_3 = bar_delta
            spike_3_atr = bar_spike_atr

        spike_atr = max(bar_spike_atr, spike_3_atr)
        latest_ret = float(log_ret.iloc[-1])
        prev_std = float(rolling_std_s.iloc[-2]) if len(rolling_std_s) >= 2 else realized_vol
        return_zscore = abs(latest_ret) / max(prev_std, 1e-7) if prev_std > 1e-7 else 0.0

        primary_delta = bar_delta if bar_spike_atr >= spike_3_atr else delta_3
        spike_direction = 1 if primary_delta > 0 else (-1 if primary_delta < 0 else 0)

        return MarketFeatures(
            valid=True,
            price=live_price,
            atr_m1=atr_m1,
            atr_m5=atr_m5,
            atr_ratio=atr_ratio,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            ema20_slope=ema20_slope,
            ema50_slope=ema50_slope,
            ema_alignment=ema_alignment,
            rsi14=rsi14,
            rsi14_m5=rsi_m5,
            adx14=adx14,
            plus_di=plus_di,
            minus_di=minus_di,
            momentum=momentum,
            realized_volatility=realized_vol,
            volatility_ratio=volatility_ratio,
            volatility_norm=volatility_norm,
            range_compression=range_compression,
            price_range_atr=price_range_atr,
            spike_atr=spike_atr,
            return_zscore=return_zscore,
            spike_direction=spike_direction,
            spread_points=snapshot.spread_points,
            tick_volume=snapshot.tick_volume,
        )
