"""Graceful shutdown helpers for active ffmpeg processes."""


def stop_ffmpeg_gracefully(process, timeout_seconds: int = 10) -> bool:
    """Send SIGTERM (or equivalent) and wait for graceful exit."""
    raise NotImplementedError
