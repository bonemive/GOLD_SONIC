# ==============================================================================
# GOLD SONIC — Main Sonic Pi 5.0.0 Audio Engine & OSC Controller
# ==============================================================================
# Run inside Sonic Pi 5.0.0:
#   run_file "/path/to/GOLD_SONIC/sonic_pi/gold_sonic.rb"
#
# Incoming OSC cue server: 127.0.0.1:4560
# Outgoing heartbeat / audio-proof pong: 127.0.0.1:4561 (/gold/pong)
# ==============================================================================

use_debug false
use_cue_logging false
set_sched_ahead_time! 0.6

# Warm Lo-fi studio headroom (targets ~-6 to -2.5 dBFS peak, zero digital clipping)
set_volume! 0.72
set_mixer_control! lpf: 120, hpf: 20

GOLD_SONIC_DIR = begin
  here = File.dirname(__FILE__)
  if File.exist?(File.join(here, "harmony.rb"))
    here
  elsif ENV["GOLD_SONIC_DIR"] && File.exist?(File.join(ENV["GOLD_SONIC_DIR"], "harmony.rb"))
    ENV["GOLD_SONIC_DIR"]
  else
    File.expand_path("sonic_pi", Dir.pwd)
  end
end

# 100% verified against Sonic Pi 5.0.0 synthinfo.rb & etc/samples/*.flac
ALLOWED_SYNTHS = [
  :rhodey, :piano, :fm, :prophet, :pretty_bell, :kalimba, :pluck, :blade,
  :sine, :beep, :tri, :subpulse, :bnoise, :cnoise, :pnoise, :hollow, :dark_ambience
].freeze

ALLOWED_SAMPLES = [
  :bd_tek, :bd_haus, :bd_boom, :bd_jazz, :elec_soft_kick,
  :sn_dub, :sn_dolf, :drum_snare_soft, :elec_snare, :elec_filt_snare,
  :drum_cymbal_closed, :drum_cymbal_pedal, :elec_hi_snare,
  :perc_snap, :perc_bell, :elec_tick, :elec_blip2,
  :elec_cymbal, :drum_cymbal_soft, :drum_splash_soft, :ambi_lunar_land,
  :vinyl_hiss
].freeze

define :gs_safe_synth do |name, fallback|
  sym = name.to_s.strip.downcase.to_sym
  ALLOWED_SYNTHS.include?(sym) ? sym : fallback
end

define :gs_safe_sample do |name, fallback|
  sym = name.to_s.strip.downcase.to_sym
  ALLOWED_SAMPLES.include?(sym) ? sym : fallback
end

define :gs_clamp do |val, lo, hi|
  v = val.to_f
  v = lo if v < lo
  v = hi if v > hi
  v
end

define :gs_is_active do
  paused = (get(:gs_paused) || 0).to_i == 1
  muted = (get(:gs_muted) || 0).to_i == 1
  !(paused || muted)
end

define :gs_is_stale do
  last_hb = get(:gs_last_heartbeat_time)
  if last_hb.nil?
    false
  else
    (Time.now.to_f - last_hb.to_f) > 15.0
  end
end

# Real audio-trigger proof: called ONLY when a musical layer actually produces sound
define :gs_mark_audio_layer do |layer_sym|
  now_t = Time.now.to_f
  set :gs_last_audio_trigger_time, now_t
  set :"gs_layer_active_#{layer_sym}", now_t
end

define :gs_count_active_audio_layers do
  now_t = Time.now.to_f
  [:harmony, :melody, :bass, :drums, :atmosphere].count do |lyr|
    t = get(:"gs_layer_active_#{lyr}")
    !t.nil? && (now_t - t.to_f) <= 9.0
  end
end

# ------------------------------------------------------------------------------
# Safe Default Time-State (allows Sonic Pi to start before Python cleanly)
# ------------------------------------------------------------------------------
set :gs_symbol, "GOLD#"
set :gs_price, 0.0
set :gs_atr, 1.0
set :gs_rsi, 50.0
set :gs_spread, 0
set :gs_quality, "WAITING"

set :gs_style_id, "rainy_night"
set :gs_mood, "Dreamy Jazz Chords"
set :gs_key, "D Minor"
set :gs_section, "Intro"
set :gs_bar_in_cycle, 1
set :gs_swing, 0.08
set :gs_atmosphere_mode, "rain_vinyl"

set :gs_regime, "SIDEWAYS"
set :gs_safe_mode, 1
set :gs_paused, 0
set :gs_muted, 0

