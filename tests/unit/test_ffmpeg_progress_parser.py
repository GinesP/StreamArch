"""Tests for ffmpeg stderr progress parsing.

These are pure-logic tests — no mocking, no subprocess.
"""

import pytest

from app.infrastructure.ffmpeg.progress_parser import parse_progress_line


class TestParseProgressLine:
    """parse_progress_line extracts structured data from ffmpeg stderr."""

    def test_typical_progress_line(self) -> None:
        """A standard ffmpeg progress line is fully parsed."""
        line = (
            "frame=  123 fps=30.0 q=-1.0 size=    1234KiB "
            "time=00:00:04.10 bitrate=1234.5kbits/s speed=1.00x"
        )
        result = parse_progress_line(line)
        assert result is not None
        assert result["frame"] == 123
        assert result["fps"] == 30.0
        # 1234 KiB = 1234 * 1024 = 1_263_616
        assert result["size_bytes"] == 1_263_616
        assert result["time_seconds"] == pytest.approx(4.10, rel=1e-3)
        assert result["bitrate_kbps"] == pytest.approx(1234.5, rel=1e-3)
        assert result["speed"] == 1.0

    def test_large_file(self) -> None:
        """Large files with MiB unit are parsed correctly."""
        line = (
            "frame= 9999 fps=60.0 q=28.0 size=   20480MiB "
            "time=01:23:45.67 bitrate=8500.0kbits/s speed=2.50x"
        )
        result = parse_progress_line(line)
        assert result is not None
        assert result["frame"] == 9999
        assert result["fps"] == 60.0
        # 20480 MiB = 20480 * 1_048_576 = 21_474_836_480
        assert result["size_bytes"] == 21_474_836_480
        assert result["time_seconds"] == pytest.approx(5025.67, rel=1e-3)
        assert result["bitrate_kbps"] == 8500.0
        assert result["speed"] == 2.5

    def test_zero_values(self) -> None:
        """A line with all-zero values is still parsed."""
        line = (
            "frame=    0 fps=0.0 q=0.0 size=       0kB "
            "time=00:00:00.00 bitrate=   0.0kbits/s speed=0x"
        )
        result = parse_progress_line(line)
        assert result is not None
        assert result["frame"] == 0
        assert result["fps"] == 0.0
        assert result["size_bytes"] == 0
        assert result["time_seconds"] == 0.0
        assert result["bitrate_kbps"] == 0.0
        assert result["speed"] == 0.0

    def test_kB_unit(self) -> None:
        """kB (1000-byte kilobyte) is handled."""
        line = (
            "frame=  50 fps=25.0 q=-1.0 size=     500kB "
            "time=00:00:02.00 bitrate=2000.0kbits/s speed=1.00x"
        )
        result = parse_progress_line(line)
        assert result is not None
        # 500 kB = 500 * 1000 = 500_000
        assert result["size_bytes"] == 500_000

    def test_MB_unit(self) -> None:
        """MB (1_000_000-byte megabyte) is handled."""
        line = (
            "frame= 100 fps=30.0 q=-1.0 size=      10MB "
            "time=00:00:05.00 bitrate=16000.0kbits/s speed=1.00x"
        )
        result = parse_progress_line(line)
        assert result is not None
        # 10 MB = 10 * 1_000_000 = 10_000_000
        assert result["size_bytes"] == 10_000_000

    def test_missing_q_field(self) -> None:
        """Some ffmpeg builds omit the q= field — parser still works."""
        line = (
            "frame=   1 fps=30.0 size=      64KiB "
            "time=00:00:00.03 bitrate=17476.3kbits/s speed=0.997x"
        )
        result = parse_progress_line(line)
        assert result is not None
        assert result["frame"] == 1
        assert result["fps"] == 30.0

    def test_non_progress_line_returns_none(self) -> None:
        """Non-progress lines like headers return None."""
        lines = [
            "ffmpeg version 6.0 Copyright (c) 2000-2023 the FFmpeg developers",
            "  libavutil      58.  2.100 / 58.  2.100",
            "Input #0, mpegts, from 'https://example.com/stream.m3u8'",
            "Output #0, mpegts, to '/data/recording.ts'",
            "Press [q] to stop, [?] for help",
            "",
            "  Stream #0:0 -> #0:0 (copy)",
        ]
        for line in lines:
            assert parse_progress_line(line) is None, f"Expected None for: {line!r}"

    def test_partial_line_returns_none(self) -> None:
        """A line that looks like progress but is missing fields returns None."""
        line = "frame=  123 fps=30.0 q=-1.0"
        assert parse_progress_line(line) is None

    def test_empty_line(self) -> None:
        """Empty string returns None."""
        assert parse_progress_line("") is None
        assert parse_progress_line("   ") is None

    def test_noisy_line_with_progress(self) -> None:
        """A line with extra whitespace or noise still matches."""
        line = (
            "    frame=   42 fps=24.0 q=0.0 size=     128KiB "
            "time=00:00:01.75 bitrate= 600.5kbits/s speed=0.99x    "
        )
        result = parse_progress_line(line)
        assert result is not None
        assert result["frame"] == 42
        assert result["fps"] == 24.0
        assert result["time_seconds"] == pytest.approx(1.75, rel=1e-3)
