"""Manages ffmpeg subprocess lifecycle."""

import subprocess


class FFmpegProcessRunner:
    """Spawns, monitors, and terminates ffmpeg processes."""

    def start(self, output_path: str, stream_url: str, **options) -> subprocess.Popen:
        raise NotImplementedError

    def stop(self, process: subprocess.Popen) -> None:
        raise NotImplementedError
