"""StreamTarget entity — a monitorizable streamer.

Invariants:
    - id must be non-empty.
    - handle must be non-empty.
    - preferred_quality, if provided, must not be blank.
    - schedule_mode is one of the ScheduleMode enum values.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.shared.types import Platform
from app.domain.stream_target.value_objects import ScheduleMode


@dataclass
class StreamTarget:
    """A streamer or channel that can be monitored and recorded.

    This is the central configuration entity — it captures *what* the user
    wants to track and *how* the system should treat it.
    """

    id: str
    platform: Platform
    handle: str
    source_url: str
    display_name: str
    enabled: bool
    favorite: bool
    preferred_quality: str | None
    output_profile_id: str | None
    schedule_mode: ScheduleMode
    created_at: datetime
    updated_at: datetime

    # ── Invariants ───────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("StreamTarget id must not be empty")
        if not self.handle:
            raise ValueError("StreamTarget handle must not be empty")
        if self.preferred_quality is not None and not self.preferred_quality.strip():
            raise ValueError("preferred_quality must not be blank if provided")

    # ── Derived state helpers ────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """Whether monitoring is currently active for this target."""
        return self.enabled

    @property
    def has_priority_bias(self) -> bool:
        """Whether this target has a priority bias from being a favourite."""
        return self.favorite and self.enabled

    @property
    def has_schedule_hints(self) -> bool:
        """Whether the user has configured schedule hints."""
        return self.schedule_mode != ScheduleMode.NONE
