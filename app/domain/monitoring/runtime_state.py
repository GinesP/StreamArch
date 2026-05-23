"""Minimal in-memory runtime state for one monitored stream target."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MonitoringRuntimeState:
    """Operational scheduler state kept in memory by ``MonitoringCycle``."""

    stream_target_id: str
    next_check_at: datetime | None
    last_checked_at: datetime | None
    last_live_at: datetime | None
    is_live: bool
    active_recording_session_id: str | None
    previous_likelihood: float
    updated_at: datetime
    last_checked_count: int = 0
    """Number of live checks performed since the target was added."""
