"""Domain event types emitted by the core during operation.

Each event carries a timestamp, target id, and relevant payload.
Consumed by EventBus for WebSocket broadcast and internal hooks.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.shared.types import utc_now


@dataclass
class StreamChecked:
    stream_target_id: str
    was_live: bool
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class LiveDetected:
    stream_target_id: str
    recording_session_id: str
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class RecordingStarted:
    stream_target_id: str
    recording_session_id: str
    artifact_path: str
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class RecordingProgress:
    recording_session_id: str
    duration_seconds: float
    size_bytes: int
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class RecordingFinished:
    recording_session_id: str
    status: str
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class DiskFullDetected:
    path: str
    free_bytes: int
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class ShutdownStarted:
    reason: str
    timestamp: datetime = field(default_factory=utc_now)
