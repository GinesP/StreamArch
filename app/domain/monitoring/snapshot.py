"""MonitoringSnapshot — summarised current state of a single target.

This is the primary read model exposed to the UI and used internally
for scheduling decisions.

Invariants:
    - current_likelihood is always in [0.0, 1.0].
    - state is a valid MonitoringState.
    - queue_band, if set, is a valid QueueBand.
    - current_confidence is a valid Confidence level.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.shared.types import Confidence, QueueBand
from app.domain.monitoring.states import MonitoringState


@dataclass
class MonitoringSnapshot:
    """Current operational state summary for one stream target."""

    stream_target_id: str
    state: MonitoringState
    queue_band: QueueBand | None
    current_likelihood: float
    current_confidence: Confidence
    next_check_at: datetime | None
    last_checked_at: datetime | None
    last_live_at: datetime | None
    current_recording_session_id: str | None
    last_error_code: str | None
    last_error_message: str | None
    updated_at: datetime

    # ── Invariants ───────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if not 0.0 <= self.current_likelihood <= 1.0:
            raise ValueError(
                f"current_likelihood must be in [0.0, 1.0], got {self.current_likelihood}"
            )

    # ── Derived state helpers ────────────────────────────────────────

    @property
    def is_live(self) -> bool:
        """Whether the target is currently being recorded."""
        return self.state == MonitoringState.RECORDING

    @property
    def is_checking(self) -> bool:
        """Whether a live check is in progress."""
        return self.state == MonitoringState.CHECKING

    @property
    def is_error(self) -> bool:
        """Whether the target is in an error state."""
        return self.state == MonitoringState.ERROR

    @property
    def is_idle(self) -> bool:
        """Whether the target is idle (no activity)."""
        return self.state == MonitoringState.IDLE

    @property
    def has_error(self) -> bool:
        """Whether an error code has been recorded."""
        return self.last_error_code is not None

    @property
    def last_error(self) -> str | None:
        """Combined error code and message for display."""
        if self.last_error_code and self.last_error_message:
            return f"[{self.last_error_code}] {self.last_error_message}"
        return self.last_error_code or self.last_error_message
