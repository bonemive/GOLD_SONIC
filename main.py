"""GOLD SONIC — Real-Time Algorithmic Lo-fi Music Engine Entry Point.

Supports:
  python main.py                  # Launch PySide6 Desktop Dashboard (default)
  python main.py --autostart      # Launch Dashboard and immediately start engine
  python main.py --headless       # Run Market -> Music -> OSC engine without GUI
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from core.config_loader import load_config, load_presets
from core.system_manager import SystemManager


def _run_headless(manager: SystemManager, duration_seconds: float | None = None) -> int:
    stop_requested = False

    def _handle_sig(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    manager.start()
    start_ts = time.monotonic()
    try:
        while not stop_requested:
            time.sleep(1.0)
            tel = manager.get_telemetry()
            print(
                f"[{tel.snapshot.symbol}] price={tel.snapshot.price:.2f} "
                f"quality={tel.snapshot.quality.value} regime={tel.regime.regime.value} "
                f"bpm={tel.music.bpm:.1f} chord={tel.music.chord_name} "
                f"section={tel.music.section.value} "
                f"mt5={'OK' if tel.mt5_status.connected else 'DISC'} "
                f"sonic_pi={'OK' if tel.osc_status.sonic_pi_connected else 'WAIT'} "
                f"audio={'ACTIVE' if tel.osc_status.audio_engine_active else 'INACTIVE'} "
                f"layers={tel.osc_status.sonic_pi_active_layers} "
                f"osc_tx={tel.osc_status.messages_sent}",
                flush=True,
            )
            if duration_seconds is not None and (time.monotonic() - start_ts) >= duration_seconds:
                break
    finally:
        manager.shutdown()
    return 0


def _run_gui(manager: SystemManager, autostart: bool = False) -> int:
    from PySide6.QtWidgets import QApplication
    from dashboard.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("GOLD SONIC")
    window = MainWindow(manager)
    window.show()

    if autostart:
        manager.start()

    try:
        return int(app.exec())
    finally:
        manager.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GOLD SONIC — Real-Time Algorithmic Music Engine")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to custom config.json",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without PySide6 GUI (console telemetry + OSC streaming)",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Automatically start live MT5/OSC engine when GUI opens",
    )
    parser.add_argument(
        "--manage-sonic-pi",
        action="store_true",
        help="Automatically boot and manage Sonic Pi 5.0.0 headless audio engine if port 4560 is free",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional duration in seconds for headless runs",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    presets = load_presets()
    manager = SystemManager(
        config=config,
        presets=presets,
        manage_sonic_pi=bool(args.manage_sonic_pi),
    )

    if args.headless:
        return _run_headless(manager, duration_seconds=args.duration)
    return _run_gui(manager, autostart=args.autostart)


if __name__ == "__main__":
    raise SystemExit(main())
