# ==============================================================================
# GOLD SONIC — Layer 2 (Melody + Momentum Arpeggios) & Market Shock Accent
# Zero per-step threads, sequential swung grid, clean echo tails, breathing room.
# ==============================================================================

live_loop :gold_melody do
  sync :gold_bar
  use_bpm(get(:gs_bpm) || 74.0)

  gain = (get(:gs_gain_melody) || 0.0).to_f
  stale = gs_is_stale
  safe_mode = (get(:gs_safe_mode) || 0).to_i == 1

  if gs_is_active && !stale && !safe_mode && gain > 0.01
    gs_mark_audio_layer(:melody)
    motif = get(:gs_melody_motif) || [69, 0, 72, 0, 74, 0, 72, 0]
    chord_notes = get(:gs_chord_notes) || [60, 64, 67, 71]
    m_synth = get(:gs_synth_melody) || :pretty_bell
    cutoff = gs_clamp((get(:gs_cutoff) || 84.0).to_f + 8.0, 68.0, 112.0)
    dly_fb = gs_clamp((get(:gs_delay) || 0.24).to_f, 0.10, 0.44)
    arp_int = (get(:gs_arp_intensity) || 0.20).to_f
    swing = gs_clamp((get(:gs_swing) || 0.06).to_f, 0.0, 0.14)
    bar_cyc = (get(:gs_bar_in_cycle) || 1).to_i

    # Soften cadence bar (4/8/12/16) for organic non-repetitive musical phrasing
    cadence_soften = (bar_cyc % 4 == 0) ? 0.76 : 1.0

    # Clean echo + lpf FX (sequential loop = 3.75 beats -> finishes cleanly before next :gold_bar)
    with_fx :echo, phase: 0.75, decay: 1.0 + (dly_fb * 1.8), mix: dly_fb * 0.50 do
      with_fx :lpf, cutoff: cutoff do
        use_synth m_synth
        8.times do |step|
          note_val = motif[step].to_i

          if note_val > 0
            play note_val,
              amp: gain * cadence_soften * (step % 2 == 0 ? 0.34 : 0.25) * rrand(0.92, 1.05),
              attack: 0.015,
              sustain: 0.15,
              release: 0.55,
              pan: rrand(-0.30, 0.30)
          elsif arp_int > 0.58 && (step == 3 || step == 7) && (bar_cyc % 2 == 1)
            arp_note = chord_notes[step % chord_notes.length] + 12
            play arp_note,
              amp: gain * 0.18 * arp_int,
              attack: 0.01,
              release: 0.36,
              pan: rrand(-0.36, 0.36)
          end

          if step < 7
            # Alternating swung 8th-note durations (zero thread spawning!)
            step_dur = step.even? ? (0.5 + swing) : (0.5 - swing)
            sleep step_dur
          end
        end
      end
    end
  end
end

# ------------------------------------------------------------------------------
# Market Shock Event: Reverse Cymbal + Percussion Accent + Bass Drop + Arp Burst
# (Cooldown strictly enforced in Python's RegimeDetector)
# ------------------------------------------------------------------------------
live_loop :gold_shock_accent do
  use_real_time
  intensity, direction, _spike_atr = sync "/osc*/gold/shock"

  if gs_is_active
    use_bpm(get(:gs_bpm) || 82.0)
    inten = gs_clamp(intensity, 0.35, 1.0)
    dir = direction.to_i
    master_scale = [
      (get(:gs_gain_harmony) || 0.5).to_f,
      (get(:gs_gain_melody) || 0.5).to_f,
      (get(:gs_gain_drums) || 0.5).to_f
    ].max

    if master_scale >= 0.05
      gs_mark_audio_layer(:melody)
      bass_note = (get(:gs_bass_note) || 38).to_i
      chord_notes = get(:gs_chord_notes) || [60, 64, 67, 71]
      accent_sample = get(:gs_sample_accent) || :elec_cymbal
      m_synth = get(:gs_synth_melody) || :pretty_bell

      with_fx :reverb, room: 0.68, mix: 0.42 do
        # 1. Reverse cymbal swell
        sample :drum_splash_soft,
          rate: -0.65,
          amp: master_scale * 0.24 * inten,
          lpf: 100

        sleep 0.35

        # 2. Crisp percussion accent
        sample accent_sample,
          amp: master_scale * 0.25 * inten,
          lpf: 106

        # 3. Short warm sub bass drop
        use_synth :sine
        s = play bass_note + 12,
          amp: master_scale * 0.32 * inten,
          attack: 0.015,
          sustain: 0.42,
          release: 0.45,
          note_slide: 0.36
        control s, note: bass_note

        # 4. Directional musical arpeggio burst locked to current chord
        use_synth m_synth
        burst = chord_notes.map { |n| n + 12 }
        burst = burst.reverse if dir < 0
        burst.each do |n|
          play n,
            amp: master_scale * 0.24 * inten,
            attack: 0.01,
            release: 0.45,
            pan: rrand(-0.40, 0.40)
          sleep 0.125
        end
      end
    end
  end
end
