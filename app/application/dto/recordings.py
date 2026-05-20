"""Data transfer objects for recording session operations."""

from dataclasses import dataclass


@dataclass
class RecordingSessionDTO:
    """A recording session ready for API/UI presentation.

    Fields are serialized to plain types (str, float, bool | None) so the
    DTO can be passed directly to ``json.dumps()`` via ``dataclasses.asdict()``.
    """

    id: str
    stream_target_id: str
    started_at: str
    ended_at: str | None
    status: str
    source_platform: str
    stream_title: str | None
    duration_seconds: float | None
    detected_by_queue: str | None
    error_code: str | None
    error_message: str | None
    split_reason: str | None
    created_at: str
    updated_at: str
