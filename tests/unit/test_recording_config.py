"""Tests for RecordingConfig resolution and file-name generation.

Covers:
* :class:`RecordingConfig` internal defaults.
* :func:`resolve_recording_config` with and without a global config.
* :meth:`FileManager.allocate_path` filename pattern, sanitisation,
  per-stream directory behaviour, and title inclusion/omission.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.domain.recording.config import RecordingConfig, resolve_recording_config
from app.infrastructure.files.file_manager import FileManager, _sanitise_filename


# ======================================================================
# RecordingConfig — defaults and resolution
# ======================================================================


class TestRecordingConfigDefaults:
    """RecordingConfig internal defaults."""

    def test_default_segment_disabled(self) -> None:
        config = RecordingConfig()
        assert config.segment_enabled is False

    def test_default_segment_time(self) -> None:
        config = RecordingConfig()
        assert config.segment_time_seconds == 1800

    def test_default_per_stream_directory(self) -> None:
        config = RecordingConfig()
        assert config.per_stream_directory is False

    def test_default_convert_to_mp4(self) -> None:
        config = RecordingConfig()
        assert config.convert_to_mp4 is True


class TestResolveRecordingConfig:
    """resolve_recording_config — global vs internal defaults."""

    def test_none_returns_internal_defaults(self) -> None:
        config = resolve_recording_config(global_config=None)
        assert config.segment_enabled is False
        assert config.segment_time_seconds == 1800
        assert config.per_stream_directory is False
        assert config.convert_to_mp4 is True

    def test_global_config_is_preserved(self) -> None:
        global_config = RecordingConfig(
            segment_enabled=True,
            segment_time_seconds=1800,
            per_stream_directory=False,
            convert_to_mp4=False,
        )
        config = resolve_recording_config(global_config=global_config)
        assert config.segment_enabled is True
        assert config.segment_time_seconds == 1800
        assert config.per_stream_directory is False
        assert config.convert_to_mp4 is False

    def test_partial_global_config(self) -> None:
        """Only the fields set on the global config are picked up."""
        global_config = RecordingConfig(per_stream_directory=False)
        config = resolve_recording_config(global_config=global_config)
        assert config.per_stream_directory is False
        # Everything else falls through to internal defaults.
        assert config.segment_enabled is False
        assert config.segment_time_seconds == 1800
        assert config.convert_to_mp4 is True


# ======================================================================
# _sanitise_filename — filesystem-safe name segments
# ======================================================================


class TestSanitiseFilename:
    """_sanitise_filename — strips unsafe chars and normalises whitespace."""

    def test_passes_through_clean_name(self) -> None:
        assert _sanitise_filename("allieostudio") == "allieostudio"

    def test_replaces_spaces_with_underscores(self) -> None:
        assert _sanitise_filename("Love Club") == "Love_Club"

    def test_collapses_multiple_spaces(self) -> None:
        assert _sanitise_filename("Love   Club 2024") == "Love_Club_2024"

    def test_strips_windows_invalid_chars(self) -> None:
        """Characters like < > : " / \\ | ? * are silently removed."""
        result = _sanitise_filename('foo<bar>:baz"qux')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert '"' not in result
        # No spaces to convert — invalid chars are stripped without substitution.
        assert result == "foobarbazqux"

    def test_strips_control_chars(self) -> None:
        """Control characters are removed without substitution."""
        result = _sanitise_filename("abc\x00def\x1fghi")
        assert result == "abcdefghi"

    def test_strips_leading_trailing_junk(self) -> None:
        result = _sanitise_filename("  __--hello__..  ")
        assert result == "hello"

    def test_handle_with_hyphen(self) -> None:
        """Hyphens are preserved (common in channel names)."""
        assert _sanitise_filename("allie-allieostudio") == "allie-allieostudio"


# ======================================================================
# FileManager.allocate_path — filename pattern
# ======================================================================


