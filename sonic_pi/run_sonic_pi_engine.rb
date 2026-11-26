# ==============================================================================
# GOLD SONIC — Headless Sonic Pi 5.0.0 Live Audio Engine Launcher
# ==============================================================================
# Uses Sonic Pi 5.0.0's official headless_boot harness to boot SuperSonic +
# Spider Server on UDP port 4560 (audible output, NOT muted) and run
# sonic_pi/gold_sonic.rb continuously until stopped or optional duration expires.
#
# Usage:
#   "C:\Program Files\Sonic Pi\app\server\native\ruby\bin\ruby.exe" ^
#     sonic_pi/run_sonic_pi_engine.rb [duration_seconds]
# ==============================================================================

BOOT_LIB = "C:/Program Files/Sonic Pi/app/server/ruby/bin/headless_boot"
abort "Sonic Pi 5.0.0 headless_boot not found at #{BOOT_LIB}.rb" unless File.exist?("#{BOOT_LIB}.rb")

require BOOT_LIB

duration = ARGV[0] ? ARGV[0].to_f : nil
script_path = File.expand_path("gold_sonic.rb", __dir__)
abort "gold_sonic.rb not found at #{script_path}" unless File.exist?(script_path)

stop_requested = false
Signal.trap("INT")  { stop_requested = true }
Signal.trap("TERM") { stop_requested = true }

boot = SonicPi::HeadlessBoot.new.boot!
boot.say "GOLD SONIC Audio Engine READY (duration=#{duration ? "#{duration}s" : "continuous"})"
boot.run(File.read(script_path))

started = Time.now.to_f
until stop_requested
  break if duration && (Time.now.to_f - started) >= duration
  sleep 0.25
end

boot.say "Stopping GOLD SONIC Sonic Pi engine..."
boot.stop_all
sleep 1.0
boot.say "SUMMARY: errors=#{boot.errors.length}"
boot.errors.each { |e| boot.say "  ERROR: #{e}" }
exit(boot.errors.empty? ? 0 : 2)
