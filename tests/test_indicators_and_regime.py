"""Unit tests for MarketIndicatorEngine and RegimeDetector."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.config_loader import load_config
from core.indicators import MarketIndicatorEngine, compute_adx, compute_atr, compute_ema, compute_rsi
from core.market_data import DataQuality, MarketSnapshot
from core.regime_detector import MarketRegime, RegimeDetector


def _make_ohlcv(closes: np.ndarray, spread_hl: np.ndarray | float = 1.0) -> pd.DataFrame:
    n = len(closes)
    opens = np.concatenate(([closes[0]], closes[:-1]))
    if np.isscalar(spread_hl):
        hl = np.full(n, float(spread_hl))
    else:
        hl = np.asarray(spread_hl, dtype=float)
    highs = np.maximum(opens, closes) + hl * 0.5
    lows = np.minimum(opens, closes) - hl * 0.5
    times = pd.date_range("2026-11-25 10:00:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": np.full(n, 120.0),
            "spread": np.full(n, 25.0),
        }
    )


def _make_snapshot(df: pd.DataFrame, quality: DataQuality = DataQuality.OK) -> MarketSnapshot:
    price = float(df["close"].iloc[-1])
    return MarketSnapshot(
        timestamp=1700000000.0,
        symbol="GOLD#",
        quality=quality,
        mt5_connected=(quality != DataQuality.DISCONNECTED),
        bid=price - 0.15,
        ask=price + 0.15,
        last=price,
        price=price,
        spread_price=0.30,
        spread_points=30,
        tick_volume=120.0,
        candles_m1=df,
        candles_m5=df,
        candles_m15=df,
    )


def test_indicator_math_bounds() -> None:
    cfg = load_config()
    engine = MarketIndicatorEngine(cfg["market_intelligence"])
    closes = np.linspace(3400.0, 3440.0, 220)
    df = _make_ohlcv(closes, spread_hl=1.2)
    f = engine.compute(_make_snapshot(df))

    assert f.valid is True
    assert 0.0 <= f.rsi14 <= 100.0
    assert f.rsi14 > 70.0  # pure uptrend
    assert f.ema20 > f.ema50 > f.ema200
    assert f.ema_alignment > 0.5
    assert 0.0 <= f.adx14 <= 100.0
    assert -1.0 <= f.momentum <= 1.0
    assert f.momentum > 0.4
    assert 0.0 <= f.volatility_norm <= 1.0
    assert f.atr_m1 > 0.0


def test_regime_detects_bullish_and_bearish_with_hysteresis() -> None:
    cfg = load_config()
    mi = dict(cfg["market_intelligence"])
    mi["regime_confirm_cycles"] = 3
    mi["regime_min_hold_seconds"] = 5.0
    ind = MarketIndicatorEngine(mi)
    det = RegimeDetector(mi)

    # Strong steady bullish trend
    bull_closes = 3400.0 + np.linspace(0.0, 45.0, 220)
    bull_snap = _make_snapshot(_make_ohlcv(bull_closes, spread_hl=1.0))
    bull_feat = ind.compute(bull_snap)

    # First two updates before hold time should NOT flip immediately from SIDEWAYS
    s1 = det.update(bull_snap, bull_feat, now=100.0)
    s2 = det.update(bull_snap, bull_feat, now=101.0)
    assert s1.regime == MarketRegime.SIDEWAYS
    assert s2.regime == MarketRegime.SIDEWAYS

    # After confirm cycles and min_hold_seconds -> BULLISH
    s3 = det.update(bull_snap, bull_feat, now=106.0)
    assert s3.regime == MarketRegime.BULLISH
    assert "Bullish" in s3.trend_label

    # Switch to strong bearish trend
    bear_closes = 3445.0 - np.linspace(0.0, 50.0, 220)
    bear_snap = _make_snapshot(_make_ohlcv(bear_closes, spread_hl=1.0))
    bear_feat = ind.compute(bear_snap)
    for t in (108.0, 110.0, 112.0, 115.0, 118.0, 121.0):
        st = det.update(bear_snap, bear_feat, now=t)
    assert st.regime == MarketRegime.BEARISH
    assert "Bearish" in st.trend_label


def test_regime_detects_compression_and_high_volatility() -> None:
    cfg = load_config()
    mi = dict(cfg["market_intelligence"])
    mi["regime_confirm_cycles"] = 2
    mi["regime_min_hold_seconds"] = 2.0
    ind = MarketIndicatorEngine(mi)
    det = RegimeDetector(mi)

    # Compression: first 170 bars normal amplitude, last 50 bars tightly coiled
    rng = np.random.default_rng(42)
    base = 3420.0 + np.sin(np.linspace(0, 20, 170)) * 3.0 + rng.normal(0, 0.4, 170)
    coil = 3420.0 + rng.normal(0, 0.08, 50)
    hl = np.concatenate([np.full(170, 2.2), np.full(50, 0.25)])
    comp_df = _make_ohlcv(np.concatenate([base, coil]), spread_hl=hl)
    comp_snap = _make_snapshot(comp_df)
    comp_feat = ind.compute(comp_snap)

    for t in (10.0, 12.0, 15.0, 18.0):
        st = det.update(comp_snap, comp_feat, now=t)
    assert st.regime == MarketRegime.COMPRESSION

    # High Volatility: last 25 bars expand wildly (without extreme single-bar shock)
    hv_closes = 3420.0 + np.concatenate([
        np.sin(np.linspace(0, 18, 195)) * 1.2,
        np.sin(np.linspace(0, 15, 25)) * 4.5,
    ])
    hv_hl = np.concatenate([np.full(195, 1.0), np.full(25, 4.2)])
    hv_df = _make_ohlcv(hv_closes, spread_hl=hv_hl)
    hv_snap = _make_snapshot(hv_df)
    hv_feat = ind.compute(hv_snap)

    for t in (25.0, 28.0, 31.0, 34.0, 38.0, 42.0):
        st = det.update(hv_snap, hv_feat, now=t)
    assert st.regime == MarketRegime.HIGH_VOLATILITY


def test_market_shock_and_cooldown() -> None:
    cfg = load_config()
    mi = dict(cfg["market_intelligence"])
    mi["shock_cooldown_seconds"] = 18.0
    ind = MarketIndicatorEngine(mi)
    det = RegimeDetector(mi)

    closes = np.full(220, 3420.0) + np.sin(np.linspace(0, 30, 220)) * 0.5
    closes[-1] = closes[-2] + 9.0  # Massive spike relative to ~1.0 ATR
    df = _make_ohlcv(closes, spread_hl=0.8)
    snap = _make_snapshot(df)
    feat = ind.compute(snap)

    st1 = det.update(snap, feat, now=200.0)
    assert st1.regime == MarketRegime.MARKET_SHOCK
    assert st1.shock_event is not None
    assert st1.shock_event.direction == 1
    assert st1.shock_event.intensity >= 0.35

    # 3 seconds later: still in cooldown, must NOT fire a duplicate ShockEvent
    st2 = det.update(snap, feat, now=203.0)
    assert st2.shock_event is None
    assert st2.shock_cooldown_remaining > 10.0

    # After 20 seconds: cooldown expired, can trigger again
    st3 = det.update(snap, feat, now=220.0)
    assert st3.shock_event is not None


def test_safe_mode_when_mt5_disconnected() -> None:
    cfg = load_config()
    ind = MarketIndicatorEngine(cfg["market_intelligence"])
    det = RegimeDetector(cfg["market_intelligence"])

    disconnected = MarketSnapshot(
        timestamp=1700000000.0,
        symbol="GOLD#",
        quality=DataQuality.DISCONNECTED,
        quality_reason="MT5 disconnected",
        mt5_connected=False,
    )
    feat = ind.compute(disconnected)
    st = det.update(disconnected, feat, now=50.0)
    assert st.safe_mode is True
    assert "Safe Mode" in st.trend_label