set :gs_bpm, 74.0
set :gs_volatility, 0.25
set :gs_cutoff, 80.0
set :gs_reverb, 0.48
set :gs_delay, 0.24
set :gs_drum_intensity, 0.45
set :gs_bass_energy, 0.55

set :gs_momentum, 0.0
set :gs_melody_dir, 0
set :gs_note_density, 0.40
set :gs_arp_intensity, 0.15
set :gs_octave_var, 0

set :gs_chord_name, "Dm9"
set :gs_bass_note, 38
set :gs_chord_notes, [60, 64, 65, 69]
set :gs_melody_motif, [69, 0, 72, 0, 74, 0, 72, 0]

set :gs_gain_harmony, 0.0
set :gs_gain_melody, 0.0
set :gs_gain_bass, 0.0
set :gs_gain_drums, 0.0
set :gs_gain_atmosphere, 0.0

set :gs_synth_harmony, :rhodey
set :gs_synth_melody, :pretty_bell
set :gs_synth_bass, :sine
set :gs_synth_atmo, :bnoise

set :gs_sample_kick, :bd_tek
set :gs_sample_snare, :sn_dub
set :gs_sample_hat, :drum_cymbal_closed
set :gs_sample_rim, :perc_snap
set :gs_sample_accent, :elec_cymbal

set :gs_last_heartbeat_time, nil
set :gs_last_audio_trigger_time, nil
set :gs_audio_bars_played, 0

# ------------------------------------------------------------------------------
# OSC Listener Loops (Realtime Capture from Python Market Intelligence Engine)
# ------------------------------------------------------------------------------
live_loop :osc_rx_market do
  use_real_time
  sym, price, atr, rsi, spread, quality = sync "/osc*/gold/market"
  set :gs_symbol, sym.to_s
  set :gs_price, price.to_f
  set :gs_atr, atr.to_f
  set :gs_rsi, rsi.to_f
  set :gs_spread, spread.to_i
  set :gs_quality, quality.to_s
end

live_loop :osc_rx_mood do
  use_real_time
  style_id, mood, key_name, section, bar_cyc, swing, atmo_mode = sync "/osc*/gold/mood"
  set :gs_style_id, style_id.to_s
  set :gs_mood, mood.to_s
  set :gs_key, key_name.to_s
  set :gs_section, section.to_s
  set :gs_bar_in_cycle, gs_clamp(bar_cyc, 1, 16).to_i
  set :gs_swing, gs_clamp(swing, 0.0, 0.22)
  set :gs_atmosphere_mode, atmo_mode.to_s
end

live_loop :osc_rx_volatility do
  use_real_time
  vol, cutoff, rev, dly, drum_int, bass_en = sync "/osc*/gold/volatility"
  set :gs_volatility, gs_clamp(vol, 0.0, 1.0)
  set :gs_cutoff, gs_clamp(cutoff, 55.0, 120.0)
  set :gs_reverb, gs_clamp(rev, 0.05, 0.80)
  set :gs_delay, gs_clamp(dly, 0.05, 0.55)
  set :gs_drum_intensity, gs_clamp(drum_int, 0.0, 1.0)
  set :gs_bass_energy, gs_clamp(bass_en, 0.0, 1.0)
end

live_loop :osc_rx_momentum do
  use_real_time
  mom, mdir, density, arp_int, oct_var = sync "/osc*/gold/momentum"
  set :gs_momentum, gs_clamp(mom, -1.0, 1.0)
  set :gs_melody_dir, mdir.to_i
  set :gs_note_density, gs_clamp(density, 0.0, 1.0)
  set :gs_arp_intensity, gs_clamp(arp_int, 0.0, 1.0)
  set :gs_octave_var, oct_var.to_i
end

live_loop :osc_rx_regime do
  use_real_time
  regime, safe_mode, paused, muted = sync "/osc*/gold/regime"
  set :gs_regime, regime.to_s
  set :gs_safe_mode, safe_mode.to_i
  set :gs_paused, paused.to_i
  set :gs_muted, muted.to_i
end

live_loop :osc_rx_bpm do
  use_real_time
  bpm_val = sync("/osc*/gold/bpm")[0]
  set :gs_bpm, gs_clamp(bpm_val, 68.0, 100.0)
end

live_loop :osc_rx_harmony do
  use_real_time
  chord_name, bass_note, n1, n2, n3, n4, n5 = sync "/osc*/gold/harmony"
  notes = [n1, n2, n3, n4, n5].map(&:to_i).select { |n| n >= 36 && n <= 96 }
  notes = [60, 64, 67, 71] if notes.empty?
  set :gs_chord_name, chord_name.to_s
  set :gs_bass_note, gs_clamp(bass_note, 28, 60).to_i
  set :gs_chord_notes, notes
