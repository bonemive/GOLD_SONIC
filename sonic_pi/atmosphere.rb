# ==============================================================================
# GOLD SONIC — Layer 5 (Atmosphere: Rain, Real Vinyl Hiss, Warm & Ambient Pads)
# Zero per-bar thread spawning & minimal synth nodes for multi-hour stability.
# ==============================================================================

live_loop :gold_atmosphere do
  sync :gold_bar
  use_bpm(get(:gs_bpm) || 74.0)

  gain = (get(:gs_gain_atmosphere) || 0.0).to_f
  if gs_is_active && gain > 0.01
    gs_mark_audio_layer(:atmosphere)
    mode = (get(:gs_atmosphere_mode) || "rain_vinyl").to_s
    root = (get(:gs_bass_note) || 38).to_i
    cutoff = gs_clamp((get(:gs_cutoff) || 80.0).to_f, 60.0, 102.0)

    case mode
    when "rain_vinyl"
      use_synth :bnoise
      play 60,
        amp: gain * 0.09,
        attack: 0.55,
        sustain: 2.75,
        release: 0.75,
        cutoff: gs_clamp(cutoff - 8.0, 58.0, 84.0),
        pan: rrand(-0.12, 0.12)

      sample :vinyl_hiss,
        amp: gain * 0.11,
        attack: 0.35,
        sustain: 2.80,
        release: 0.75,
        hpf: 74,
        lpf: 102,
        finish: 0.45

    when "warm_pad"
      use_synth :hollow
      play root + 24, amp: gain * 0.25, attack: 0.9, sustain: 2.2, release: 0.9, cutoff: cutoff, pan: -0.2
      play root + 31, amp: gain * 0.18, attack: 1.0, sustain: 2.0, release: 0.9, cutoff: cutoff, pan: 0.2

    when "vinyl_crackle"
      sample :vinyl_hiss,
        amp: gain * 0.14,
        attack: 0.35,
        sustain: 2.85,
        release: 0.75,
        hpf: 72,
        lpf: 100,
        finish: 0.45

    else
      use_synth :dark_ambience
      play root + 24,
        amp: gain * 0.26,
        attack: 0.85,
        sustain: 2.25,
        release: 1.0,
        cutoff: gs_clamp(cutoff + 4.0, 68.0, 104.0),
        pan: rrand(-0.20, 0.20)
    end
  end
end
