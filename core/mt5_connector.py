"""MetaTrader 5 connection, symbol validation, and raw data access layer.

All MT5 API calls are serialized via an internal lock and never synthesize mock
market data when the terminal is disconnected or unavailable.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

logger = logging.getLogger("gold_sonic.mt5")

TIMEFRAME_MAP: dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
}


@dataclass(frozen=True)
class MT5Status:
    """Honest point-in-time status of the MT5 terminal connection."""

    connected: bool
    terminal_build: int = 0
    server: str = ""
    symbol: str = ""
    symbol_valid: bool = False
    last_error: str = ""
    reconnect_attempts: int = 0


class MT5Connector:
    """Thread-safe wrapper around the official MetaTrader5 Python API."""

    def __init__(self, mt5_config: dict[str, Any]) -> None:
        self._cfg = mt5_config
        self._lock = threading.RLock()
        self._terminal_path: str = str(mt5_config.get("terminal_path", "")).strip()
        self._timeout_ms: int = int(mt5_config.get("timeout_ms", 15000))
        self._reconnect_interval: float = float(mt5_config.get("reconnect_interval_seconds", 5.0))
        self._candidate_symbols: list[str] = list(
            mt5_config.get("candidate_symbols", ["GOLD#", "XAUUSD", "XAUUSDm", "GOLD"])
        )
        self._active_symbol: str = str(mt5_config.get("symbol", "GOLD#")).strip()

        self._initialized: bool = False
        self._last_reconnect_attempt: float = 0.0
        self._reconnect_attempts: int = 0
        self._last_error: str = ""

    @property
    def active_symbol(self) -> str:
        with self._lock:
            return self._active_symbol

    def connect(self) -> MT5Status:
        """Initialize MT5 connection and validate the configured gold symbol."""
        with self._lock:
            self._last_reconnect_attempt = time.monotonic()
            kwargs: dict[str, Any] = {"timeout": self._timeout_ms}
            if self._terminal_path:
                kwargs["path"] = self._terminal_path

            ok = mt5.initialize(**kwargs)
            if not ok:
                err = mt5.last_error()
                self._initialized = False
                self._last_error = f"MT5 initialize failed: {err}"
                self._reconnect_attempts += 1
                logger.error(self._last_error)
                return self.get_status()

            terminal = mt5.terminal_info()
            if terminal is None or not getattr(terminal, "connected", False):
                err = mt5.last_error()
                self._initialized = False
                self._last_error = f"MT5 terminal is not connected to broker server: {err}"
                self._reconnect_attempts += 1
                logger.warning(self._last_error)
                return self.get_status()

            self._initialized = True
            self._reconnect_attempts = 0
            self._last_error = ""

            resolved = self.resolve_symbol(self._active_symbol)
            if resolved:
                self._active_symbol = resolved
                logger.info(
                    "MT5 connected (build=%s, server=%s, symbol=%s)",
                    getattr(terminal, "build", 0),
                    getattr(mt5.account_info(), "server", "unknown"),
                    self._active_symbol,
                )
            else:
                self._last_error = (
                    f"Configured symbol '{self._active_symbol}' and fallback candidates "
                    f"not found in MT5."
                )
                logger.error(self._last_error)

            return self.get_status()

    def ensure_connected(self) -> bool:
        """Verify live connection; attempt periodic reconnect if disconnected."""
        with self._lock:
            if self._initialized and self._is_terminal_alive():
                return True

            self._initialized = False
            now = time.monotonic()
            if now - self._last_reconnect_attempt < self._reconnect_interval:
                return False

            logger.info("Attempting MT5 reconnect (attempt #%d)...", self._reconnect_attempts + 1)
            status = self.connect()
            return status.connected and status.symbol_valid

    def _is_terminal_alive(self) -> bool:
        terminal = mt5.terminal_info()
        if terminal is None:
            self._last_error = f"MT5 terminal_info unavailable: {mt5.last_error()}"
            return False
        if not getattr(terminal, "connected", False):
            self._last_error = "MT5 lost connection to broker server"
            return False
        return True

    def get_status(self) -> MT5Status:
        """Return exact real-time connection status without masking errors."""
        with self._lock:
            if not self._initialized:
                return MT5Status(
                    connected=False,
                    symbol=self._active_symbol,
                    symbol_valid=False,
                    last_error=self._last_error or "Not connected",
                    reconnect_attempts=self._reconnect_attempts,
                )

            terminal = mt5.terminal_info()
            if terminal is None or not getattr(terminal, "connected", False):
                self._initialized = False
                self._last_error = "MT5 disconnected from broker server"
                return MT5Status(
                    connected=False,
                    symbol=self._active_symbol,
                    symbol_valid=False,
                    last_error=self._last_error,
                    reconnect_attempts=self._reconnect_attempts,
                )

            account = mt5.account_info()
            sym_info = mt5.symbol_info(self._active_symbol)
            return MT5Status(
                connected=True,
                terminal_build=int(getattr(terminal, "build", 0)),
                server=str(getattr(account, "server", "")) if account else "",
                symbol=self._active_symbol,
                symbol_valid=sym_info is not None,
                last_error=self._last_error,
                reconnect_attempts=self._reconnect_attempts,
            )

    def discover_gold_symbols(self) -> list[str]:
        """List available Gold/XAU symbols directly from the connected MT5 terminal."""
        with self._lock:
            if not self._initialized:
                return []
            symbols = mt5.symbols_get()
            if not symbols:
                return []

            preferred: list[str] = []
            others: list[str] = []
            candidate_upper = {c.upper() for c in self._candidate_symbols}

            for sym in symbols:
                name = str(sym.name)
                upper = name.upper()
                if upper in candidate_upper:
                    preferred.append(name)
                elif "XAU" in upper or upper.startswith("GOLD"):
                    others.append(name)

            # Preserve candidate priority order first, then alphabetical extras
            ordered_preferred = [
                c for c in self._candidate_symbols if any(p.upper() == c.upper() for p in preferred)
            ]
            seen = {s.upper() for s in ordered_preferred}
            for name in sorted(others):
                if name.upper() not in seen:
                    ordered_preferred.append(name)
                    seen.add(name.upper())
            return ordered_preferred

    def resolve_symbol(self, requested_symbol: str) -> str | None:
        """Validate requested symbol in MT5, or fall back to verified gold candidates."""
        with self._lock:
            if not self._initialized:
                return None

            search_order = [requested_symbol] + [
                c for c in self._candidate_symbols if c != requested_symbol
            ]
            for candidate in search_order:
                if not candidate:
                    continue
                info = mt5.symbol_info(candidate)
                if info is not None:
                    if not info.visible:
                        if not mt5.symbol_select(candidate, True):
                            logger.warning("Failed to enable Market Watch for %s", candidate)
                            continue
                    return str(info.name)
            return None

    def set_symbol(self, symbol: str) -> tuple[bool, str]:
        """Switch active symbol after verifying it exists in MT5."""
        with self._lock:
            clean = symbol.strip()
            if not clean:
                return False, "Symbol name cannot be empty"
            if not self._initialized:
                self._active_symbol = clean
                return False, "MT5 not connected; symbol saved for next connection"

            info = mt5.symbol_info(clean)
            if info is None:
                return False, f"Symbol '{clean}' does not exist in MT5"
            if not info.visible and not mt5.symbol_select(clean, True):
                return False, f"Could not select '{clean}' in MT5 Market Watch"

            self._active_symbol = str(info.name)
            self._last_error = ""
            logger.info("Active MT5 symbol switched to %s", self._active_symbol)
            return True, self._active_symbol

    def get_symbol_info(self, symbol: str | None = None) -> Any | None:
        """Fetch raw MT5 SymbolInfo object for the active symbol."""
        with self._lock:
            if not self._initialized:
                return None
            target = symbol or self._active_symbol
            return mt5.symbol_info(target)

    def get_tick(self, symbol: str | None = None) -> Any | None:
        """Fetch the latest real tick from MT5."""
        with self._lock:
            if not self._initialized:
                return None
            target = symbol or self._active_symbol
            tick = mt5.symbol_info_tick(target)
            if tick is None:
                self._last_error = f"Missing tick for {target}: {mt5.last_error()}"
            return tick

    def get_rates(
        self,
        timeframe: str,
        count: int = 260,
        symbol: str | None = None,
    ) -> pd.DataFrame:
        """Fetch real OHLCV candles from MT5 as a normalized DataFrame."""
        with self._lock:
            if not self._initialized:
                return pd.DataFrame()
            tf_code = TIMEFRAME_MAP.get(timeframe.upper())
            if tf_code is None:
                raise ValueError(f"Unsupported timeframe: {timeframe}")

            target = symbol or self._active_symbol
            rates = mt5.copy_rates_from_pos(target, tf_code, 0, int(count))
            if rates is None or len(rates) == 0:
                self._last_error = f"No {timeframe} rates returned for {target}: {mt5.last_error()}"
                return pd.DataFrame()

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype(float)
            df["tick_volume"] = df["tick_volume"].astype(float)
            if "spread" in df.columns:
                df["spread"] = df["spread"].astype(float)
            return df

    def shutdown(self) -> None:
        """Gracefully close MT5 connection."""
        with self._lock:
            if self._initialized:
                mt5.shutdown()
                self._initialized = False
                logger.info("MT5 connection shut down cleanly.")
