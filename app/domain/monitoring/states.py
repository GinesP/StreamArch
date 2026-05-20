"""State machine for a stream target's monitoring lifecycle.

States:
    idle              — No check pending, no activity.
    checking          — Live check in progress.
    recording         — Stream is being recorded.
    post_processing   — Transmux / remux after recording.
    error             — Unrecoverable error state.
"""

from enum import Enum


class MonitoringState(Enum):
    IDLE = "idle"
    CHECKING = "checking"
    RECORDING = "recording"
    POST_PROCESSING = "post_processing"
    ERROR = "error"
