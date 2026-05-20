"""RecordingSession — lifecycle of a detected live stream.

Status lifecycle::

    recording ──► completed
        │             │
        ├──► failed   │
        ├──► aborted  │
        └──► split    │
                       ▼
                  (terminal, read-only)

Invariants:
    - id must be non-empty.
    - detection_latency_seconds must not be negative if set.
    - A terminal session (completed/failed/aborted/split) must have an ended_at.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.shared.types import Platform, QueueBand, RecordingStatus, utc_now


@dataclass
class RecordingSession:
    """A single detected live stream and its lifecycle."""

    id: str
    stream_target_id: str
    started_at: datetime
    ended_at: datetime | None
    status: RecordingStatus
    source_platform: Platform
    stream_title: str | None
    detected_by_queue: QueueBand | None
    detection_latency_seconds: float | None
    scheduled_hint_delay_minutes: int | None
    split_reason: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    # ── Invariants ───────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("RecordingSession id must not be empty")
        if self.detection_latency_seconds is not None and self.detection_latency_seconds < 0:
            raise ValueError(
                f"detection_latency_seconds must not be negative, "
                f"got {self.detection_latency_seconds}"
            )
        if self.is_finished and self.ended_at is None:
            raise ValueError(
                f"A terminal session (status={self.status.value}) "
                f"must have an ended_at timestamp"
            )

    # ── Derived properties ───────────────────────────────────────────

    @property
    def duration_seconds(self) -> float | None:
        """Elapsed or total duration in seconds."""
        end = self.ended_at
        if end is None:
            return None
        return (end - self.started_at).total_seconds()

    @property
    def is_active(self) -> bool:
        """Whether the session is still being recorded."""
        return self.status == RecordingStatus.RECORDING

    @property
    def is_finished(self) -> bool:
        """Whether the session has reached a terminal state."""
        return self.status in (
            RecordingStatus.COMPLETED,
            RecordingStatus.FAILED,
            RecordingStatus.ABORTED,
            RecordingStatus.SPLIT,
        )

    @property
    def is_failed(self) -> bool:
        """Whether the session ended in failure."""
        return self.status == RecordingStatus.FAILED

    # ── State transitions ────────────────────────────────────────────
    #
    # Each transition validates it is called from the correct current
    # state and sets the terminal timestamp automatically.

    def complete(self, ended_at: datetime | None = None) -> None:
        """Mark the session as successfully completed."""
        if self.status != RecordingStatus.RECORDING:
            raise ValueError(
                f"Cannot complete session in status {self.status.value}"
            )
        self.status = RecordingStatus.COMPLETED
        self.ended_at = ended_at or utc_now()
        self.updated_at = utc_now()

    def fail(self, error_code: str, error_message: str) -> None:
        """Mark the session as failed with an error."""
        if self.status != RecordingStatus.RECORDING:
            raise ValueError(
                f"Cannot fail session in status {self.status.value}"
            )
        self.status = RecordingStatus.FAILED
        self.error_code = error_code
        self.error_message = error_message
        self.ended_at = utc_now()
        self.updated_at = utc_now()

    def abort(self, reason: str | None = None) -> None:
        """Abort the session (e.g. on shutdown or user request)."""
        if self.status != RecordingStatus.RECORDING:
            raise ValueError(
                f"Cannot abort session in status {self.status.value}"
            )
        self.status = RecordingStatus.ABORTED
        self.split_reason = reason
        self.ended_at = utc_now()
        self.updated_at = utc_now()

    def split(self, reason: str) -> None:
        """Split the session (e.g. stale gap, reconnect)."""
        if self.status != RecordingStatus.RECORDING:
            raise ValueError(
                f"Cannot split session in status {self.status.value}"
            )
        self.status = RecordingStatus.SPLIT
        self.split_reason = reason
        self.ended_at = utc_now()
        self.updated_at = utc_now()
