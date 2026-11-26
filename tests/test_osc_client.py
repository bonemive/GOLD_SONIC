"""Unit & loopback UDP integration tests for GoldSonicOSCClient."""

from __future__ import annotations

import threading
import time

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from core.config_loader import load_config, load_presets
from core.indicators import MarketFeatures
from core.market_data import DataQuality, MarketSnapshot
from core.musical_engine import MusicalEngine
from core.osc_client import (
    OSC_BPM,
    OSC_HARMONY,
    OSC_HEARTBEAT,
    OSC_LAYERS,
    OSC_MARKET,
    OSC_MELODY,
    OSC_MOMENTUM,
    OSC_MOOD,
    OSC_PONG,
    OSC_REGIME,
    OSC_SHOCK,
    OSC_VOLATILITY,
    GoldSonicOSCClient,
)
from core.regime_detector import MarketRegime, RegimeState, ShockEvent


def test_osc_udp_loopback_schema_throttling_and_heartbeat() -> None:
    cfg = load_config()
    presets = load_presets()
    music_engine = MusicalEngine(cfg["musical_engine"], presets)

    received: list[tuple[str, tuple]] = []
    rx_event = threading.Event()

    # Localhost test receiver simulating Sonic Pi's port on ephemeral test port 14560
    test_tx_port = 14560
    test_fb_port = 14561
    pong_sender = SimpleUDPClient("127.0.0.1", test_fb_port)

    def _capture(address: str, *args):
        received.append((address, args))
        if address == OSC_HEARTBEAT:
            seq = args[0]
            pong_sender.send_message(OSC_PONG, [seq, "SonicPi-5.0", 1, 5, 3])
        if len(received) >= 11:
            rx_event.set()

    dispatcher = Dispatcher()
    dispatcher.set_default_handler(_capture)
    rx_server = ThreadingOSCUDPServer(("127.0.0.1", test_tx_port), dispatcher)
    rx_thread = threading.Thread(target=rx_server.serve_forever, daemon=True)
    rx_thread.start()

    osc_cfg = dict(cfg["osc"])
    osc_cfg["port"] = test_tx_port
    osc_cfg["feedback_port"] = test_fb_port
    osc_cfg["min_send_interval_ms"] = 300

    client = GoldSonicOSCClient(osc_cfg)
    assert client.start() is True

    try:
        # Before any heartbeat pong, Sonic Pi MUST report Disconnected (honest status!)
        assert client.get_status().sonic_pi_connected is False

        snap = MarketSnapshot(
            timestamp=time.time(),
            symbol="GOLD#",
            quality=DataQuality.OK,
            mt5_connected=True,
            bid=3450.0,
            ask=3450.3,
            last=3450.15,
            price=3450.15,
            spread_price=0.30,
            spread_points=30,
            tick_volume=210.0,
        )
        feat = MarketFeatures(valid=True, price=3450.15, atr_m1=3.2, rsi14=61.5)
        shock = ShockEvent(intensity=0.82, direction=1, spike_atr=3.1, return_zscore=3.8, timestamp=100.0)
        regime = RegimeState(
            regime=MarketRegime.MARKET_SHOCK,
            raw_candidate=MarketRegime.HIGH_VOLATILITY,
            confidence=0.95,
            trend_label="Strong Bullish",
            volatility_smooth=0.72,
            momentum_smooth=0.62,
            atr_ratio_smooth=1.8,
            trend_strength=0.7,
            safe_mode=False,
            safe_mode_reason="",
            shock_event=shock,
            shock_cooldown_remaining=18.0,
            regime_age_seconds=0.0,
        )
        music = music_engine.update(regime, now=100.0)

        sent = client.publish_state(snap, feat, regime, music, force=True, now=100.0)
        assert sent >= 10
        assert rx_event.wait(timeout=2.0)

        # Verify all canonical OSC endpoints were delivered
        addresses = {addr for addr, _ in received}
        for expected in (
            OSC_MARKET,
            OSC_MOOD,
            OSC_VOLATILITY,
            OSC_MOMENTUM,
            OSC_REGIME,
            OSC_BPM,
            OSC_HARMONY,
            OSC_MELODY,
            OSC_LAYERS,
            OSC_SHOCK,
            OSC_HEARTBEAT,
        ):
            assert expected in addresses, f"Missing OSC address: {expected}"

        # Throttling check: 50ms later without bar_changed/force should throttle continuous sends
        regime_no_shock = RegimeState(**{**regime.__dict__, "shock_event": None})
        music_next = music_engine.update(regime_no_shock, now=100.05)
        sent_throttled = client.publish_state(snap, feat, regime_no_shock, music_next, force=False, now=100.05)
        assert sent_throttled == 0
        assert client.get_status().messages_throttled >= 1

        # Wait briefly for pong loopback -> Sonic Pi should now honestly report Connected
        time.sleep(0.15)
        st = client.get_status()
        assert st.sonic_pi_connected is True
        assert st.pongs_received >= 1
        assert st.sonic_pi_version == "SonicPi-5.0"
        assert st.audio_engine_active is True
        assert st.sonic_pi_active_layers == 5
        assert st.sonic_pi_bars_played == 3
    finally:
        client.stop()
        rx_server.shutdown()
        rx_server.server_close()
        rx_thread.join(timeout=1.5)
