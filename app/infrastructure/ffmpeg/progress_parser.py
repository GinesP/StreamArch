"""Parses ffmpeg stderr output to extract progress metrics.

Extracts: duration, speed, fps, bitrate, size.
"""


class FFmpegProgressParser:
    def parse_line(self, line: str) -> dict | None:
        raise NotImplementedError
