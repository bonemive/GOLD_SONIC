# ==============================================================================
# GOLD SONIC — Layer 1 (Harmony) & Layer 3 (Sidechain-Shaped Warm Bass)
# Zero per-bar child threads, zero orphan FX groups, clean HPF/LPF separation,
# zero chord overlap across bar boundaries, and smooth Beat-1 Kick/Bass pocket.
# ==============================================================================

live_loop :gold_harmony do
  sync :gold_bar
  use_bpm(get(:gs_bpm) || 74.0)

  gain = (get(:gs_gain_harmony) || 0.0).to_f
  stale = gs_is_stale
  gain = [gain, 0.22].min if stale

  if gs_is_active && gain > 0.01
    gs_mark_audio_layer(:harmony)
    notes = get(:gs_chord_notes) || [60, 64, 67, 71]
    h_synth = get(:gs_synth_harmony) || :rhodey
    cutoff = gs_clamp((get(:gs_cutoff) || 82.0).to_f, 62.0, 110.0)
    rev_mix = gs_clamp((get(:gs_reverb) || 0.44).to_f, 0.14, 0.58)
    section = (get(:gs_section) || "Main Progression").to_s
    vol = (get(:gs_volatility) || 0.3).to_f
    swing = (get(:gs_swing) || 0.06).to_f
    voice_scale = 1.0 / [Math.sqrt(notes.length), 1.7].max

    # Sequential execution inside reverb + lpf (zero child threads, real ATR filter sweep on all synths)
    with_fx :reverb, room: 0.60, mix: rev_mix do
      with_fx :lpf, cutoff: cutoff do
        use_synth h_synth

        # Beat 1: Humanized gentle keyboard roll (finishes cleanly before Beat 4)
        roll_elapsed = 0.0
        notes.each_with_index do |n, idx|
          vel = gain * voice_scale * (idx == 0 ? 0.54 : 0.44) * rrand(0.94, 1.04)
          play n,
            amp: vel,
            attack: 0.025,
            decay: 0.35,
            sustain: 1.50,
            release: 0.85,
            pan: rrand(-0.22, 0.22)
          if idx < notes.length - 1
            sleep 0.04
            roll_elapsed += 0.04
          end
        end

        # Beat 3.5: Soft syncopated comping chord (strictly decays before next bar)
        if !stale && (section == "Melody & Bass" || section == "Harmonic Variation" || vol > 0.55)
          wait_t = [2.5 + swing - roll_elapsed, 0.2].max
          sleep wait_t
          upper = notes.length > 2 ? notes[1..-1] : notes
          upper.each_with_index do |n, idx|
            play n,
              amp: gain * voice_scale * 0.24 * rrand(0.92, 1.04),
              attack: 0.015,
              sustain: 0.32,
              release: 0.40,
              pan: rrand(-0.18, 0.18)
            sleep 0.03 if idx < upper.length - 1
          end
        end
      end
    end
  end
end

live_loop :gold_bass do
  sync :gold_bar
  use_bpm(get(:gs_bpm) || 74.0)

  gain = (get(:gs_gain_bass) || 0.0).to_f
  stale = gs_is_stale
  safe_mode = (get(:gs_safe_mode) || 0).to_i == 1

  if gs_is_active && !stale && gain > 0.01
    gs_mark_audio_layer(:bass)
    root = (get(:gs_bass_note) || 38).to_i
    b_synth = get(:gs_synth_bass) || :sine
    bass_en = (get(:gs_bass_energy) || 0.55).to_f
    drums_on = (get(:gs_gain_drums) || 0.0).to_f > 0.05 && !safe_mode
    cutoff = gs_clamp((get(:gs_cutoff) || 80.0).to_f - 14.0, 50.0, 82.0)
    section = (get(:gs_section) || "Main Progression").to_s
    swing = (get(:gs_swing) || 0.06).to_f

    # Sidechain-style bloom attack when drums are active avoids Beat-1 Kick/Bass clash
    beat1_attack = drums_on ? 0.14 : 0.04

    with_fx :lpf, cutoff: cutoff do
      use_synth b_synth
      # Beat 1: Grounded fundamental
      play root,
        amp: gain * (0.44 + 0.20 * bass_en),
        attack: beat1_attack,
        sustain: safe_mode ? 2.4 : 1.10,
        release: 0.42

      unless safe_mode || section == "Intro"
        # Beat 2.5: Syncopated lo-fi pocket pulse
        sleep 1.5 + swing
        play root,
          amp: gain * (0.32 + 0.16 * bass_en),
          attack: 0.03,
          sustain: 0.55,
          release: 0.36

        # Beat 4: Gentle fifth approach (decays cleanly before next bar's Kick)
        if bass_en > 0.45 || section == "Harmonic Variation"
          sleep [1.5 - swing, 0.25].max
          play root + 7,
            amp: gain * (0.28 + 0.14 * bass_en),
            attack: 0.025,
            sustain: 0.32,
            release: 0.28
        end
      end
    end
  end
end
