"""Configuration, preset management, and rotating logging setup for GOLD SONIC."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
PRESETS_DIR = PROJECT_ROOT / "presets"


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load and validate GOLD SONIC configuration from JSON."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    required_sections = ("mt5", "market_intelligence", "musical_engine", "osc", "logging")
    missing = [sec for sec in required_sections if sec not in data]
    if missing:
        raise ValueError(f"Missing required config sections: {', '.join(missing)}")
    return data


def save_config(config: dict[str, Any], config_path: Path | str | None = None) -> None:
    """Persist configuration updates atomically to disk."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def load_presets(presets_dir: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Load all musical style preset JSON files keyed by preset id."""
    directory = Path(presets_dir) if presets_dir else PRESETS_DIR
    if not directory.exists():
        raise FileNotFoundError(f"Presets directory not found: {directory}")

    presets: dict[str, dict[str, Any]] = {}
    for file_path in sorted(directory.glob("*.json")):
        with file_path.open("r", encoding="utf-8") as fh:
            preset = json.load(fh)
        preset_id = preset.get("id") or file_path.stem
        preset["id"] = preset_id
        presets[preset_id] = preset

    if not presets:
        raise ValueError(f"No musical style presets found in {directory}")
    return presets


def setup_logging(config: dict[str, Any], base_dir: Path | None = None) -> logging.Logger:
    """Configure root logger with rotating file handler and console stream."""
    log_cfg = config.get("logging", {})
    level_name = str(log_cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root_dir = base_dir or PROJECT_ROOT
    log_dir = root_dir / log_cfg.get("log_dir", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "gold_sonic.log"

    logger = logging.getLogger("gold_sonic")
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=int(log_cfg.get("max_bytes", 5 * 1024 * 1024)),
            backupCount=int(log_cfg.get("backup_count", 5)),
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        stream_handler.setLevel(level)
        logger.addHandler(stream_handler)

    return logger
