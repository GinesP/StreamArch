"""Parses ffmpeg stderr output to extract progress metrics.

Extracts: duration, speed, fps, bitrate, size.

The typical ffmpeg progress line looks like::

    frame=  123 fps=30.0 q=-1.0 size=    1234KiB time=00:00:04.10 \\
        bitrate=1234.5kbits/s speed=1.00x

Some variations (YouTube-dl style, older ffmpeg) omit ``q=`` or use
different unit suffixes — the parser handles them gracefully.
"""

import re
from typing import TypedDict


class FFmpegProgress(TypedDict, total=False):
    """Structured progress data extracted from an ffmpeg stderr line."""

    frame: int
    fps: float
    size_bytes: int
    time_seconds: float
    bitrate_kbps: float
    speed: float


# ── Regex ──────────────────────────────────────────────────────────────
#
# The progress line is a space-separated list of key=value pairs.
# We capture frame, fps, size (with unit), time, bitrate, and speed.
#
# Examples:
#   frame=  123 fps=30.0 q=-1.0 size=    1234KiB time=00:00:04.10 bitrate=1234.5kbits/s speed=1.00x
#   frame=123 fps=30 q=28 size=1234kB time=00:01:23.45 bitrate=1234.5kbits/s speed=1.00x
#   frame= 0 fps=0.0 q=0.0 size= 0KiB time=00:00:00.00 bitrate= 0.0kbits/s speed=0x

_PROGRESS_RE = re.compile(
    r"frame=\s*(?P<frame>\d+)"                          # frame=  123
    r"\s+fps=\s*(?P<fps>[\d.]+)"                        # fps=30.0
    r"(?:\s+q=[-\d.]+)?"                                 # q=-1.0 (optional, captured but skipped)
    r"\s+size=\s*(?P<size>\d+)\s*(?P<size_unit>kB|KiB|MB|MiB)?"  # size= 1234KiB
    r"\s+time=(?P<time>\d+:\d+:\d+\.\d+)"                # time=00:00:04.10
    r"\s+bitrate=\s*(?P<bitrate>[\d.]+)kbits/s"          # bitrate=1234.5kbits/s
    r"\s+speed=\s*(?P<speed>[\d.]+)x",                   # speed=1.00x
)


# ── Size multiplier map ────────────────────────────────────────────────

_SIZE_MULTIPLIER: dict[str, int] = {
    "kB": 1_000,
    "KiB": 1_024,
    "MB": 1_000_000,
    "MiB": 1_048_576,
}


# ── Public API ─────────────────────────────────────────────────────────


def parse_progress_line(line: str) -> FFmpegProgress | None:
    """Parse a single ffmpeg stderr progress line into a structured dict.

    Args:
        line: A line from ffmpeg stderr (typically from the verbose output
              shown during encoding).

    Returns:
        An :class:`FFmpegProgress` dict with parsed values, or ``None`` if
        the line does not look like a progress line.

    Example::

        >>> parse_progress_line(
        ...     "frame=  123 fps=30.0 q=-1.0 size=    1234KiB "
        ...     "time=00:00:04.10 bitrate=1234.5kbits/s speed=1.00x"
        ... )
        {"frame": 123, "fps": 30.0, "size_bytes": 1263616, ...}
    """
    match = _PROGRESS_RE.search(line)
    if not match:
        return None

    result: FFmpegProgress = {}

    # Frame count
    result["frame"] = int(match.group("frame"))

    # FPS (float)
    result["fps"] = float(match.group("fps"))

    # Size in bytes (convert from KiB/kB/MiB/MB)
    raw_size = int(match.group("size"))
    unit = match.group("size_unit")
    if unit and unit in _SIZE_MULTIPLIER:
        result["size_bytes"] = raw_size * _SIZE_MULTIPLIER[unit]
    else:
        result["size_bytes"] = raw_size  # Unknown unit — treat as bytes

    # Time in seconds (HH:MM:SS.mmm)
    time_str = match.group("time")
    parts = time_str.split(":")
    result["time_seconds"] = (
        int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    )

    # Bitrate in kbps
    result["bitrate_kbps"] = float(match.group("bitrate"))

    # Speed multiplier
    result["speed"] = float(match.group("speed"))

    return result
