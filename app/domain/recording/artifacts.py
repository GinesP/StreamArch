"""RecordingArtifact — a file produced during a recording session.

Invariants:
    - id must be non-empty.
    - size_bytes must not be negative if set.
    - duration_seconds must not be negative if set.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.shared.types import ArtifactStatus, ArtifactType, ContainerFormat
from app.domain.recording.rules import requires_remux


@dataclass
class RecordingArtifact:
    """A file produced as part of a recording session."""

    id: str
    recording_session_id: str
    artifact_type: ArtifactType
    path: str
    container_format: ContainerFormat
    status: ArtifactStatus
    size_bytes: int | None
    duration_seconds: float | None
    checksum: str | None
    created_at: datetime
    updated_at: datetime

    # ── Invariants ───────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("RecordingArtifact id must not be empty")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError(
                f"size_bytes must not be negative, got {self.size_bytes}"
            )
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError(
                f"duration_seconds must not be negative, "
                f"got {self.duration_seconds}"
            )

    # ── Derived state helpers ────────────────────────────────────────

    @property
    def needs_remux(self) -> bool:
        """Whether this artifact should be remuxed to a final format."""
        return requires_remux(self.container_format)

    @property
    def is_finalized(self) -> bool:
        """Whether the artifact is in a terminal state."""
        return self.status in (
            ArtifactStatus.READY,
            ArtifactStatus.FAILED,
            ArtifactStatus.DELETED,
        )
