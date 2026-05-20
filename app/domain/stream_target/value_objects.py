"""Value objects for stream target modelling.

StreamHandle:
    Normalized handle for a platform.

ScheduleMode:
    How scheduling hints from the user are interpreted.
"""

from enum import Enum

from app.domain.shared.types import Platform


class ScheduleMode(Enum):
    """How the user's schedule hints affect prediction.

    ``NONE`` — no manual hints configured; rely purely on learned signals.
    ``HINTED`` — manual hints feed into the predictor as a strong signal
        but do not override learned patterns.
    ``STRICT_HINT`` — manual hints dominate; the predictor trusts the user's
        declared schedule above historical data.
    """

    NONE = "none"
    HINTED = "hinted"
    STRICT_HINT = "strict_hint"


class StreamHandle:
    """Normalized streamer handle for a given platform.

    The handle is auto-normalised (stripped, lowercased) on construction.
    """

    def __init__(self, platform: Platform, handle: str) -> None:
        normalised = handle.strip().lower()
        if not normalised:
            raise ValueError("StreamHandle handle must not be empty")
        self.platform = platform
        self.handle = normalised

    def __repr__(self) -> str:
        return f"{self.platform.value}/{self.handle}"
