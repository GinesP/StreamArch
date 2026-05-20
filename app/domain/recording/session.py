"""RecordingSession — lifecycle of a detected live stream.

Status lifecycle:
    recording -> completed | failed | aborted | split
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RecordingSession:
    id: str
    stream_target_id: str
    started_at: datetime
    ended_at: datetime | None
    status: str  # recording | completed | failed | aborted | split
    source_platform: str
    stream_title: str | None
    detected_by_queue: str | None  # fast | medium | slow
    detection_latency_seconds: float | None
    scheduled_hint_delay_minutes: int | None
    split_reason: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