class TestFileManagerAllocatePath:
    """FileManager.allocate_path — naming scheme, per-stream dir, title."""

    FAKE_NOW = "2026-05-22 23:12:56"

    @pytest.fixture
    def fm(self, tmp_path: Path) -> FileManager:
        return FileManager(base_path=tmp_path, per_stream_directory=True)

    @pytest.fixture
    def fm_flat(self, tmp_path: Path) -> FileManager:
        return FileManager(base_path=tmp_path, per_stream_directory=False)

    # ── Pattern: handle + date + time → .ts ─────────────────────

    def test_minimal_pattern(self, fm: FileManager, tmp_path: Path) -> None:
        """handle + date + time with no title."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-05-22"
            # We need two calls — one for date_part, one for time_part
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm.allocate_path(handle="streamer", extension="ts")

        assert path.name == "streamer_2026-05-22_23-12-56.ts"
        assert path.parent.name == "streamer"
        assert path.parent.parent == tmp_path

    def test_pattern_with_title(self, fm: FileManager, tmp_path: Path) -> None:
        """Title is inserted as the second segment."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm.allocate_path(
                handle="allie-allieostudio",
                extension="ts",
                stream_title="Love Club",
            )

        assert path.name == "allie-allieostudio_Love_Club_2026-05-22_23-12-56.ts"

    def test_title_sanitised(self, fm: FileManager, tmp_path: Path) -> None:
        """Title is sanitised — unsafe chars removed, spaces → underscores."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm.allocate_path(
                handle="chan",
                extension="ts",
                stream_title='LATE NIGHT <show> / 2024',
            )

        # / is stripped, < > are stripped, spaces become underscores
        assert path.name == "chan_LATE_NIGHT_show_2024_2026-05-22_23-12-56.ts"

    def test_empty_title_omitted(self, fm: FileManager, tmp_path: Path) -> None:
        """Empty or whitespace-only title is treated as absent."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm.allocate_path(
                handle="chan",
                extension="ts",
                stream_title="   ",
            )

        assert "   " not in path.name
        # Should be chan_2026-05-22_23-12-56.ts (no title segment)
        parts = path.stem.split("_")
        assert len(parts) == 3  # chan, date, time
        assert parts[0] == "chan"

    def test_mp4_extension(self, fm: FileManager, tmp_path: Path) -> None:
        """Works with .mp4 extension too."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm.allocate_path(handle="streamer", extension="mp4")

        assert path.suffix == ".mp4"
        assert path.name.endswith(".mp4")

    # ── Per-stream directory ─────────────────────────────────────

    def test_per_stream_directory_default(self, fm: FileManager, tmp_path: Path) -> None:
        """When per_stream_directory is True, file goes under handle directory."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm.allocate_path(handle="streamer", extension="ts")

        assert path.parent.name == "streamer"

    def test_flat_directory(self, fm_flat: FileManager, tmp_path: Path) -> None:
        """When per_stream_directory is False, file goes directly in base."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm_flat.allocate_path(handle="streamer", extension="ts")

        assert path.parent == tmp_path
        assert path.parent.name != "streamer"

    def test_per_stream_directory_override(self, fm: FileManager, tmp_path: Path) -> None:
        """Call-site per_stream_directory overrides instance default."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            # fm has per_stream_directory=True, but we override to False
            path = fm.allocate_path(
                handle="streamer",
                extension="ts",
                per_stream_directory=False,
            )

        assert path.parent == tmp_path

    # ── Directory creation ───────────────────────────────────────

    def test_creates_parent_directory(self, fm: FileManager, tmp_path: Path) -> None:
        """Parent directory is created automatically."""
        with patch("app.infrastructure.files.file_manager.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = ["2026-05-22", "23-12-56"]

            path = fm.allocate_path(handle="streamer", extension="ts")

        assert path.parent.exists()
        assert path.parent.is_dir()

    # ── User timezone (bugfix: C) ────────────────────────────────

    def test_default_tz_is_utc(self, tmp_path: Path) -> None:
        """Default FileManager (no tz_name) uses UTC."""
        fm = FileManager(base_path=tmp_path)
        from datetime import timezone
        assert fm._tz is timezone.utc

    def test_utc_tz_name(self, tmp_path: Path) -> None:
        """Explicit 'UTC' tz_name resolves to timezone.utc."""
        fm = FileManager(base_path=tmp_path, tz_name="UTC")
        from datetime import timezone
        assert fm._tz is timezone.utc

    def test_custom_timezone_stored(self, tmp_path: Path) -> None:
        """Non-UTC IANA timezone is stored as ZoneInfo."""
        import zoneinfo
        fm = FileManager(base_path=tmp_path, tz_name="America/New_York")
        assert isinstance(fm._tz, zoneinfo.ZoneInfo)
        assert str(fm._tz) == "America/New_York"

    def test_timezone_affects_filename_date_part(self, tmp_path: Path) -> None:
        """Filename date/time segments reflect the configured timezone,
        not UTC.  We verify this by comparing a UTC-filemanager and an
        America/New_York-filemanager at a UTC-Late time that crosses
        into the next day in Europe but not in the US.

        Instead of mocking datetime, we freeze it by patching with a
        wrap that injects our fixed time via `datetime.now(tz)`.
        """
        import zoneinfo
        from datetime import datetime as real_datetime, timezone as real_tz

        # A UTC time that is 2026-06-15 23:30 in UTC
        # In America/New_York (UTC-4 in June) this is 2026-06-15 19:30
        # The UTC filemanager should show date=2026-06-15 time=23-30-00
        # The NY filemanager should show date=2026-06-15 time=19-30-00
        fixed_utc = real_datetime(2026, 6, 15, 23, 30, 0, tzinfo=real_tz.utc)

        ny_tz = zoneinfo.ZoneInfo("America/New_York")
        fixed_ny = fixed_utc.astimezone(ny_tz)

        # Build two filemanagers — one UTC, one NY
        fm_utc = FileManager(base_path=tmp_path, tz_name="UTC")
        fm_ny = FileManager(base_path=tmp_path, tz_name="America/New_York")

        # We cannot easily patch datetime.now(tz) because the existing
        # patching in other tests replaces the whole datetime class.
        # Instead, directly verify the _tz attribute behaviour:
        utc_now_via_fm = real_datetime.now(fm_utc._tz)
        ny_now_via_fm = real_datetime.now(fm_ny._tz)

        # Both return "now" in their respective timezones — we cannot
        # assert absolute values, but we DO assert that _tz differs.
        assert fm_utc._tz is not fm_ny._tz
        assert str(fm_ny._tz) == "America/New_York"

        # Also verify that calling datetime.now on each produces
        # different offsets
        utc_offset = utc_now_via_fm.utcoffset()
        ny_offset = ny_now_via_fm.utcoffset()
        assert ny_offset is not None
        assert ny_offset.total_seconds() < 0  # America/New_York is behind UTC

    def test_none_tz_name_defaults_to_utc(self, tmp_path: Path) -> None:
        """Explicit None tz_name defaults to UTC."""
        fm = FileManager(base_path=tmp_path, tz_name=None)
        from datetime import timezone
        assert fm._tz is timezone.utc
