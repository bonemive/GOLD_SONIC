"""Algorithmic Musical Intelligence and Composition Engine for GOLD SONIC.

Translates smoothed MarketRegime & quantitative features into structured,
theory-compliant Lo-fi music: key-consistent chord progressions with smooth
voice leading, 4/8/16-bar arrangement sections, pentatonic/jazz melody motifs,
slew-limited BPM, and ATR-driven sound design parameters.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.regime_detector import MarketRegime, RegimeState, ShockEvent

logger = logging.getLogger("gold_sonic.music")

NOTE_TO_SEMITONE: dict[str, int] = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}

# Jazz & Lo-fi chord intervals relative to root
CHORD_INTERVALS: dict[str, list[int]] = {
    "maj7": [0, 4, 7, 11],
    "maj9": [0, 4, 7, 11, 14],
    "m7": [0, 3, 7, 10],
    "m9": [0, 3, 7, 10, 14],
    "7": [0, 4, 7, 10],
    "9": [0, 4, 7, 10, 14],
    "13": [0, 4, 7, 10, 14, 21],
    "7b9": [0, 4, 7, 10, 13],
    "sus2": [0, 2, 7, 12],
    "sus4": [0, 5, 7, 10],
    "add9": [0, 4, 7, 14],
    "m": [0, 3, 7],
    "": [0, 4, 7],
}

# Scales mapped to regimes for key-consistent pentatonic & jazz melodic lines
REGIME_SCALES: dict[MarketRegime, list[int]] = {
    MarketRegime.BULLISH: [0, 2, 4, 7, 9, 11],          # Warm Major Pentatonic + 7th
    MarketRegime.BEARISH: [0, 3, 5, 7, 10, 14],         # Emotional Minor Pentatonic + 9th
    MarketRegime.SIDEWAYS: [0, 2, 3, 5, 7, 9, 10],      # Dreamy Jazz Dorian
    MarketRegime.COMPRESSION: [0, 2, 5, 7, 10],         # Suspended Quartal Pentatonic
    MarketRegime.HIGH_VOLATILITY: [0, 2, 4, 7, 9, 10],  # Energetic Mixolydian Pentatonic
    MarketRegime.MARKET_SHOCK: [0, 3, 5, 6, 7, 10],     # Expressive Blues-Jazz Accent
}

REGIME_MOODS: dict[MarketRegime, str] = {
    MarketRegime.BULLISH: "Warm Major 7/9",
    MarketRegime.BEARISH: "Emotional Minor 7/9",
    MarketRegime.SIDEWAYS: "Dreamy Jazz Chords",
    MarketRegime.COMPRESSION: "Suspended Ambient",
    MarketRegime.HIGH_VOLATILITY: "Energetic Harmonic",
    MarketRegime.MARKET_SHOCK: "Shock Musical Accent",
}

LAYER_NAMES: tuple[str, ...] = ("harmony", "melody", "bass", "drums", "atmosphere")


class ArrangementSection(str, Enum):
    """Structured musical song sections (4/8/16-bar architecture)."""

    INTRO = "Intro"
    MAIN_GROOVE = "Main Progression"
    MELODY_DEVELOP = "Melody & Bass"
    VARIATION_B = "Harmonic Variation"
    TRANSITION = "Transition"
    OUTRO_RESET = "Outro / Safe Mode"


@dataclass(frozen=True)
class LayerSettings:
    """Independent enable toggle and gain for a Sonic Pi instrument layer."""

    enabled: bool = True
    volume: float = 0.75


@dataclass(frozen=True)
class MusicalState:
    """Complete musical composition & DSP state broadcast to Sonic Pi and Dashboard."""

    style_id: str
    style_name: str
    regime: MarketRegime
    mood: str
    musical_key: str
    section: ArrangementSection
    bar_index: int
    bar_in_phrase: int  # 1..4
    bar_in_cycle: int  # 1..16
    chord_name: str
    chord_notes: list[int]
    bass_note: int
    melody_motif: list[int]  # 8-step MIDI motif (0 = musical rest)
    bpm: float
    target_bpm: float
    volatility_level: str
    volatility_norm: float
    momentum_norm: float
    melody_direction: int  # -1, 0, +1
    note_density: float  # 0.0..1.0
    arpeggio_intensity: float  # 0.0..1.0
    octave_variation: int  # 0 or 1
    filter_cutoff: float  # Sonic Pi LPF cutoff (60..118)
    reverb_amount: float  # 0.0..0.85
    delay_feedback: float  # 0.0..0.60
    drum_intensity: float  # 0.0..1.0
    bass_energy: float  # 0.0..1.0
    swing: float
    atmosphere_mode: str
    synths: dict[str, str]
    drum_kit: dict[str, str]
    layer_gains: dict[str, float]  # Effective gains after mute/master/section shaping
    layer_enabled: dict[str, bool]
    master_volume: float
    muted: bool
    paused: bool
    bar_changed: bool
    shock_event: ShockEvent | None = None


_CHORD_RE = re.compile(r"^([A-G](?:#|b)?)(.*)$")


def parse_chord_symbol(chord_symbol: str, base_octave: int = 4) -> tuple[int, list[int]]:
    """Parse a chord symbol like 'Fmaj9' or 'A7b9' into (bass_midi, chord_midi_notes)."""
    match = _CHORD_RE.match(chord_symbol.strip())
    if not match:
        # Safe fallback: Cmaj7
        return 36, [60, 64, 67, 71]

    root_name, quality = match.group(1), match.group(2)
    semitone = NOTE_TO_SEMITONE.get(root_name, 0)
    intervals = CHORD_INTERVALS.get(quality, CHORD_INTERVALS["maj7"])

    # Bass sits comfortably in warm sub/lo-fi register (C2=36 .. B2=47)
    bass_midi = 36 + semitone
    if bass_midi < 38:
        bass_midi += 12  # Keep D2..C3 warm on laptop/studio speakers

    root_midi = 12 * (base_octave + 1) + semitone  # e.g. C4 = 60
    notes = [root_midi + iv for iv in intervals]
    return bass_midi, notes


def voice_lead_chord(
    target_notes: list[int],
    previous_notes: list[int] | None,
    low_bound: int = 53,
    high_bound: int = 76,
) -> list[int]:
    """Minimize semitone movement from the previous chord for smooth Rhodes/piano voice leading."""
    if not target_notes:
        return [60, 64, 67, 71]

    # Fit pitch classes smoothly around the center of the previous chord
    center = (
        sum(previous_notes) / len(previous_notes)
        if previous_notes
        else 64.0
    )

    voiced: list[int] = []
    for note in target_notes:
        pc = note % 12
        candidates = [pc + 12 * oct_num for oct_num in range(3, 8)]
        valid = [c for c in candidates if low_bound <= c <= high_bound]
        if not valid:
            valid = [note]

        if previous_notes:
            # Prefer close proximity to any voice in previous chord + center gravity
            best = min(
                valid,
                key=lambda c: (
                    min(abs(c - p) for p in previous_notes) * 0.65
                    + abs(c - center) * 0.35
                ),
            )
        else:
            best = min(valid, key=lambda c: abs(c - center))
        voiced.append(best)

    # Deduplicate and keep gentle vertical spacing
    unique_sorted = sorted(set(voiced))
    while len(unique_sorted) < min(4, len(target_notes)):
        candidate = unique_sorted[-1] + 12
        if candidate <= high_bound + 5:
            unique_sorted.append(candidate)
        else:
            break
    return unique_sorted[:5]


def volatility_to_target_bpm(volatility_norm: float, bpm_offset: float = 0.0) -> tuple[float, str]:
    """Map normalized volatility (0..1) into the specification's 4 BPM bands.

    - Low Volatility (< 0.25): 68-74 BPM
    - Normal (0.25..0.60):     74-82 BPM
    - High (0.60..0.85):       82-94 BPM
    - Extreme (>= 0.85):       94-100 BPM
    """
    v = max(0.0, min(1.0, float(volatility_norm)))
    if v < 0.25:
        t = v / 0.25
        bpm = 68.0 + t * (74.0 - 68.0)
        label = "Low"
    elif v < 0.60:
        t = (v - 0.25) / 0.35
        bpm = 74.0 + t * (82.0 - 74.0)
        label = "Normal"
    elif v < 0.85:
        t = (v - 0.60) / 0.25
        bpm = 82.0 + t * (94.0 - 82.0)
        label = "High"
    else:
        t = (v - 0.85) / 0.15
        bpm = 94.0 + t * (100.0 - 94.0)
        label = "Extreme"

    final_bpm = max(68.0, min(100.0, bpm + bpm_offset))
    return final_bpm, label


class MusicalEngine:
    """Stateful real-time Lo-fi composition and musical parameter mapping engine."""

    def __init__(
        self,
        music_config: dict[str, Any],
        presets: dict[str, dict[str, Any]],
    ) -> None:
        self._cfg = music_config
        self._presets = presets
        self._bpm_min = float(music_config.get("bpm_min", 68.0))
        self._bpm_max = float(music_config.get("bpm_max", 100.0))
        self._bpm_slew_rate = float(music_config.get("bpm_slew_rate_per_sec", 0.65))
        self._beats_per_bar = int(music_config.get("beats_per_bar", 4))
        self._arrangement_bars = int(music_config.get("arrangement_bars", 16))

        default_style = str(music_config.get("default_style", "rainy_night"))
        if default_style not in self._presets:
            default_style = next(iter(self._presets))
        self._style_id: str = default_style

        self._master_volume: float = float(music_config.get("master_volume", 0.80))
        self._muted: bool = False
        self._paused: bool = False

        layer_defaults = music_config.get("layer_defaults", {})
        self._layers: dict[str, LayerSettings] = {}
        for name in LAYER_NAMES:
            ld = layer_defaults.get(name, {})
            self._layers[name] = LayerSettings(
                enabled=bool(ld.get("enabled", True)),
                volume=float(ld.get("volume", 0.72)),
            )
        self._apply_preset_volumes(self._style_id)

        # Composition clock & phrase state (changes chords ONLY on bar boundaries!)
        self._current_bpm: float = 75.0
        self._last_update_ts: float | None = None
        self._beat_accumulator: float = 0.0
        self._bar_index: int = 0
        self._intro_bars_remaining: int = 4

        self._active_harmonic_regime: MarketRegime = MarketRegime.SIDEWAYS
        self._pending_harmonic_regime: MarketRegime = MarketRegime.SIDEWAYS
        self._current_chord_name: str = ""
        self._current_chord_notes: list[int] = [60, 64, 67, 71]
        self._current_bass_note: int = 48
        self._current_melody_motif: list[int] = [64, 0, 67, 69, 0, 67, 64, 0]

        self._select_chord_for_bar(bar_idx=0, momentum=0.0, regime=MarketRegime.SIDEWAYS)

    @property
    def style_id(self) -> str:
        return self._style_id

    @property
    def available_styles(self) -> list[tuple[str, str]]:
        return [(pid, str(p.get("name", pid))) for pid, p in self._presets.items()]

    def reset_arrangement(self) -> None:
        """Reset composition clock back to Intro bar 0 smoothly."""
        self._beat_accumulator = 0.0
        self._bar_index = 0
        self._intro_bars_remaining = 4
        self._last_update_ts = None
        self._select_chord_for_bar(0, 0.0, self._active_harmonic_regime)
        logger.info("Musical arrangement reset to Intro.")

    def set_style(self, style_id: str) -> bool:
        """Switch musical style preset; applies cleanly on next musical update."""
        if style_id not in self._presets:
            logger.warning("Unknown musical style requested: %s", style_id)
            return False
        self._style_id = style_id
        self._apply_preset_volumes(style_id)
        self._select_chord_for_bar(self._bar_index, 0.0, self._active_harmonic_regime)
        logger.info("Musical style switched to '%s'", self._presets[style_id].get("name", style_id))
        return True

    def _apply_preset_volumes(self, style_id: str) -> None:
        preset_vols = self._presets[style_id].get("layer_volumes", {})
        for name in LAYER_NAMES:
            if name in preset_vols:
                cur = self._layers.get(name, LayerSettings())
                self._layers[name] = LayerSettings(
                    enabled=cur.enabled,
                    volume=max(0.0, min(1.0, float(preset_vols[name]))),
                )

    def set_layer_enabled(self, layer: str, enabled: bool) -> None:
        if layer in self._layers:
            cur = self._layers[layer]
            self._layers[layer] = LayerSettings(enabled=bool(enabled), volume=cur.volume)

    def set_layer_volume(self, layer: str, volume: float) -> None:
        if layer in self._layers:
            cur = self._layers[layer]
            self._layers[layer] = LayerSettings(
                enabled=cur.enabled,
                volume=max(0.0, min(1.0, float(volume))),
            )

    def set_master_volume(self, volume: float) -> None:
        self._master_volume = max(0.0, min(1.0, float(volume)))

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)

    def get_layer_settings(self) -> dict[str, LayerSettings]:
        return dict(self._layers)

    def update(self, regime_state: RegimeState, now: float | None = None) -> MusicalState:
        """Advance musical clock, smoothly glide BPM, and compute full MusicalState."""
        ts = time.monotonic() if now is None else now
        if self._last_update_ts is None:
            dt = 0.0
        else:
            dt = max(0.0, min(5.0, ts - self._last_update_ts))
        self._last_update_ts = ts

        preset = self._presets[self._style_id]
        bpm_offset = float(preset.get("bpm_offset", 0.0))

        # 1. Volatility -> Smooth Slew-Limited BPM
        target_bpm, vol_label = volatility_to_target_bpm(
            regime_state.volatility_smooth, bpm_offset=bpm_offset
        )
        target_bpm = max(self._bpm_min, min(self._bpm_max, target_bpm))

        if dt > 0.0:
            max_delta = self._bpm_slew_rate * dt
            diff = target_bpm - self._current_bpm
            if abs(diff) <= max_delta:
                self._current_bpm = target_bpm
            else:
                self._current_bpm += math.copysign(max_delta, diff)
        else:
            self._current_bpm = target_bpm

        # Queue regime harmony update (never jump chords mid-bar on a tick!)
        self._pending_harmonic_regime = regime_state.regime

        # 2. Advance musical bar clock (unless paused)
        bar_changed = False
        if not self._paused and dt > 0.0:
            beats_elapsed = (self._current_bpm / 60.0) * dt
            self._beat_accumulator += beats_elapsed
            while self._beat_accumulator >= self._beats_per_bar:
                self._beat_accumulator -= self._beats_per_bar
                self._bar_index += 1
                bar_changed = True
                if self._intro_bars_remaining > 0:
                    self._intro_bars_remaining -= 1

                # Commit new harmonic regime cleanly at 4-bar phrase boundary (or bar boundary on shock)
                if (
                    self._bar_index % 4 == 0
                    or self._pending_harmonic_regime == MarketRegime.MARKET_SHOCK
                ):
                    self._active_harmonic_regime = self._pending_harmonic_regime

                self._select_chord_for_bar(
                    self._bar_index,
                    regime_state.momentum_smooth,
                    self._active_harmonic_regime,
                )

        # 3. Arrangement section (Intro -> 16-bar structured cycle -> Outro/Safe Mode)
        section = self._determine_section(regime_state.safe_mode)
        bar_in_phrase = (self._bar_index % 4) + 1
        bar_in_cycle = (self._bar_index % self._arrangement_bars) + 1

        # 4. Momentum -> Melody Parameters
        mom = max(-1.0, min(1.0, regime_state.momentum_smooth))
        abs_mom = abs(mom)
        melody_direction = 1 if mom > 0.14 else (-1 if mom < -0.14 else 0)
        note_density = max(0.22, min(0.92, 0.34 + 0.45 * abs_mom + 0.15 * regime_state.volatility_smooth))
        arpeggio_intensity = max(0.0, min(1.0, 0.12 + 0.60 * abs_mom + 0.28 * regime_state.volatility_smooth))
        octave_variation = 1 if (abs_mom >= 0.48 or regime_state.regime == MarketRegime.HIGH_VOLATILITY) else 0

        # 5. ATR / Volatility -> Sound Design DSP Parameters
        fx = preset.get("fx_profile", {})
        base_cutoff = float(fx.get("base_cutoff", 82.0))
        base_reverb = float(fx.get("base_reverb", 0.48))
        base_delay = float(fx.get("base_delay", 0.25))

        vol = max(0.0, min(1.0, regime_state.volatility_smooth))
        atr_drive = max(0.0, min(1.0, (regime_state.atr_ratio_smooth - 0.5) / 1.5))

        filter_cutoff = max(62.0, min(116.0, base_cutoff + (atr_drive - 0.35) * 26.0))
        reverb_amount = max(0.20, min(0.78, base_reverb + (0.45 - vol) * 0.22))
        delay_feedback = max(0.12, min(0.55, base_delay + atr_drive * 0.20))
        drum_intensity = max(0.20, min(1.0, 0.32 + 0.58 * vol + 0.12 * abs_mom))
        bass_energy = max(0.35, min(1.0, 0.48 + 0.40 * atr_drive + 0.12 * regime_state.trend_strength))

        if regime_state.safe_mode:
            filter_cutoff = min(filter_cutoff, 72.0)
            drum_intensity = 0.0
            bass_energy = 0.28

        # 6. Arrangement section gain multipliers for natural song dynamics
        section_mix = self._section_mix_multipliers(section)
        effective_master = 0.0 if (self._muted or self._paused) else self._master_volume

        layer_gains: dict[str, float] = {}
        layer_enabled: dict[str, bool] = {}
        for name in LAYER_NAMES:
            ls = self._layers[name]
            layer_enabled[name] = ls.enabled
            gain = (
                ls.volume * section_mix.get(name, 1.0) * effective_master
                if ls.enabled
                else 0.0
            )
            layer_gains[name] = round(max(0.0, min(1.0, gain)), 4)

        root_key = str(preset.get("root_key", "D"))
        key_mode = (
            "Major"
            if self._active_harmonic_regime == MarketRegime.BULLISH
            else ("Minor" if self._active_harmonic_regime == MarketRegime.BEARISH else str(preset.get("default_mode", "minor")).title())
        )
        musical_key = f"{root_key} {key_mode}"

        return MusicalState(
            style_id=self._style_id,
            style_name=str(preset.get("name", self._style_id)),
            regime=self._active_harmonic_regime,
            mood=REGIME_MOODS.get(self._active_harmonic_regime, "Lo-fi Ambient"),
            musical_key=musical_key,
            section=section,
            bar_index=self._bar_index,
            bar_in_phrase=bar_in_phrase,
            bar_in_cycle=bar_in_cycle,
            chord_name=self._current_chord_name,
            chord_notes=list(self._current_chord_notes),
            bass_note=self._current_bass_note,
            melody_motif=list(self._current_melody_motif),
            bpm=round(self._current_bpm, 2),
            target_bpm=round(target_bpm, 2),
            volatility_level=vol_label,
            volatility_norm=round(vol, 4),
            momentum_norm=round(mom, 4),
            melody_direction=melody_direction,
            note_density=round(note_density, 3),
            arpeggio_intensity=round(arpeggio_intensity, 3),
            octave_variation=octave_variation,
            filter_cutoff=round(filter_cutoff, 2),
            reverb_amount=round(reverb_amount, 3),
            delay_feedback=round(delay_feedback, 3),
            drum_intensity=round(drum_intensity, 3),
            bass_energy=round(bass_energy, 3),
            swing=float(preset.get("swing", 0.06)),
            atmosphere_mode=str(preset.get("atmosphere_mode", "rain_vinyl")),
            synths=dict(preset.get("synths", {})),
            drum_kit=dict(preset.get("drum_kit", {})),
            layer_gains=layer_gains,
            layer_enabled=layer_enabled,
            master_volume=round(self._master_volume, 3),
            muted=self._muted,
            paused=self._paused,
            bar_changed=bar_changed,
            shock_event=regime_state.shock_event,
        )

    def _determine_section(self, safe_mode: bool) -> ArrangementSection:
        if safe_mode:
            return ArrangementSection.OUTRO_RESET
        if self._intro_bars_remaining > 0:
            return ArrangementSection.INTRO
        bar_in_16 = self._bar_index % self._arrangement_bars
        if bar_in_16 < 4:
            return ArrangementSection.MAIN_GROOVE
        if bar_in_16 < 8:
            return ArrangementSection.MELODY_DEVELOP
        if bar_in_16 < 12:
            return ArrangementSection.VARIATION_B
        return ArrangementSection.TRANSITION

    @staticmethod
    def _section_mix_multipliers(section: ArrangementSection) -> dict[str, float]:
        if section == ArrangementSection.INTRO:
            return {"harmony": 0.82, "melody": 0.25, "bass": 0.45, "drums": 0.15, "atmosphere": 1.0}
        if section == ArrangementSection.MAIN_GROOVE:
            return {"harmony": 1.0, "melody": 0.65, "bass": 0.90, "drums": 0.85, "atmosphere": 0.85}
        if section == ArrangementSection.MELODY_DEVELOP:
            return {"harmony": 0.95, "melody": 1.0, "bass": 1.0, "drums": 0.95, "atmosphere": 0.80}
        if section == ArrangementSection.VARIATION_B:
            return {"harmony": 1.0, "melody": 0.95, "bass": 1.0, "drums": 1.0, "atmosphere": 0.90}
        if section == ArrangementSection.TRANSITION:
            return {"harmony": 0.90, "melody": 0.80, "bass": 0.85, "drums": 0.72, "atmosphere": 1.0}
        # OUTRO_RESET / Safe Mode: warm ambient chord bed only
        return {"harmony": 0.55, "melody": 0.0, "bass": 0.30, "drums": 0.0, "atmosphere": 0.85}

    def _select_chord_for_bar(
        self,
        bar_idx: int,
        momentum: float,
        regime: MarketRegime,
    ) -> None:
        preset = self._presets[self._style_id]
        progressions = preset.get("progressions", {})
        prog = progressions.get(regime.value) or progressions.get("SIDEWAYS") or ["Dm9", "G13", "Cmaj9", "A7"]

        chord_pos = bar_idx % len(prog)
        chord_name = str(prog[chord_pos])

        # Controlled harmonic variation on bars 9-12 (B-section) without losing key consistency
        bar_in_16 = bar_idx % self._arrangement_bars
        base_octave = 4
        if 8 <= bar_in_16 < 12 and chord_pos in (1, 3):
            # Gently lift voicing register during B-section for musical phrasing
            high_bound = 79
        else:
            high_bound = 75

        bass_midi, raw_notes = parse_chord_symbol(chord_name, base_octave=base_octave)
        voiced = voice_lead_chord(
            raw_notes,
            previous_notes=self._current_chord_notes if self._current_chord_name else None,
            low_bound=53,
            high_bound=high_bound,
        )

        self._current_chord_name = chord_name
        self._current_chord_notes = voiced
        self._current_bass_note = bass_midi
        self._current_melody_motif = self._compose_melody_motif(
            bar_idx=bar_idx,
            regime=regime,
            momentum=momentum,
            root_key=str(preset.get("root_key", "D")),
            chord_notes=voiced,
        )

    def _compose_melody_motif(
        self,
        bar_idx: int,
        regime: MarketRegime,
        momentum: float,
        root_key: str,
        chord_notes: list[int],
    ) -> list[int]:
        """Compose an 8-step scale-locked melodic motif anchored to current chord tones."""
        root_semi = NOTE_TO_SEMITONE.get(root_key, 2)
        intervals = REGIME_SCALES.get(regime, REGIME_SCALES[MarketRegime.SIDEWAYS])
        # Build 2-octave melody scale in singing register (C4..G6)
        scale_notes = sorted(
            {
                60 + root_semi + iv + 12 * oct_shift
                for oct_shift in (0, 1)
                for iv in intervals
                if 60 <= (60 + root_semi + iv + 12 * oct_shift) <= 84
            }
        )
        if not scale_notes:
            scale_notes = [62, 65, 67, 69, 72, 74]

        # Select rhythmic template based on bar position in 4-bar phrase
        phrase_templates: list[list[int]] = [
            [1, 0, 1, 0, 1, 1, 0, 0],  # Bar 1: call
            [0, 1, 0, 1, 0, 1, 1, 0],  # Bar 2: response
            [1, 0, 1, 1, 0, 1, 0, 1],  # Bar 3: build
            [1, 0, 0, 1, 1, 0, 0, 0],  # Bar 4: breathing resolution
        ]
        template = list(phrase_templates[bar_idx % 4])

        # Increase or thin note density deterministically based on momentum magnitude
        if abs(momentum) > 0.55:
            template[1] = 1
            template[6] = 1
        elif abs(momentum) < 0.15 and regime == MarketRegime.COMPRESSION:
            template = [1, 0, 0, 0, 1, 0, 0, 0]

        # Contour driven by momentum direction: ascending / arch / descending
        mid_idx = len(scale_notes) // 2
        if momentum > 0.18:
            # Upward optimistic contour
            step_offsets = [-1, 0, 0, 1, 1, 2, 2, 3]
        elif momentum < -0.18:
            # Gentle descending emotional contour
            step_offsets = [2, 2, 1, 1, 0, 0, -1, -2]
        else:
            # Lyrical arch contour
            step_offsets = [0, 1, 2, 1, 0, 1, 0, -1]

        # Anchor bar downbeat to nearest chord tone so melody locks cleanly to harmony
        anchor = chord_notes[-1] + 12 if chord_notes and chord_notes[-1] < 66 else (chord_notes[-1] if chord_notes else scale_notes[mid_idx])
        anchor_idx = min(range(len(scale_notes)), key=lambda i: abs(scale_notes[i] - anchor))

        motif: list[int] = []
        phrase_shift = (bar_idx // 4) % 2  # Gentle A/B variation across 4-bar phrases
        for step in range(8):
            if template[step] == 0:
                motif.append(0)
            else:
                idx = max(0, min(len(scale_notes) - 1, anchor_idx + step_offsets[step] + phrase_shift))
                note = scale_notes[idx]
                if abs(momentum) > 0.65 and step == 5 and note + 12 <= 86:
                    note += 12
                motif.append(note)
        return motif
