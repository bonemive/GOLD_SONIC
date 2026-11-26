"""Market data validation, buffering, and multi-timeframe snapshot pipeline.

Separates raw MT5 acquisition from data hygiene, staleness detection, spread
guards, and immutable snapshot delivery to downstream analytics.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from core.mt5_connector import MT5Connector

logger = logging.getLogger("gold_sonic.market_data")


class DataQuality(str, Enum):
    """Explicit data health classification for downstream safe-mode handling."""

    OK = "OK"
    DISCONNECTED = "DISCONNECTED"
    MISSING_TICK = "MISSING_TICK"
    INVALID_PRICE = "INVALID_PRICE"
    MARKET_CLOSED = "MARKET_CLOSED"
    EXCESSIVE_SPREAD = "EXCESSIVE_SPREAD"
    STALE_DATA = "STALE_DATA"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


@dataclass(frozen=True)
class TickRecord:
    """Validated real market tick."""

    symbol: str
    bid: float
    ask: float
    last: float
    mid: float
    spread_price: float
    spread_points: int
    tick_volume: float
    broker_time: int
    broker_time_msc: int
    local_monotonic: float


@dataclass
class MarketSnapshot:
    """Complete point-in-time market packet passed to Indicator & Regime engines."""

    timestamp: float
    symbol: str
    quality: DataQuality
    quality_reason: str = ""
    mt5_connected: bool = False
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    price: float = 0.0
    spread_price: float = 0.0
    spread_points: int = 0
    tick_volume: float = 0.0
    digits: int = 2
    ohlc_m1: dict[str, float] = field(default_factory=dict)
    candles_m1: pd.DataFrame = field(default_factory=pd.DataFrame)
    candles_m5: pd.DataFrame = field(default_factory=pd.DataFrame)
    candles_m15: pd.DataFrame = field(default_factory=pd.DataFrame)
    stale_seconds: float = 0.0
    update_rate_hz: float = 0.0

    @property
    def is_usable_for_live_music(self) -> bool:
        """True when market data is live and trustworthy for full musical modulation."""
        return self.mt5_connected and self.quality in (
            DataQuality.OK,
            DataQuality.EXCESSIVE_SPREAD,
        )


class MarketDataPipeline:
    """Validates ticks, refreshes M1/M5/M15 candles, and flags all feed anomalies."""

    def __init__(self, connector: MT5Connector, mt5_config: dict[str, Any]) -> None:
        self._connector = connector
        self._history_bars: int = int(mt5_config.get("history_bars", 260))
        self._candle_refresh_sec: float = float(mt5_config.get("candle_refresh_seconds", 5.0))
        self._max_spread_points: int = int(mt5_config.get("max_spread_points", 120))
        self._stale_tick_sec: float = float(mt5_config.get("stale_tick_seconds", 20.0))

        self._tick_buffer: deque[TickRecord] = deque(maxlen=600)
        self._poll_timestamps: deque[float] = deque(maxlen=60)

        self._candles_m1: pd.DataFrame = pd.DataFrame()
        self._candles_m5: pd.DataFrame = pd.DataFrame()
        self._candles_m15: pd.DataFrame = pd.DataFrame()
        self._last_candle_fetch: float = 0.0

        self._last_symbol: str = ""
        self._last_tick_key: tuple[int, float, float] | None = None
        self._last_tick_change_mono: float = 0.0
        self._last_valid_price: float = 0.0

    def reset_cache(self) -> None:
        """Clear cached candles and tick history (e.g., on symbol switch)."""
        self._tick_buffer.clear()
        self._candles_m1 = pd.DataFrame()
        self._candles_m5 = pd.DataFrame()
        self._candles_m15 = pd.DataFrame()
        self._last_candle_fetch = 0.0
        self._last_tick_key = None
        self._last_tick_change_mono = 0.0
        self._last_valid_price = 0.0

    def poll(self) -> MarketSnapshot:
        """Poll real MT5 data once and return a fully validated MarketSnapshot."""
        now_mono = time.monotonic()
        now_wall = time.time()
        self._poll_timestamps.append(now_mono)
        update_rate = self._compute_update_rate()

        if not self._connector.ensure_connected():
            status = self._connector.get_status()
            return MarketSnapshot(
                timestamp=now_wall,
                symbol=status.symbol,
                quality=DataQuality.DISCONNECTED,
                quality_reason=status.last_error or "MT5 disconnected",
                mt5_connected=False,
                update_rate_hz=update_rate,
            )

        symbol = self._connector.active_symbol
        if symbol != self._last_symbol:
            self.reset_cache()
            self._last_symbol = symbol

        sym_info = self._connector.get_symbol_info(symbol)
        if sym_info is None:
            return MarketSnapshot(
                timestamp=now_wall,
                symbol=symbol,
                quality=DataQuality.DISCONNECTED,
                quality_reason=f"Symbol info unavailable for {symbol}",
                mt5_connected=True,
                update_rate_hz=update_rate,
            )

        digits = int(getattr(sym_info, "digits", 2))
        point = float(getattr(sym_info, "point", 0.01)) or 0.01
        trade_mode = int(getattr(sym_info, "trade_mode", 4))

        raw_tick = self._connector.get_tick(symbol)
        if raw_tick is None:
            return MarketSnapshot(
                timestamp=now_wall,
                symbol=symbol,
                quality=DataQuality.MISSING_TICK,
                quality_reason=f"MT5 returned no tick for {symbol}",
                mt5_connected=True,
                digits=digits,
                candles_m1=self._candles_m1,
                candles_m5=self._candles_m5,
                candles_m15=self._candles_m15,
                update_rate_hz=update_rate,
            )

        bid = float(getattr(raw_tick, "bid", 0.0))
        ask = float(getattr(raw_tick, "ask", 0.0))
        raw_last = float(getattr(raw_tick, "last", 0.0))
        broker_time = int(getattr(raw_tick, "time", 0))
        broker_time_msc = int(getattr(raw_tick, "time_msc", broker_time * 1000))
        tick_vol = float(getattr(raw_tick, "volume", 0.0))

        # Validate numerical price integrity
        if not self._is_valid_price(bid, ask):
            return MarketSnapshot(
                timestamp=now_wall,
                symbol=symbol,
                quality=DataQuality.INVALID_PRICE,
                quality_reason=f"Invalid tick prices: bid={bid}, ask={ask}",
                mt5_connected=True,
                bid=bid,
                ask=ask,
                digits=digits,
                candles_m1=self._candles_m1,
                candles_m5=self._candles_m5,
                candles_m15=self._candles_m15,
                update_rate_hz=update_rate,
            )

        mid = (bid + ask) * 0.5
        effective_price = raw_last if (math.isfinite(raw_last) and raw_last > 0.0) else mid
        if self._last_valid_price > 0.0:
            rel_jump = abs(effective_price - self._last_valid_price) / self._last_valid_price
            if rel_jump > 0.15:
                return MarketSnapshot(
                    timestamp=now_wall,
                    symbol=symbol,
                    quality=DataQuality.INVALID_PRICE,
                    quality_reason=(
                        f"Rejected corrupt price jump: {self._last_valid_price:.2f} -> "
                        f"{effective_price:.2f} ({rel_jump * 100:.1f}%)"
                    ),
                    mt5_connected=True,
                    bid=bid,
                    ask=ask,
                    digits=digits,
                    update_rate_hz=update_rate,
                )
        self._last_valid_price = effective_price

        spread_price = max(0.0, ask - bid)
        spread_points = int(round(spread_price / point))

        # Refresh multi-timeframe candles periodically (or on first poll)
        if (
            self._candles_m1.empty
            or (now_mono - self._last_candle_fetch) >= self._candle_refresh_sec
        ):
            self._refresh_candles(symbol, now_mono)

        # Fallback tick volume to active M1 candle volume when broker omits per-tick volume
        if tick_vol <= 0.0 and not self._candles_m1.empty:
            tick_vol = float(self._candles_m1["tick_volume"].iloc[-1])

        # Track genuine tick progression using monotonic clock (immune to broker timezone offsets)
        tick_key = (broker_time_msc, bid, ask)
        if self._last_tick_key is None or tick_key != self._last_tick_key:
            self._last_tick_key = tick_key
            self._last_tick_change_mono = now_mono

        stale_seconds = max(0.0, now_mono - self._last_tick_change_mono)

        record = TickRecord(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=effective_price,
            mid=mid,
            spread_price=spread_price,
            spread_points=spread_points,
            tick_volume=tick_vol,
            broker_time=broker_time,
            broker_time_msc=broker_time_msc,
            local_monotonic=now_mono,
        )
        self._tick_buffer.append(record)

        ohlc_m1: dict[str, float] = {}
        if not self._candles_m1.empty:
            latest = self._candles_m1.iloc[-1]
            ohlc_m1 = {
                "open": float(latest["open"]),
                "high": float(latest["high"]),
                "low": float(latest["low"]),
                "close": float(latest["close"]),
                "tick_volume": float(latest["tick_volume"]),
            }

        quality, reason = self._assess_quality(
            trade_mode=trade_mode,
            spread_points=spread_points,
            stale_seconds=stale_seconds,
        )

        return MarketSnapshot(
            timestamp=now_wall,
            symbol=symbol,
            quality=quality,
            quality_reason=reason,
            mt5_connected=True,
            bid=bid,
            ask=ask,
            last=raw_last if raw_last > 0.0 else effective_price,
            price=effective_price,
            spread_price=spread_price,
            spread_points=spread_points,
            tick_volume=tick_vol,
            digits=digits,
            ohlc_m1=ohlc_m1,
            candles_m1=self._candles_m1,
            candles_m5=self._candles_m5,
            candles_m15=self._candles_m15,
            stale_seconds=stale_seconds,
            update_rate_hz=update_rate,
        )

    def get_recent_ticks(self, limit: int = 60) -> list[TickRecord]:
        """Return the latest N validated ticks."""
        if limit <= 0:
            return []
        return list(self._tick_buffer)[-limit:]

    def _refresh_candles(self, symbol: str, now_mono: float) -> None:
        m1 = self._connector.get_rates("M1", self._history_bars, symbol)
        m5 = self._connector.get_rates("M5", self._history_bars, symbol)
        m15 = self._connector.get_rates("M15", self._history_bars, symbol)
        if not m1.empty:
            self._candles_m1 = m1
        if not m5.empty:
            self._candles_m5 = m5
        if not m15.empty:
            self._candles_m15 = m15
        self._last_candle_fetch = now_mono

    @staticmethod
    def _is_valid_price(bid: float, ask: float) -> bool:
        if not (math.isfinite(bid) and math.isfinite(ask)):
            return False
        if bid <= 0.0 or ask <= 0.0:
            return False
        if ask < bid:
            return False
        return True

    def _assess_quality(
        self,
        trade_mode: int,
        spread_points: int,
        stale_seconds: float,
    ) -> tuple[DataQuality, str]:
        # MT5 SYMBOL_TRADE_MODE_DISABLED == 0
        if trade_mode == 0:
            return DataQuality.MARKET_CLOSED, "Broker reports symbol trading disabled (market closed)"
        if len(self._candles_m1) < 30:
            return (
                DataQuality.INSUFFICIENT_HISTORY,
                f"Only {len(self._candles_m1)} M1 candles available (need >= 30)",
            )
        if stale_seconds >= self._stale_tick_sec:
            return (
                DataQuality.STALE_DATA,
                f"No new tick update for {stale_seconds:.1f}s (possible market pause/closed)",
            )
        if spread_points > self._max_spread_points:
            return (
                DataQuality.EXCESSIVE_SPREAD,
                f"Spread {spread_points} pts exceeds guard ({self._max_spread_points} pts)",
            )
        return DataQuality.OK, "Live market feed healthy"

    def _compute_update_rate(self) -> float:
        if len(self._poll_timestamps) < 2:
            return 0.0
        span = self._poll_timestamps[-1] - self._poll_timestamps[0]
        if span <= 0.0:
            return 0.0
        return (len(self._poll_timestamps) - 1) / span
