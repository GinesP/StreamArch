"""Configuration loader — reads config from file with env overrides.

Supports YAML/TOML/JSON config files (to be decided).
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    db_path: str = "streamarch.db"
    log_level: str = "INFO"
    log_file: str | None = None
    recording_path: str = "recordings"
    max_concurrent_checks: int = 5
    max_concurrent_recordings: int = 3
    jitter_pct: float = 0.15
    platform_limits: dict = field(default_factory=lambda: {"twitch": 3, "youtube": 2})


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from file, falling back to defaults + env overrides."""
    # Stub — returns defaults for now
    return AppConfig()