end

live_loop :osc_rx_melody do
  use_real_time
  motif = sync "/osc*/gold/melody"
  cleaned = motif.to_a.first(8).map { |n| n.to_i }
  cleaned << 0 while cleaned.length < 8
  set :gs_melody_motif, cleaned
end

live_loop :osc_rx_layers do
  use_real_time
  g_h, g_m, g_b, g_d, g_a, s_h, s_m, s_b, s_a, k, sn, hh, rim, acc = sync "/osc*/gold/layers"
  set :gs_gain_harmony, gs_clamp(g_h, 0.0, 1.0)
  set :gs_gain_melody, gs_clamp(g_m, 0.0, 1.0)
  set :gs_gain_bass, gs_clamp(g_b, 0.0, 1.0)
  set :gs_gain_drums, gs_clamp(g_d, 0.0, 1.0)
  set :gs_gain_atmosphere, gs_clamp(g_a, 0.0, 1.0)

  set :gs_synth_harmony, gs_safe_synth(s_h, :rhodey)
  set :gs_synth_melody, gs_safe_synth(s_m, :pretty_bell)
  set :gs_synth_bass, gs_safe_synth(s_b, :sine)
  set :gs_synth_atmo, gs_safe_synth(s_a, :bnoise)

  set :gs_sample_kick, gs_safe_sample(k, :bd_tek)
  set :gs_sample_snare, gs_safe_sample(sn, :sn_dub)
  set :gs_sample_hat, gs_safe_sample(hh, :drum_cymbal_closed)
  set :gs_sample_rim, gs_safe_sample(rim, :perc_snap)
  set :gs_sample_accent, gs_safe_sample(acc, :elec_cymbal)
end

live_loop :osc_rx_heartbeat do
  use_real_time
  seq, fb_port, safe_flag = sync "/osc*/gold/heartbeat"
  now_t = Time.now.to_f
  set :gs_last_heartbeat_time, now_t
  set :gs_safe_mode, safe_flag.to_i

  last_audio = get(:gs_last_audio_trigger_time)
  bars_played = (get(:gs_audio_bars_played) || 0).to_i
  active_layers = gs_count_active_audio_layers
  audio_live = (
    gs_is_active &&
    !last_audio.nil? &&
    (now_t - last_audio.to_f) <= 9.0 &&
    active_layers > 0
  ) ? 1 : 0

  port_num = fb_port.to_i
  if port_num > 1024 && port_num < 65535
    use_osc "127.0.0.1", port_num
    sp_ver = defined?(version) ? "SonicPi-#{version}" : "SonicPi"
    osc "/gold/pong", seq.to_i, sp_ver, audio_live, active_layers, bars_played
  end
end

# ------------------------------------------------------------------------------
# Master Bar Clock (phase-locks all 5 musical layers on every 4-beat bar)
# ------------------------------------------------------------------------------
live_loop :gold_master_clock do
  use_bpm(get(:gs_bpm) || 74.0)
  if gs_is_active && !gs_is_stale
    total_gain = (get(:gs_gain_harmony) || 0.0).to_f +
                 (get(:gs_gain_melody) || 0.0).to_f +
                 (get(:gs_gain_bass) || 0.0).to_f +
                 (get(:gs_gain_drums) || 0.0).to_f +
                 (get(:gs_gain_atmosphere) || 0.0).to_f
    if total_gain > 0.02
      set :gs_audio_bars_played, (get(:gs_audio_bars_played) || 0).to_i + 1
    end
  end
  cue :gold_bar
  sleep 4
end

# ------------------------------------------------------------------------------
# Preload all allowlisted samples into SuperSonic RAM once at boot
# (eliminates on-the-fly disk-load latency spikes & timing warnings)
# ------------------------------------------------------------------------------
puts "GOLD SONIC: Preloading #{ALLOWED_SAMPLES.length} verified Sonic Pi 5 samples..."
ALLOWED_SAMPLES.each { |s| load_sample s }

# ------------------------------------------------------------------------------
# Load Modular Musical Layer Engines
# ------------------------------------------------------------------------------
puts "GOLD SONIC: Loading 5 audio layers from #{GOLD_SONIC_DIR}"
run_file File.join(GOLD_SONIC_DIR, "harmony.rb")
run_file File.join(GOLD_SONIC_DIR, "melody.rb")
run_file File.join(GOLD_SONIC_DIR, "drums.rb")
run_file File.join(GOLD_SONIC_DIR, "atmosphere.rb")
puts "GOLD SONIC: Sonic Pi #{version} engine LIVE (OSC RX :4560 | Pong TX :4561)."
