"""RecordingArtifact — a file produced during a recording session.

Types: raw_ts, raw_mkv, final_mp4, log
Status: writing, ready, failed, deleted
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RecordingArtifact:
    id: str
    recording_session_id: str
    artifact_type: str  # raw_ts | raw_mkv | final_mp4 | log
    path: str
    container_format: str  # ts | mkv | mp4
    status: str  # writing | ready | failed | deleted
    size_bytes: int | None
    duration_seconds: float | None
    checksum: str | None
    created_at: datetime
    updated_at: datetime
