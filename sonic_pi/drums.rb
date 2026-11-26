# ==============================================================================
# GOLD SONIC — Layer 4 (Adaptive Lo-fi / Jazz / Electronic Drum Engine)
# Zero per-step thread spawning: sequential 16-step swung groove finishes at
# beat 3.75 so it locks tightly to :gold_bar with zero SuperSonic timing drift.
# ==============================================================================

live_loop :gold_drums do
  sync :gold_bar
  use_bpm(get(:gs_bpm) || 74.0)

  gain = (get(:gs_gain_drums) || 0.0).to_f
  stale = gs_is_stale
  safe_mode = (get(:gs_safe_mode) || 0).to_i == 1
  drum_int = (get(:gs_drum_intensity) || 0.45).to_f

  if gs_is_active && !stale && !safe_mode && gain > 0.02 && drum_int > 0.05
    gs_mark_audio_layer(:drums)
    kick = get(:gs_sample_kick) || :bd_tek
    snare = get(:gs_sample_snare) || :sn_dub
    hat = get(:gs_sample_hat) || :drum_cymbal_closed
    rim = get(:gs_sample_rim) || :perc_snap
    swing = gs_clamp((get(:gs_swing) || 0.06).to_f, 0.0, 0.14)
    section = (get(:gs_section) || "Main Progression").to_s
    bar_cyc = (get(:gs_bar_in_cycle) || 1).to_i
    cutoff = gs_clamp((get(:gs_cutoff) || 82.0).to_f + 16.0, 74.0, 118.0)

    kick_steps =
      if section == "Intro"
        [0]
      elsif drum_int >= 0.72
        [0, 6, 8, 10, 14]
      elsif drum_int >= 0.45
        [0, 7, 10]
      else
        [0, 10]
      end

    snare_steps = (section == "Intro") ? [] : [4, 12]
    ghost_rim_steps = (section == "Harmonic Variation" || drum_int >= 0.62) ? [7, 15] : [15]
    swing_amt = swing * 0.45

    16.times do |step|
      # Tight punchy Kick (finish: 0.58 + lpf: 86 avoids overlapping Beat-1 Bass bloom)
      if kick_steps.include?(step)
        k_vel = (step == 0 ? 0.58 : 0.44) * gain * (0.65 + 0.35 * drum_int)
        sample kick, amp: k_vel * rrand(0.94, 1.04), lpf: 86, finish: 0.58
      end

      # Warm Lo-fi Snare / Backbeat
      if snare_steps.include?(step)
        s_vel = 0.42 * gain * (0.60 + 0.40 * drum_int)
        sample snare, amp: s_vel * rrand(0.92, 1.04), hpf: 48, lpf: cutoff, pan: -0.06
      end

      # Soft Rim / Ghost Percussion
      if ghost_rim_steps.include?(step) && section != "Intro"
        sample rim, amp: 0.16 * gain * drum_int, lpf: cutoff, pan: 0.18
      end

      # Crisp Humanized Hi-hat Groove
      if step.even?
        h_vel = (step % 4 == 0 ? 0.18 : 0.12) * gain * (0.55 + 0.45 * drum_int)
        sample hat, amp: h_vel * rrand(0.88, 1.06), hpf: 78, lpf: cutoff, pan: 0.14, rate: rrand(0.97, 1.03)
      elsif drum_int >= 0.65 && (step == 3 || step == 11 || step == 15)
        sample hat, amp: 0.09 * gain * drum_int, hpf: 80, lpf: cutoff, pan: 0.20, rate: 1.05
      end

      # Gentle Bar 16 turnaround fill
      if bar_cyc == 16 && (step == 13 || step == 14)
        sample snare, amp: 0.22 * gain, rate: 0.92, hpf: 50, lpf: cutoff, pan: rrand(-0.14, 0.14)
      end

      if step < 15
        # Sequential swung 16th timing (total 3.75 beats -> always ready for next :gold_bar!)
        step_dur = step.even? ? (0.25 + swing_amt) : (0.25 - swing_amt)
        sleep step_dur
      end
    end
  end
end
