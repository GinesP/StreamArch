"""Transmux/remux from .ts/.mkv to .mp4 using ffmpeg."""


class FFmpegTransmuxer:
    def remux(self, source_path: str, output_path: str) -> str:
        """Remux to mp4 and return the output path."""
        raise NotImplementedError
