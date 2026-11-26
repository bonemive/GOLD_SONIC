"""Static schema & integrity tests for Sonic Pi Ruby composition scripts and presets."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from core.config_loader import PROJECT_ROOT, load_presets
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
)

SONIC_DIR = PROJECT_ROOT / "sonic_pi"
EXPECTED_FILES = ("gold_sonic.rb", "harmony.rb", "melody.rb", "drums.rb", "atmosphere.rb")


def test_all_sonic_pi_files_exist_and_non_empty() -> None:
    for fname in EXPECTED_FILES:
        path = SONIC_DIR / fname
        assert path.exists(), f"Missing Sonic Pi file: {path}"
        assert path.stat().st_size > 200


def test_osc_schema_matches_python_and_sonic_pi_1_to_1() -> None:
    combined = "\n".join((SONIC_DIR / f).read_text(encoding="utf-8") for f in EXPECTED_FILES)
    for addr in (
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
        OSC_PONG,
    ):
        assert addr in combined, f"OSC endpoint {addr} missing from Sonic Pi scripts!"


def test_all_preset_synths_and_samples_are_allowlisted() -> None:
    main_rb = (SONIC_DIR / "gold_sonic.rb").read_text(encoding="utf-8")
    synths_block = re.search(r"ALLOWED_SYNTHS\s*=\s*\[(.*?)\]", main_rb, re.S)
    samples_block = re.search(r"ALLOWED_SAMPLES\s*=\s*\[(.*?)\]", main_rb, re.S)
    assert synths_block and samples_block

    allowed_synths = set(re.findall(r":([a-z0-9_]+)", synths_block.group(1)))
    allowed_samples = set(re.findall(r":([a-z0-9_]+)", samples_block.group(1)))

    presets = load_presets()
    assert len(presets) >= 4
    for pid, preset in presets.items():
        for role, synth_name in preset["synths"].items():
            assert synth_name in allowed_synths, f"Preset {pid} synth {role}={synth_name} not in ALLOWED_SYNTHS"
        for role, sample_name in preset["drum_kit"].items():
            assert sample_name in allowed_samples, f"Preset {pid} sample {role}={sample_name} not in ALLOWED_SAMPLES"


def test_sonic_pi_scripts_avoid_bare_return_and_have_balanced_blocks() -> None:
    open_re = re.compile(r"(?:^\s*(?:if|unless|case|begin)\b|=\s*begin\b|\bdo\s*(?:\|[^|]*\|)?\s*$)")
    close_re = re.compile(r"^\s*end\b")
    for fname in EXPECTED_FILES:
        text = (SONIC_DIR / fname).read_text(encoding="utf-8")
        assert not re.search(r"^\s*return\b", text, re.M), f"Unsafe return in {fname}"
        depth = 0
        for line in text.splitlines():
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            if open_re.search(stripped):
                depth += 1
            if close_re.search(stripped):
                depth -= 1
            assert depth >= 0, f"Unbalanced end in {fname}: {line}"
        assert depth == 0, f"Unclosed Ruby block in {fname}: remaining depth={depth}"


def test_sonic_pi_5_installed_samples_and_ruby_syntax() -> None:
    """When Sonic Pi 5 is installed, verify every allowlisted sample & script against real installation."""
    sp_samples = Path(r"C:\Program Files\Sonic Pi\etc\samples")
    sp_ruby = Path(r"C:\Program Files\Sonic Pi\app\server\native\ruby\bin\ruby.exe")
    if sp_samples.exists():
        main_rb = (SONIC_DIR / "gold_sonic.rb").read_text(encoding="utf-8")
        samples_block = re.search(r"ALLOWED_SAMPLES\s*=\s*\[(.*?)\]", main_rb, re.S)
        assert samples_block
        installed = {p.stem for p in sp_samples.glob("*.flac")}
        for sample_name in re.findall(r":([a-z0-9_]+)", samples_block.group(1)):
            assert sample_name in installed, f"Sample :{sample_name} missing in Sonic Pi 5!"

    if sp_ruby.exists():
        for fname in EXPECTED_FILES:
            res = subprocess.run(
                [str(sp_ruby), "-c", str(SONIC_DIR / fname)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert res.returncode == 0, f"Ruby syntax error in {fname}: {res.stderr}"


