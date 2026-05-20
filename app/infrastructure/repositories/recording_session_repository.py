"""Repository for RecordingSession persistence.

Maps between the domain :class:`RecordingSession` and the
``recording_sessions`` SQLite table.
"""

import sqlite3
from datetime import datetime

from app.domain.recording.session import RecordingSession
from app.domain.shared.types import Platform, QueueBand, RecordingStatus


# ── Mapping helpers ──────────────────────────────────────────────────


def _to_row(session: RecordingSession) -> dict:
    return {
        "id": session.id,
        "stream_target_id": session.stream_target_id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "status": session.status.value,
        "source_platform": session.source_platform.value,
        "stream_title": session.stream_title,
        "detected_by_queue": session.detected_by_queue.value if session.detected_by_queue else None,
        "detection_latency_seconds": session.detection_latency_seconds,
        "scheduled_hint_delay_minutes": session.scheduled_hint_delay_minutes,
        "split_reason": session.split_reason,
        "error_code": session.error_code,
        "error_message": session.error_message,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _from_row(row: sqlite3.Row) -> RecordingSession:
    return RecordingSession(
        id=row["id"],
        stream_target_id=row["stream_target_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=_parse_dt(row["ended_at"]),
        status=RecordingStatus(row["status"]),
        source_platform=Platform(row["source_platform"]),
        stream_title=row["stream_title"],
        detected_by_queue=QueueBand(row["detected_by_queue"]) if row["detected_by_queue"] else None,
        detection_latency_seconds=row["detection_latency_seconds"],
        scheduled_hint_delay_minutes=row["scheduled_hint_delay_minutes"],
        split_reason=row["split_reason"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


# ── Repository ────────────────────────────────────────────────────────


_COLUMNS = (
    "id",
    "stream_target_id",
    "started_at",
    "ended_at",
    "status",
    "source_platform",
    "stream_title",
    "detected_by_queue",
    "detection_latency_seconds",
    "scheduled_hint_delay_minutes",
    "split_reason",
    "error_code",
    "error_message",
    "created_at",
    "updated_at",
)

_PLACEHOLDERS = ", ".join(f":{c}" for c in _COLUMNS)
_COLUMNS_CSV = ", ".join(_COLUMNS)


class RecordingSessionRepository:
    """Persistence for :class:`RecordingSession` entities."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def save(self, session: RecordingSession) -> None:
        """Insert or replace a recording session."""
        row = _to_row(session)
        self._conn.execute(
            f"INSERT OR REPLACE INTO recording_sessions ({_COLUMNS_CSV}) "
            f"VALUES ({_PLACEHOLDERS})",
            row,
        )
        self._conn.commit()

    def get(self, session_id: str) -> RecordingSession | None:
        """Return a session by its id, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM recording_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return _from_row(row) if row is not None else None

    def list_by_target(self, stream_target_id: str) -> list[RecordingSession]:
        """Return all sessions for a given target, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM recording_sessions WHERE stream_target_id = ? "
            "ORDER BY started_at DESC",
            (stream_target_id,),
        ).fetchall()
        return [_from_row(r) for r in rows]
