"""Configuration loader — dataclass + JSON file loader using stdlib only.

Usage:
    config = load_config()              # defaults only
    config = load_config("path.json")   # merge file over defaults
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    """Minimal, explicit application configuration.

    All fields have sensible defaults. A JSON config file can override
    any subset of them — everything not present in the file keeps its
    default.
    """

    # ── Directories ──────────────────────────────────────────────
    data_dir: str = field(default="./data")
    db_path: str = field(default="./data/streamarch.db")
    recordings_dir: str = field(default="./data/recordings")

    # ── Logging ──────────────────────────────────────────────────
    log_level: str = field(default="INFO")
    log_format: str = field(default="detailed")  # "detailed" | "simple"

    # ── Platform limits ──────────────────────────────────────────
    max_concurrent_checks: int = field(default=5)
    max_concurrent_recordings: int = field(default=2)

    # ── Scheduler intervals (seconds) ────────────────────────────
    default_check_interval_seconds: int = field(default=300)
    fast_band_interval_seconds: int = field(default=60)
    medium_band_interval_seconds: int = field(default=300)
    slow_band_interval_seconds: int = field(default=900)

    # ── API ──────────────────────────────────────────────────────
    api_host: str = field(default="127.0.0.1")
    api_port: int = field(default=8899)

    # ── Database ─────────────────────────────────────────────────
    db_pool_size: int = field(default=1)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from an optional JSON file, merging over defaults.

    If *config_path* is ``None`` or the file does not exist, all defaults
    are used.  If the file exists, only the keys present in the JSON are
    overridden — unknown keys are silently ignored.
    """
    config = AppConfig()

    if config_path is not None:
        path = Path(config_path)
        if path.is_file():
            with path.open("r", encoding="utf-8") as f:
                overrides = json.load(f)
            for key, value in overrides.items():
                if hasattr(config, key):
                    setattr(config, key, value)

    return config
