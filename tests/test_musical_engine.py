"""Unit tests for MusicalEngine theory, voice leading, BPM slew, and arrangement."""

from __future__ import annotations

from core.config_loader import load_config, load_presets
from core.musical_engine import (
    ArrangementSection,
    MusicalEngine,
    parse_chord_symbol,
    voice_lead_chord,
    volatility_to_target_bpm,
)
from core.regime_detector import MarketRegime, RegimeState


def _make_regime_state(
    regime: MarketRegime = MarketRegime.SIDEWAYS,
    vol: float = 0.35,
    mom: float = 0.0,
    atr_ratio: float = 1.0,
    safe_mode: bool = False,
) -> RegimeState:
    return RegimeState(
        regime=regime,
        raw_candidate=regime,
        confidence=0.85,
        trend_label="Neutral",
        volatility_smooth=vol,
        momentum_smooth=mom,
        atr_ratio_smooth=atr_ratio,
        trend_strength=0.4,
        safe_mode=safe_mode,
        safe_mode_reason="Disconnected" if safe_mode else "",
        shock_event=None,
        shock_cooldown_remaining=0.0,
        regime_age_seconds=15.0,
    )


def test_volatility_to_bpm_exact_ranges() -> None:
    bpm_low, lbl_low = volatility_to_target_bpm(0.10)
    assert 68.0 <= bpm_low <= 74.0 and lbl_low == "Low"

    bpm_norm, lbl_norm = volatility_to_target_bpm(0.42)
    assert 74.0 <= bpm_norm <= 82.0 and lbl_norm == "Normal"

    bpm_high, lbl_high = volatility_to_target_bpm(0.72)
    assert 82.0 <= bpm_high <= 94.0 and lbl_high == "High"

    bpm_ext, lbl_ext = volatility_to_target_bpm(0.95)
    assert 94.0 <= bpm_ext <= 100.0 and lbl_ext == "Extreme"


def test_voice_leading_minimizes_jumps() -> None:
    _, dm9 = parse_chord_symbol("Dm9")
    _, g13 = parse_chord_symbol("G13")
    v1 = voice_lead_chord(dm9, None)
    v2 = voice_lead_chord(g13, v1)
    assert len(v2) >= 4
    assert all(53 <= n <= 79 for n in v2)
    # Average voice motion should stay compact (jazz smooth voice leading)
    avg_step = sum(min(abs(n - p) for p in v1) for n in v2) / len(v2)
    assert avg_step <= 4.0


def test_bpm_changes_smoothly_and_chords_do_not_jump_mid_bar() -> None:
    cfg = load_config()
    presets = load_presets()
    eng = MusicalEngine(cfg["musical_engine"], presets)

    s0 = eng.update(_make_regime_state(MarketRegime.SIDEWAYS, vol=0.10), now=0.0)
    initial_chord = s0.chord_name

    # Sudden volatility spike + regime shift after only 0.5 seconds (mid-bar!)
    s1 = eng.update(_make_regime_state(MarketRegime.HIGH_VOLATILITY, vol=0.95), now=0.5)
    # BPM must NOT jump instantly to 98; max slew is 0.65 * 0.5 = 0.325 BPM!
    assert abs(s1.bpm - s0.bpm) <= 0.5
    # Chord must NOT change mid-bar!
    assert s1.chord_name == initial_chord
    assert s1.bar_changed is False


def test_arrangement_progresses_through_intro_and_16_bar_sections() -> None:
    cfg = load_config()
    presets = load_presets()
    eng = MusicalEngine(cfg["musical_engine"], presets)

    seen_sections: set[ArrangementSection] = set()
    t = 0.0
    st = _make_regime_state(MarketRegime.BULLISH, vol=0.45, mom=0.5)
    # Step 1 second at a time across ~85 seconds (~26+ bars at ~76 BPM)
    for _ in range(90):
        ms = eng.update(st, now=t)
        seen_sections.add(ms.section)
        t += 1.0

    assert ArrangementSection.INTRO in seen_sections
    assert ArrangementSection.MAIN_GROOVE in seen_sections
    assert ArrangementSection.MELODY_DEVELOP in seen_sections
    assert ArrangementSection.VARIATION_B in seen_sections
    assert ArrangementSection.TRANSITION in seen_sections


def test_presets_layer_controls_and_safe_mode() -> None:
    cfg = load_config()
    presets = load_presets()
    eng = MusicalEngine(cfg["musical_engine"], presets)

    for style_id in ("rainy_night", "golden_sunrise", "midnight_jazz", "market_pulse"):
        assert eng.set_style(style_id) is True
        ms = eng.update(_make_regime_state(MarketRegime.BULLISH), now=10.0)
        assert ms.style_id == style_id
        assert len(ms.chord_notes) >= 4
        assert len(ms.melody_motif) == 8

    # Mute disables all output gains
    eng.set_muted(True)
    ms_muted = eng.update(_make_regime_state(), now=11.0)
    assert all(g == 0.0 for g in ms_muted.layer_gains.values())

    # Unmute + disable drums only
    eng.set_muted(False)
    eng.set_layer_enabled("drums", False)
    ms_nodrums = eng.update(_make_regime_state(), now=12.0)
    assert ms_nodrums.layer_gains["drums"] == 0.0
    assert ms_nodrums.layer_gains["harmony"] > 0.0

    # Safe mode switches to Outro/Safe Mode with drums at 0
    ms_safe = eng.update(_make_regime_state(safe_mode=True), now=13.0)
    assert ms_safe.section == ArrangementSection.OUTRO_RESET
    assert ms_safe.layer_gains["drums"] == 0.0
