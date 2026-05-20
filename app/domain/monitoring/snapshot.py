"""MonitoringSnapshot — summarised current state of a single target.

This is the primary read model exposed to the UI and used internally
for scheduling decisions.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MonitoringSnapshot:
    stream_target_id: str
    state: str  # MonitoringState value
    queue_band: str | None  # fast | medium | slow
    current_likelihood: float
    current_confidence: str  # low | medium | high
    next_check_at: datetime | None
    last_checked_at: datetime | None
    last_live_at: datetime | None
    current_recording_session_id: str | None
    last_error_code: str | None
    last_error_message: str | None
    updated_at: datetime
