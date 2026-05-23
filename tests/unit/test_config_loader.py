"""Tests for config loader — AppConfig dataclass and load_config function."""

import json
from pathlib import Path

from app.infrastructure.config.loader import AppConfig, load_config


class TestAppConfigDefaults:
    """Default AppConfig — no file overrides."""

    def test_default_user_timezone_is_europe_madrid(self) -> None:
        config = AppConfig()
        assert config.user_timezone == "Europe/Madrid"

    def test_default_log_level(self) -> None:
        config = AppConfig()
        assert config.log_level == "INFO"


class TestLoadConfig:
    """load_config — merging JSON file over defaults."""

    def test_loads_from_json_file(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "test_config.json"
        cfg_path.write_text(
            json.dumps({
                "user_timezone": "America/New_York",
                "log_level": "DEBUG",
            }),
            encoding="utf-8",
        )

        config = load_config(str(cfg_path))
        assert config.user_timezone == "America/New_York"
        assert config.log_level == "DEBUG"

    def test_unknown_keys_ignored(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "test_unknown.json"
        cfg_path.write_text(
            json.dumps({
                "nonexistent_field": "value",
                "user_timezone": "Europe/Madrid",
            }),
            encoding="utf-8",
        )

        config = load_config(str(cfg_path))
        assert config.user_timezone == "Europe/Madrid"
        # Unknown key should not cause error or be set
        assert not hasattr(config, "nonexistent_field")

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "does_not_exist.json"
        config = load_config(str(path))
        assert config.user_timezone == "Europe/Madrid"

    def test_none_path_returns_defaults(self) -> None:
        config = load_config(None)
        assert config.user_timezone == "Europe/Madrid"
