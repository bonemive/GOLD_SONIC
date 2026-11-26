"""OSC/UDP communication bridge between Python (GOLD SONIC) and Sonic Pi.

Implements strict payload validation, rate throttling, heartbeat/pong liveness
monitoring (never falsely claiming Sonic Pi is connected), stale-data detection,
and safe-default shutdown signaling.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from core.indicators import MarketFeatures
from core.market_data import MarketSnapshot
from core.musical_engine import MusicalState
from core.regime_detector import RegimeState

logger = logging.getLogger("gold_sonic.osc")

# Canonical OSC address space shared with sonic_pi/gold_sonic.rb
OSC_MARKET = "/gold/market"
OSC_MOOD = "/gold/mood"
OSC_VOLATILITY = "/gold/volatility"
OSC_MOMENTUM = "/gold/momentum"
OSC_REGIME = "/gold/regime"
OSC_BPM = "/gold/bpm"
OSC_HARMONY = "/gold/harmony"
OSC_MELODY = "/gold/melody"
OSC_LAYERS = "/gold/layers"
OSC_SHOCK = "/gold/shock"
OSC_HEARTBEAT = "/gold/heartbeat"
OSC_PONG = "/gold/pong"


@dataclass(frozen=True)
class OSCStatus:
    """Honest transport, Sonic Pi liveness, and real audio-activity telemetry."""

    host: str
    port: int
    feedback_port: int
    transport_ok: bool
    sonic_pi_connected: bool
    sonic_pi_version: str
    audio_engine_active: bool
    sonic_pi_active_layers: int
    sonic_pi_bars_played: int
    messages_sent: int
    messages_throttled: int
    heartbeats_sent: int
    pongs_received: int
    heartbeat_rtt_ms: float
    packet_loss_pct: float
    last_send_age_sec: float
    last_pong_age_sec: float
    last_error: str


def _clean_float(val: Any, default: float = 0.0, lo: float | None = None, hi: float | None = None) -> float:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    if lo is not None:
        f = max(lo, f)
    if hi is not None:
        f = min(hi, f)
    return f


def _clean_int(val: Any, default: int = 0, lo: int | None = None, hi: int | None = None) -> int:
    try:
        i = int(round(float(val)))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        i = max(lo, i)
    if hi is not None:
        i = min(hi, i)
    return i


class GoldSonicOSCClient:
    """Throttled, validated UDP OSC client with optional two-way Sonic Pi heartbeat monitor."""

    def __init__(self, osc_config: dict[str, Any]) -> None:
        self._host: str = str(osc_config.get("host", "127.0.0.1"))
        self._port: int = int(osc_config.get("port", 4560))
        self._feedback_port: int = int(osc_config.get("feedback_port", 4561))
        self._min_interval_sec: float = max(0.05, float(osc_config.get("min_send_interval_ms", 250)) / 1000.0)
        self._heartbeat_interval_sec: float = float(osc_config.get("heartbeat_interval_seconds", 2.0))
        self._sonic_pi_timeout_sec: float = float(osc_config.get("sonic_pi_timeout_seconds", 6.5))

        self._lock = threading.RLock()
        self._client: SimpleUDPClient | None = None
        self._server: ThreadingOSCUDPServer | None = None
        self._server_thread: threading.Thread | None = None

        self._transport_ok: bool = False
        self._last_error: str = ""
        self._messages_sent: int = 0
        self._messages_throttled: int = 0
        self._pongs_received: int = 0
        self._heartbeat_seq: int = 0
        self._heartbeat_sent_times: dict[int, float] = {}
        self._heartbeat_rtt_ms: float = 0.0
        self._sonic_pi_version: str = ""
        self._sonic_pi_audio_live: bool = False
        self._sonic_pi_active_layers: int = 0
        self._sonic_pi_bars_played: int = 0

        self._last_state_send_mono: float = 0.0
        self._last_heartbeat_mono: float = 0.0
        self._last_pong_mono: float = 0.0
        self._last_full_sync_mono: float = 0.0
        self._last_sent_payloads: dict[str, tuple[Any, ...]] = {}

    def start(self) -> bool:
        """Initialize UDP sender and start non-blocking pong listener for Sonic Pi health."""
        with self._lock:
            try:
                self._client = SimpleUDPClient(self._host, self._port)
                self._transport_ok = True
                self._last_error = ""
            except OSError as exc:
                self._transport_ok = False
                self._last_error = f"OSC UDP client init error: {exc}"
                logger.error(self._last_error)
                return False

            if self._server is None and self._feedback_port > 0:
                dispatcher = Dispatcher()
                dispatcher.map(OSC_PONG, self._on_pong)
                try:
                    self._server = ThreadingOSCUDPServer(
                        (self._host, self._feedback_port), dispatcher
                    )
                except OSError:
                    # Fall back cleanly to an ephemeral free localhost UDP port
                    try:
                        self._server = ThreadingOSCUDPServer((self._host, 0), dispatcher)
                        self._feedback_port = int(self._server.server_address[1])
                        logger.info(
                            "Feedback port busy; bound ephemeral RX port %d",
                            self._feedback_port,
                        )
                    except OSError as exc:
                        self._last_error = f"Feedback listener unavailable: {exc}"
                        logger.warning(self._last_error)
                        self._server = None

                if self._server is not None:
                    self._server.daemon_threads = True
                    self._server_thread = threading.Thread(
                        target=self._server.serve_forever,
                        name="osc-pong-listener",
                        daemon=True,
                    )
                    self._server_thread.start()
                    logger.info(
                        "OSC ready: TX -> %s:%d | RX heartbeat ack <- %s:%d",
                        self._host,
                        self._port,
                        self._host,
                        self._feedback_port,
                    )
            return True

    def stop(self) -> None:
        """Send safe silence state and cleanly shut down OSC sockets/threads."""
        with self._lock:
            if self._transport_ok and self._client is not None:
                self.send_safe_default()

            if self._server is not None:
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception as exc:  # pragma: no cover - defensive cleanup
                    logger.debug("Error closing OSC feedback server: %s", exc)
                self._server = None

            if self._server_thread is not None and self._server_thread.is_alive():
                self._server_thread.join(timeout=1.5)
            self._server_thread = None
            self._transport_ok = False
            logger.info("OSC client stopped cleanly.")

    def _on_pong(self, _address: str, *args: Any) -> None:
        with self._lock:
            now_m = time.monotonic()
            self._last_pong_mono = now_m
            self._pongs_received += 1
            if len(args) >= 1:
                seq = _clean_int(args[0], 0)
                sent_at = self._heartbeat_sent_times.pop(seq, None)
                if sent_at is not None:
                    self._heartbeat_rtt_ms = round(max(0.0, (now_m - sent_at) * 1000.0), 1)
                # Prune stale outstanding seq entries to keep memory bounded
                if len(self._heartbeat_sent_times) > 64:
                    cutoff = now_m - 30.0
                    self._heartbeat_sent_times = {
                        k: v for k, v in self._heartbeat_sent_times.items() if v >= cutoff
                    }
            if len(args) >= 2:
                self._sonic_pi_version = str(args[1])
            if len(args) >= 3:
                self._sonic_pi_audio_live = _clean_int(args[2], 0) == 1
            else:
                self._sonic_pi_audio_live = False
            if len(args) >= 4:
                self._sonic_pi_active_layers = _clean_int(args[3], 0, 0, 5)
            if len(args) >= 5:
                self._sonic_pi_bars_played = _clean_int(args[4], 0, 0)

    def publish_state(
        self,
        snapshot: MarketSnapshot,
        features: MarketFeatures,
        regime: RegimeState,
        music: MusicalState,
        force: bool = False,
        now: float | None = None,
    ) -> int:
        """Validate, throttle, and publish market + musical state to Sonic Pi.

        Returns the number of OSC messages actually transmitted in this call.
        """
        with self._lock:
            if not self._transport_ok or self._client is None:
                return 0

            ts = time.monotonic() if now is None else now
            sent_now = 0

            # Always send periodic heartbeat regardless of state throttling
            if force or (ts - self._last_heartbeat_mono) >= self._heartbeat_interval_sec:
                sent_now += self._send_heartbeat(safe_mode=regime.safe_mode, ts=ts)

            # One-shot Market Shock event bypasses normal state throttle (already cooldown-guarded!)
            if music.shock_event is not None:
                shock_args = [
                    _clean_float(music.shock_event.intensity, 0.5, 0.0, 1.0),
                    _clean_int(music.shock_event.direction, 1, -1, 1),
                    _clean_float(music.shock_event.spike_atr, 2.5, 0.0, 20.0),
                ]
                if self._raw_send(OSC_SHOCK, shock_args):
                    sent_now += 1

            # Enforce minimum interval throttling for continuous market/music parameters
            urgent = force or music.bar_changed
            if not urgent and (ts - self._last_state_send_mono) < self._min_interval_sec:
                self._messages_throttled += 1
                return sent_now

            self._last_state_send_mono = ts
            periodic_resync = (ts - self._last_full_sync_mono) >= 4.0
            if periodic_resync or force:
                self._last_full_sync_mono = ts

            chord_padded = (list(music.chord_notes) + [0, 0, 0, 0, 0])[:5]
            melody_padded = (list(music.melody_motif) + [0] * 8)[:8]

            packets: list[tuple[str, list[Any]]] = [
                (
                    OSC_MARKET,
                    [
                        str(snapshot.symbol or "UNKNOWN"),
                        round(_clean_float(snapshot.price, 0.0, 0.0), 4),
                        round(_clean_float(features.atr_m1, 0.0, 0.0), 5),
                        round(_clean_float(features.rsi14, 50.0, 0.0, 100.0), 2),
                        _clean_int(snapshot.spread_points, 0, 0, 100000),
                        str(snapshot.quality.value),
                    ],
                ),
                (
                    OSC_MOOD,
                    [
                        str(music.style_id),
                        str(music.mood),
                        str(music.musical_key),
                        str(music.section.value),
                        _clean_int(music.bar_in_cycle, 1, 1, 16),
                        round(_clean_float(music.swing, 0.06, 0.0, 0.25), 3),
                        str(music.atmosphere_mode),
                    ],
                ),
                (
                    OSC_VOLATILITY,
                    [
                        round(_clean_float(music.volatility_norm, 0.3, 0.0, 1.0), 3),
                        round(_clean_float(music.filter_cutoff, 82.0, 45.0, 125.0), 2),
                        round(_clean_float(music.reverb_amount, 0.45, 0.0, 0.95), 3),
                        round(_clean_float(music.delay_feedback, 0.25, 0.0, 0.85), 3),
                        round(_clean_float(music.drum_intensity, 0.5, 0.0, 1.0), 3),
                        round(_clean_float(music.bass_energy, 0.6, 0.0, 1.0), 3),
                    ],
                ),
                (
                    OSC_MOMENTUM,
                    [
                        round(_clean_float(music.momentum_norm, 0.0, -1.0, 1.0), 3),
                        _clean_int(music.melody_direction, 0, -1, 1),
                        round(_clean_float(music.note_density, 0.45, 0.0, 1.0), 3),
                        round(_clean_float(music.arpeggio_intensity, 0.2, 0.0, 1.0), 3),
                        _clean_int(music.octave_variation, 0, 0, 1),
                    ],
                ),
                (
                    OSC_REGIME,
                    [
                        str(music.regime.value),
                        1 if regime.safe_mode else 0,
                        1 if music.paused else 0,
                        1 if music.muted else 0,
                    ],
                ),
                (
                    OSC_BPM,
                    [round(_clean_float(music.bpm, 75.0, 60.0, 110.0), 2)],
                ),
                (
                    OSC_HARMONY,
                    [
                        str(music.chord_name or "Cmaj7"),
                        _clean_int(music.bass_note, 48, 24, 64),
                        *[_clean_int(n, 0, 0, 108) for n in chord_padded],
                    ],
                ),
                (
                    OSC_MELODY,
                    [_clean_int(n, 0, 0, 108) for n in melody_padded],
                ),
                (
                    OSC_LAYERS,
                    [
                        round(_clean_float(music.layer_gains.get("harmony", 0.0), 0.0, 0.0, 1.0), 3),
                        round(_clean_float(music.layer_gains.get("melody", 0.0), 0.0, 0.0, 1.0), 3),
                        round(_clean_float(music.layer_gains.get("bass", 0.0), 0.0, 0.0, 1.0), 3),
                        round(_clean_float(music.layer_gains.get("drums", 0.0), 0.0, 0.0, 1.0), 3),
                        round(_clean_float(music.layer_gains.get("atmosphere", 0.0), 0.0, 0.0, 1.0), 3),
                        str(music.synths.get("harmony", "rhodey")),
                        str(music.synths.get("melody", "pretty_bell")),
                        str(music.synths.get("bass", "sine")),
                        str(music.synths.get("atmosphere", "bnoise")),
                        str(music.drum_kit.get("kick", "bd_tek")),
                        str(music.drum_kit.get("snare", "sn_dub")),
                        str(music.drum_kit.get("hat", "drum_cymbal_closed")),
                        str(music.drum_kit.get("rim", "perc_snap")),
                        str(music.drum_kit.get("accent", "elec_cymbal")),
                    ],
                ),
            ]

            for address, args in packets:
                key_tuple = tuple(args)
                # Send if changed, forced, on bar change (for harmony/melody), or periodic resync
                changed = self._last_sent_payloads.get(address) != key_tuple
                must_send = (
                    force
                    or periodic_resync
                    or changed
                    or (music.bar_changed and address in (OSC_HARMONY, OSC_MELODY, OSC_MOOD))
                )
                if must_send and self._raw_send(address, args):
                    self._last_sent_payloads[address] = key_tuple
                    sent_now += 1

            return sent_now

    def send_safe_default(self) -> None:
        """Broadcast calm muted/safe default state to Sonic Pi (on Stop or Shutdown)."""
        with self._lock:
            if not self._transport_ok or self._client is None:
                return
            self._raw_send(OSC_REGIME, ["COMPRESSION", 1, 1, 1])
            self._raw_send(
                OSC_LAYERS,
                [
                    0.0, 0.0, 0.0, 0.0, 0.0,
                    "rhodey", "pretty_bell", "sine", "bnoise",
                    "bd_tek", "sn_dub", "drum_cymbal_closed", "perc_snap", "elec_cymbal",
                ],
            )
            self._last_sent_payloads.clear()

    def _send_heartbeat(self, safe_mode: bool, ts: float) -> int:
        self._heartbeat_seq += 1
        self._last_heartbeat_mono = ts
        self._heartbeat_sent_times[self._heartbeat_seq] = ts
        args = [self._heartbeat_seq, self._feedback_port, 1 if safe_mode else 0]
        return 1 if self._raw_send(OSC_HEARTBEAT, args) else 0

    def _raw_send(self, address: str, args: list[Any]) -> bool:
        if self._client is None:
            return False
        try:
            self._client.send_message(address, args)
            self._messages_sent += 1
            return True
        except OSError as exc:
            self._last_error = f"OSC send error on {address}: {exc}"
            logger.error(self._last_error)
            return False

    def get_status(self, now: float | None = None) -> OSCStatus:
        """Return real transport and Sonic Pi handshake status."""
        with self._lock:
            ts = time.monotonic() if now is None else now
            last_pong_age = (ts - self._last_pong_mono) if self._last_pong_mono > 0.0 else -1.0
            last_send_age = (ts - self._last_state_send_mono) if self._last_state_send_mono > 0.0 else -1.0
            sonic_pi_alive = (
                self._last_pong_mono > 0.0
                and last_pong_age <= self._sonic_pi_timeout_sec
            )
            audio_active = sonic_pi_alive and self._sonic_pi_audio_live
            if self._heartbeat_seq > 0:
                loss = max(
                    0.0,
                    min(100.0, (1.0 - (self._pongs_received / self._heartbeat_seq)) * 100.0),
                )
            else:
                loss = 0.0
            return OSCStatus(
                host=self._host,
                port=self._port,
                feedback_port=self._feedback_port,
                transport_ok=self._transport_ok,
                sonic_pi_connected=sonic_pi_alive,
                sonic_pi_version=self._sonic_pi_version if sonic_pi_alive else "",
                audio_engine_active=audio_active,
                sonic_pi_active_layers=self._sonic_pi_active_layers if audio_active else 0,
                sonic_pi_bars_played=self._sonic_pi_bars_played if sonic_pi_alive else 0,
                messages_sent=self._messages_sent,
                messages_throttled=self._messages_throttled,
                heartbeats_sent=self._heartbeat_seq,
                pongs_received=self._pongs_received,
                heartbeat_rtt_ms=self._heartbeat_rtt_ms if sonic_pi_alive else 0.0,
                packet_loss_pct=round(loss, 1),
                last_send_age_sec=round(last_send_age, 2),
                last_pong_age_sec=round(last_pong_age, 2),
                last_error=self._last_error,
            )
