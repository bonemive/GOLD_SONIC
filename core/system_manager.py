"""Central runtime orchestrator for GOLD SONIC.

Coordinates MT5Connector, MarketDataPipeline, MarketIndicatorEngine,
RegimeDetector, MusicalEngine, and GoldSonicOSCClient on a single non-blocking
worker thread with bounded logging, CPU/RAM metrics, error recovery, and
graceful shutdown.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import psutil

from core.config_loader import load_config, load_presets, save_config, setup_logging
from core.indicators import MarketFeatures, MarketIndicatorEngine
from core.market_data import DataQuality, MarketDataPipeline, MarketSnapshot
from core.mt5_connector import MT5Connector, MT5Status
from core.musical_engine import LAYER_NAMES, LayerSettings, MusicalEngine, MusicalState
from core.osc_client import GoldSonicOSCClient, OSCStatus
from core.regime_detector import MarketRegime, RegimeDetector, RegimeState
from core.sonic_pi_launcher import SonicPiProcessManager

logger = logging.getLogger("gold_sonic.system")


class _RingBufferLogHandler(logging.Handler):
    """Thread-safe bounded ring buffer capturing recent log lines for the GUI."""

    def __init__(self, maxlen: int = 250) -> None:
        super().__init__()
        self._buf: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self._buf.append(msg)
        except Exception:  # pragma: no cover - logging must never raise
            pass

    def get_lines(self) -> list[str]:
        with self._lock:
            return list(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


@dataclass(frozen=True)
class SystemTelemetry:
    """Thread-safe immutable snapshot consumed by the PySide6 Dashboard."""

    running: bool
    mt5_status: MT5Status
    osc_status: OSCStatus
    snapshot: MarketSnapshot
    features: MarketFeatures
    regime: RegimeState
    music: MusicalState
    cpu_percent: float
    memory_mb: float
    discovered_symbols: list[str] = field(default_factory=list)
    uptime_seconds: float = 0.0
    cycle_errors: int = 0


class SystemManager:
    """Thread-safe lifecycle & dataflow coordinator for GOLD SONIC."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        presets: dict[str, dict[str, Any]] | None = None,
        persist_config: bool = True,
        manage_sonic_pi: bool = False,
    ) -> None:
        self._config: dict[str, Any] = config if config is not None else load_config()
        self._presets: dict[str, dict[str, Any]] = presets if presets is not None else load_presets()
        self._persist_config: bool = persist_config
        self._manage_sonic_pi: bool = manage_sonic_pi
        self._sp_launcher = SonicPiProcessManager(
            host=str(self._config["osc"].get("host", "127.0.0.1")),
            port=int(self._config["osc"].get("port", 4560)),
        )
        self._root_logger = setup_logging(self._config)

        max_logs = int(self._config.get("dashboard", {}).get("max_log_lines", 250))
        self._log_handler = _RingBufferLogHandler(maxlen=max_logs)
        self._root_logger.addHandler(self._log_handler)

        self._poll_interval_sec: float = max(
            0.1, float(self._config["mt5"].get("poll_interval_ms", 500)) / 1000.0
        )

        # Core decoupled modules
        self._mt5 = MT5Connector(self._config["mt5"])
        self._pipeline = MarketDataPipeline(self._mt5, self._config["mt5"])
        self._indicators = MarketIndicatorEngine(self._config["market_intelligence"])
        self._regime_detector = RegimeDetector(self._config["market_intelligence"])
        self._music_engine = MusicalEngine(self._config["musical_engine"], self._presets)
        self._osc = GoldSonicOSCClient(self._config["osc"])

        # Threading & telemetry state
        self._state_lock = threading.RLock()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._force_osc_sync = threading.Event()

        self._running: bool = False
        self._started_at: float = 0.0
        self._cycle_errors: int = 0
        self._discovered_symbols: list[str] = list(
            self._config["mt5"].get("candidate_symbols", ["GOLD#", "XAUUSD", "XAUUSDm", "GOLD"])
        )

        # Process resource monitor
        self._proc = psutil.Process()
        self._proc.cpu_percent(interval=None)
        self._last_perf_sample: float = 0.0
        self._cpu_percent: float = 0.0
        self._memory_mb: float = 0.0

        # Initial honest stopped telemetry
        init_snap = MarketSnapshot(
            timestamp=time.time(),
            symbol=self._mt5.active_symbol,
            quality=DataQuality.DISCONNECTED,
            quality_reason="Engine stopped",
            mt5_connected=False,
        )
        init_feat = MarketFeatures(valid=False)
        init_regime = self._regime_detector.update(init_snap, init_feat, now=time.monotonic())
        init_music = self._music_engine.update(init_regime, now=time.monotonic())
        self._telemetry = SystemTelemetry(
            running=False,
            mt5_status=self._mt5.get_status(),
            osc_status=self._osc.get_status(),
            snapshot=init_snap,
            features=init_feat,
            regime=init_regime,
            music=init_music,
            cpu_percent=0.0,
            memory_mb=0.0,
            discovered_symbols=list(self._discovered_symbols),
        )

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @property
    def presets(self) -> dict[str, dict[str, Any]]:
        return self._presets

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    def start(self) -> bool:
        """Start the background market/music/OSC worker thread safely (idempotent)."""
        with self._state_lock:
            if self._running and self._worker_thread and self._worker_thread.is_alive():
                logger.info("SystemManager is already running.")
                return True

            self._stop_event.clear()
            if self._manage_sonic_pi:
                self._sp_launcher.ensure_running()
            self._osc.start()
            self._music_engine.reset_arrangement()
            self._regime_detector.reset()
            self._started_at = time.monotonic()
            self._running = True

            self._worker_thread = threading.Thread(
                target=self._run_loop,
                name="gold-sonic-engine",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("GOLD SONIC engine started.")
            return True

    def stop(self) -> None:
        """Gracefully stop background thread, silence Sonic Pi, and disconnect MT5."""
        with self._state_lock:
            was_running = self._running
            self._running = False
            self._stop_event.set()
            worker = self._worker_thread

        if worker is not None and worker.is_alive():
            worker.join(timeout=4.0)

        with self._state_lock:
            self._worker_thread = None
            self._osc.stop()
            self._mt5.shutdown()

            # Refresh telemetry to reflect honest stopped state
            stopped_snap = MarketSnapshot(
                timestamp=time.time(),
                symbol=self._mt5.active_symbol,
                quality=DataQuality.DISCONNECTED,
                quality_reason="Engine stopped",
                mt5_connected=False,
            )
            stopped_feat = MarketFeatures(valid=False)
            stopped_regime = self._regime_detector.update(stopped_snap, stopped_feat)
            stopped_music = self._music_engine.update(stopped_regime)
            self._telemetry = SystemTelemetry(
                running=False,
                mt5_status=self._mt5.get_status(),
                osc_status=self._osc.get_status(),
                snapshot=stopped_snap,
                features=stopped_feat,
                regime=stopped_regime,
                music=stopped_music,
                cpu_percent=self._cpu_percent,
                memory_mb=self._memory_mb,
                discovered_symbols=list(self._discovered_symbols),
                uptime_seconds=0.0,
                cycle_errors=self._cycle_errors,
            )

        if was_running:
            logger.info("GOLD SONIC engine stopped cleanly.")

    def shutdown(self) -> None:
        """Final cleanup when exiting the application."""
        self.stop()
        if self._manage_sonic_pi:
            self._sp_launcher.stop()
        self._root_logger.removeHandler(self._log_handler)

    def _run_loop(self) -> None:
        """Single dedicated engine loop: MT5 -> Features -> Regime -> Music -> OSC."""
        # Perform initial MT5 connect & symbol discovery on worker thread (keeps GUI responsive!)
        mt5_status = self._mt5.connect()
        if mt5_status.connected:
            discovered = self._mt5.discover_gold_symbols()
            if discovered:
                with self._state_lock:
                    self._discovered_symbols = discovered
            logger.info(
                "MT5 live session active: symbol=%s | available gold symbols=%s",
                mt5_status.symbol,
                discovered[:8],
            )
        else:
            logger.warning("Starting in Safe Mode: %s", mt5_status.last_error)

        first_cycle = True
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            try:
                snapshot = self._pipeline.poll()
                features = self._indicators.compute(snapshot)

                with self._state_lock:
                    regime = self._regime_detector.update(snapshot, features, now=cycle_start)
                    music = self._music_engine.update(regime, now=cycle_start)

                force_send = first_cycle or self._force_osc_sync.is_set()
                self._force_osc_sync.clear()
                self._osc.publish_state(
                    snapshot=snapshot,
                    features=features,
                    regime=regime,
                    music=music,
                    force=force_send,
                    now=cycle_start,
                )
                first_cycle = False

                self._sample_resources(cycle_start)
                mt5_st = self._mt5.get_status()
                osc_st = self._osc.get_status(now=cycle_start)

                with self._state_lock:
                    self._telemetry = SystemTelemetry(
                        running=self._running,
                        mt5_status=mt5_st,
                        osc_status=osc_st,
                        snapshot=snapshot,
                        features=features,
                        regime=regime,
                        music=music,
                        cpu_percent=self._cpu_percent,
                        memory_mb=self._memory_mb,
                        discovered_symbols=list(self._discovered_symbols),
                        uptime_seconds=max(0.0, cycle_start - self._started_at),
                        cycle_errors=self._cycle_errors,
                    )
            except Exception as exc:
                self._cycle_errors += 1
                logger.exception("Recoverable error in engine cycle #%d: %s", self._cycle_errors, exc)

            elapsed = time.monotonic() - cycle_start
            wait_sec = max(0.02, self._poll_interval_sec - elapsed)
            self._stop_event.wait(timeout=wait_sec)

    def _sample_resources(self, now_mono: float) -> None:
        if now_mono - self._last_perf_sample >= 1.0:
            self._last_perf_sample = now_mono
            try:
                cpu = self._proc.cpu_percent(interval=None)
                mem = self._proc.memory_info().rss / (1024.0 * 1024.0)
                self._cpu_percent = round(float(cpu), 1)
                self._memory_mb = round(float(mem), 1)
            except psutil.Error:
                pass

    # ------------------------------------------------------------------
    # Thread-safe Dashboard Queries & Controls
    # ------------------------------------------------------------------
    def get_telemetry(self) -> SystemTelemetry:
        with self._state_lock:
            return self._telemetry

    def get_log_lines(self) -> list[str]:
        return self._log_handler.get_lines()

    def clear_logs(self) -> None:
        self._log_handler.clear()

    def get_layer_settings(self) -> dict[str, LayerSettings]:
        with self._state_lock:
            return self._music_engine.get_layer_settings()

    def pause_music(self) -> None:
        with self._state_lock:
            self._music_engine.set_paused(True)
            self._force_osc_sync.set()
            logger.info("Music paused by user.")

    def resume_music(self) -> None:
        with self._state_lock:
            self._music_engine.set_paused(False)
            self._force_osc_sync.set()
            logger.info("Music resumed by user.")

    def set_muted(self, muted: bool) -> None:
        with self._state_lock:
            self._music_engine.set_muted(muted)
            self._force_osc_sync.set()
            logger.info("Audio %s by user.", "muted" if muted else "unmuted")

    def set_master_volume(self, volume: float) -> None:
        with self._state_lock:
            self._music_engine.set_master_volume(volume)
            self._force_osc_sync.set()

    def set_style(self, style_id: str) -> bool:
        with self._state_lock:
            ok = self._music_engine.set_style(style_id)
            if ok:
                self._config["musical_engine"]["default_style"] = style_id
                if self._persist_config:
                    try:
                        save_config(self._config)
                    except OSError:
                        pass
                self._force_osc_sync.set()
            return ok

    def set_layer_enabled(self, layer: str, enabled: bool) -> None:
        if layer not in LAYER_NAMES:
            return
        with self._state_lock:
            self._music_engine.set_layer_enabled(layer, enabled)
            self._force_osc_sync.set()

    def set_layer_volume(self, layer: str, volume: float) -> None:
        if layer not in LAYER_NAMES:
            return
        with self._state_lock:
            self._music_engine.set_layer_volume(layer, volume)
            self._force_osc_sync.set()

    def reset_arrangement(self) -> None:
        with self._state_lock:
            self._music_engine.reset_arrangement()
            self._force_osc_sync.set()

    def set_symbol(self, symbol: str) -> tuple[bool, str]:
        ok, msg = self._mt5.set_symbol(symbol)
        if ok:
            self._pipeline.reset_cache()
            with self._state_lock:
                self._regime_detector.reset()
                self._config["mt5"]["symbol"] = msg
                if self._persist_config:
                    try:
                        save_config(self._config)
                    except OSError:
                        pass
                self._force_osc_sync.set()
        return ok, msg

    def refresh_symbols(self) -> list[str]:
        discovered = self._mt5.discover_gold_symbols()
        if discovered:
            with self._state_lock:
                self._discovered_symbols = discovered
        return list(self._discovered_symbols)
