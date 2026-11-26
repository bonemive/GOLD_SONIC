"""Dashboard UI tests, Live MT5 SystemManager integration test, and long-running stability test."""

from __future__ import annotations

import os
import threading
import time
import tracemalloc

import numpy as np
import pandas as pd
import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from core.config_loader import load_config, load_presets
from core.indicators import MarketIndicatorEngine
from core.market_data import DataQuality, MarketSnapshot
from core.musical_engine import MusicalEngine
from core.osc_client import GoldSonicOSCClient
from core.regime_detector import RegimeDetector
from core.system_manager import SystemManager


def test_live_mt5_system_manager_integration_and_honest_sonic_pi_status() -> None:
    """Runs the real SystemManager end-to-end against live MT5 and captures real OSC packets."""
    cfg = load_config()
    cfg["osc"] = dict(cfg["osc"])
    cfg["osc"]["port"] = 14570
    cfg["osc"]["feedback_port"] = 14571
    cfg["osc"]["min_send_interval_ms"] = 250

    captured: list[tuple[str, tuple]] = []
    dispatcher = Dispatcher()
    dispatcher.set_default_handler(lambda addr, *args: captured.append((addr, args)))
    rx = ThreadingOSCUDPServer(("127.0.0.1", 14570), dispatcher)
    rx_t = threading.Thread(target=rx.serve_forever, daemon=True)
    rx_t.start()

    mgr = SystemManager(config=cfg, presets=load_presets(), persist_config=False)
    try:
        assert mgr.start() is True
        # Calling start() twice must NOT create duplicate threads
        threads_before = threading.active_count()
        assert mgr.start() is True
        assert threading.active_count() <= threads_before + 1

        # Wait up to 8s for live MT5 ticks + OSC broadcast
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            tel = mgr.get_telemetry()
            if tel.mt5_status.connected and tel.snapshot.price > 0 and tel.osc_status.messages_sent >= 10:
                break
            time.sleep(0.25)

        tel = mgr.get_telemetry()
        assert tel.running is True
        assert tel.mt5_status.connected is True
        assert tel.mt5_status.symbol_valid is True
        assert tel.snapshot.price > 0.0
        assert tel.features.valid is True
        assert tel.cycle_errors == 0
        # Because no Sonic Pi is answering /gold/pong on 14571, status MUST honestly be False!
        assert tel.osc_status.sonic_pi_connected is False
        assert tel.osc_status.transport_ok is True
        assert len(captured) >= 10

        # Exercise runtime controls safely while live
        mgr.pause_music()
        mgr.set_muted(True)
        mgr.set_style("midnight_jazz")
        mgr.set_layer_enabled("drums", False)
        mgr.set_muted(False)
        mgr.resume_music()
        time.sleep(0.6)

        tel2 = mgr.get_telemetry()
        assert tel2.music.style_id == "midnight_jazz"
        assert tel2.music.layer_enabled["drums"] is False
        assert tel2.cycle_errors == 0
    finally:
        mgr.shutdown()
        rx.shutdown()
        rx.server_close()
        rx_t.join(timeout=1.5)

    assert mgr.is_running is False


def test_pyside6_dashboard_widgets_and_controls_offscreen() -> None:
    """Instantiates real MainWindow offscreen, feeds telemetry, toggles controls, and verifies zero crashes."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from dashboard.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    cfg = load_config()
    cfg["osc"] = dict(cfg["osc"])
    cfg["osc"]["port"] = 14572
    cfg["osc"]["feedback_port"] = 14573

    mgr = SystemManager(config=cfg, presets=load_presets(), persist_config=False)
    win = MainWindow(mgr)
    try:
        win.show()
        app.processEvents()

        # Verify initial honest stopped state
        assert win.engine_led._lbl.text() == "STANDBY"
        assert "OFF" in win.mt5_led._lbl.text()
        assert "OFF" in win.sp_led._lbl.text()
        assert "INACTIVE" in win.audio_led._lbl.text()

        # Exercise interactive controls (style switch, volume, mute, vertical channel strip toggle, logs drawer)
        win.controls_panel.style_combo.setCurrentIndex(1)
        win.controls_panel.master_slider.setValue(65)
        win.controls_panel.btn_mute.setChecked(True)
        win.controls_panel.btn_mute.setChecked(False)
        win.controls_panel.set_layer_checked("atmosphere", False)
        win.btn_logs.setChecked(True)
        app.processEvents()

        # Verify panels refresh cleanly with live telemetry
        win._refresh_ui()
        app.processEvents()
        assert win.controls_panel.master_vol_val.text() == "65%"
        assert mgr.get_layer_settings()["atmosphere"].enabled is False
        assert win.log_console.isVisible() is True
    finally:
        win.close()
        app.processEvents()


def test_long_running_stability_and_bounded_memory() -> None:
    """Simulates 1,500 continuous real-time cycles (~12.5 minutes at 2 Hz) checking stability & memory."""
    cfg = load_config()
    presets = load_presets()
    ind = MarketIndicatorEngine(cfg["market_intelligence"])
    det = RegimeDetector(cfg["market_intelligence"])
    mus = MusicalEngine(cfg["musical_engine"], presets)

    osc_cfg = dict(cfg["osc"])
    osc_cfg["port"] = 14575
    osc_cfg["feedback_port"] = 0  # TX-only stress test
    osc = GoldSonicOSCClient(osc_cfg)
    assert osc.start() is True

    rng = np.random.default_rng(123)
    closes = 3440.0 + np.cumsum(rng.normal(0.0, 0.7, 260))
    times = pd.date_range("2026-11-25 12:00:00", periods=260, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "time": times,
            "open": closes,
            "high": closes + 0.8,
            "low": closes - 0.8,
            "close": closes,
            "tick_volume": np.full(260, 150.0),
            "spread": np.full(260, 28.0),
        }
    )

    tracemalloc.start()
    try:
        base_mem = 0
        t = 1000.0
        prev_bpm = 75.0
        for i in range(1500):
            price = float(closes[-1] + np.sin(i * 0.05) * 4.0)
            snap = MarketSnapshot(
                timestamp=t,
                symbol="GOLD#",
                quality=DataQuality.OK,
                mt5_connected=True,
                bid=price - 0.15,
                ask=price + 0.15,
                last=price,
                price=price,
                spread_price=0.30,
                spread_points=30,
                tick_volume=150.0,
                candles_m1=df,
                candles_m5=df,
                candles_m15=df,
            )
            feat = ind.compute(snap)
            reg = det.update(snap, feat, now=t)
            ms = mus.update(reg, now=t)
            osc.publish_state(snap, feat, reg, ms, now=t)

            # Verify BPM stays strictly bounded and smooth every step
            assert 68.0 <= ms.bpm <= 100.0
            if i > 0:
                assert abs(ms.bpm - prev_bpm) <= 1.0
            prev_bpm = ms.bpm

            if i == 200:
                base_mem, _ = tracemalloc.get_traced_memory()
            t += 0.5

        final_mem, _ = tracemalloc.get_traced_memory()
        # Memory delta across 1,300 continuous iterations must stay tightly bounded (< 8 MB)
        mem_growth_mb = (final_mem - base_mem) / (1024.0 * 1024.0)
        assert mem_growth_mb < 8.0, f"Unexpected memory growth: {mem_growth_mb:.2f} MB"
        assert ms.bar_index > 150  # Progressed smoothly through > 9 full 16-bar cycles
    finally:
        tracemalloc.stop()
        osc.stop()
