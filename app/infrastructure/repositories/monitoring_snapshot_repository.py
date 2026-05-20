"""Repository for MonitoringSnapshot persistence.

Maps between the domain :class:`MonitoringSnapshot` and the
``monitoring_snapshots`` SQLite table.  Because the PK is also the FK
to ``stream_targets``, the ``get`` method serves as both lookup-by-id
and ``get_by_stream_target_id``.

Each repository method creates its own short-lived SQLite connection.
Write operations are serialized via :func:`write_lock` from the connection
module.
"""

import sqlite3
from datetime import datetime

from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import Confidence, QueueBand
from app.infrastructure.db.connection import get_connection, write_lock


# ── Mapping helpers ──────────────────────────────────────────────────


def _to_row(snapshot: MonitoringSnapshot) -> dict:
    return {
        "stream_target_id": snapshot.stream_target_id,
        "state": snapshot.state.value,
        "queue_band": snapshot.queue_band.value if snapshot.queue_band else None,
        "current_likelihood": snapshot.current_likelihood,
        "current_confidence": snapshot.current_confidence.value,
        "next_check_at": snapshot.next_check_at.isoformat() if snapshot.next_check_at else None,
        "last_checked_at": snapshot.last_checked_at.isoformat() if snapshot.last_checked_at else None,
        "last_live_at": snapshot.last_live_at.isoformat() if snapshot.last_live_at else None,
        "current_recording_session_id": snapshot.current_recording_session_id,
        "last_error_code": snapshot.last_error_code,
        "last_error_message": snapshot.last_error_message,
        "updated_at": snapshot.updated_at.isoformat(),
    }


def _from_row(row: sqlite3.Row) -> MonitoringSnapshot:
    return MonitoringSnapshot(
        stream_target_id=row["stream_target_id"],
        state=MonitoringState(row["state"]),
        queue_band=QueueBand(row["queue_band"]) if row["queue_band"] else None,
        current_likelihood=row["current_likelihood"],
        current_confidence=Confidence(row["current_confidence"]),
        next_check_at=_parse_dt(row["next_check_at"]),
        last_checked_at=_parse_dt(row["last_checked_at"]),
        last_live_at=_parse_dt(row["last_live_at"]),
        current_recording_session_id=row["current_recording_session_id"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


# ── Repository ────────────────────────────────────────────────────────


_COLUMNS = (
    "stream_target_id",
    "state",
    "queue_band",
    "current_likelihood",
    "current_confidence",
    "next_check_at",
    "last_checked_at",
    "last_live_at",
    "current_recording_session_id",
    "last_error_code",
    "last_error_message",
    "updated_at",
)

_PLACEHOLDERS = ", ".join(f":{c}" for c in _COLUMNS)
_COLUMNS_CSV = ", ".join(_COLUMNS)


class MonitoringSnapshotRepository:
    """Persistence for :class:`MonitoringSnapshot` snapshots.

    Uses a *connection-per-operation* pattern — each method opens a
    fresh SQLite connection and closes it when done.  Write operations
    are serialised through a shared :data:`write_lock`.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def save(self, snapshot: MonitoringSnapshot) -> None:
        """Insert or replace a monitoring snapshot by target id."""
        row = _to_row(snapshot)
        with write_lock:
            conn = get_connection(self._db_path)
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO monitoring_snapshots ({_COLUMNS_CSV}) "
                    f"VALUES ({_PLACEHOLDERS})",
                    row,
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, stream_target_id: str) -> MonitoringSnapshot | None:
        """Return the snapshot for *stream_target_id*, or ``None``."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM monitoring_snapshots WHERE stream_target_id = ?",
                (stream_target_id,),
            ).fetchone()
            return _from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_all(self) -> list[MonitoringSnapshot]:
        """Return all monitoring snapshots."""
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM monitoring_snapshots ORDER BY stream_target_id"
            ).fetchall()
            return [_from_row(r) for r in rows]
        finally:
            conn.close()
