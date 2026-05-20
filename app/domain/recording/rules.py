"""Domain rules for recording session lifecycle.

Decides when a session should close, split, or trigger remux.
"""


def requires_remux(container_format: str) -> bool:
    """Return True if the format should be remuxed to mp4."""
    return container_format in ("ts", "mkv")


def can_close_session(status: str) -> bool:
    """Return True if the session can be marked as completed."""
    return status in ("recording",)
