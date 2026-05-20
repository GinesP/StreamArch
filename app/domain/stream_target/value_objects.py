"""Value objects for stream target modelling.

Platform:
    Enum of supported streaming platforms.

StreamHandle:
    Normalized handle for a platform.

FavoriteFlag:
    Simple boolean wrapper for favorite state.
"""

from enum import Enum


class Platform(Enum):
    TWITCH = "twitch"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    KICK = "kick"
    OTHER = "other"


class StreamHandle:
    """Normalized streamer handle for a given platform."""

    def __init__(self, platform: Platform, handle: str) -> None:
        self.platform = platform
        self.handle = handle.strip().lower()

    def __repr__(self) -> str:
        return f"{self.platform.value}/{self.handle}"
