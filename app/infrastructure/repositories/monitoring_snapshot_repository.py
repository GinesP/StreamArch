"""Repository for MonitoringSnapshot persistence.

Maps between the domain :class:`MonitoringSnapshot` and the
``monitoring_snapshots`` SQLite table.  Because the PK is also the FK
to ``stream_targets``, the ``get`` method serves as both lookup-by-id
and ``get_by_stream_target_id``.
"""

import sqlite3
from datetime import datetime

from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import Confidence, QueueBand


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
    """Persistence for :class:`MonitoringSnapshot` snapshots."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def save(self, snapshot: MonitoringSnapshot) -> None:
        """Insert or replace a monitoring snapshot by target id."""
        row = _to_row(snapshot)
        self._conn.execute(
            f"INSERT OR REPLACE INTO monitoring_snapshots ({_COLUMNS_CSV}) "
            f"VALUES ({_PLACEHOLDERS})",
            row,
        )
        self._conn.commit()

    def get(self, stream_target_id: str) -> MonitoringSnapshot | None:
        """Return the snapshot for *stream_target_id*, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM monitoring_snapshots WHERE stream_target_id = ?",
            (stream_target_id,),
        ).fetchone()
        return _from_row(row) if row is not None else None

    def list_all(self) -> list[MonitoringSnapshot]:
        """Return all monitoring snapshots."""
        rows = self._conn.execute(
            "SELECT * FROM monitoring_snapshots ORDER BY stream_target_id"
        ).fetchall()
        return [_from_row(r) for r in rows]
