"""Repository for StreamTarget persistence.

Maps between the domain :class:`StreamTarget` and the ``stream_targets``
SQLite table.  Datetimes are stored as ISO-8601 text, booleans as 0/1,
and enums as their string value.

Each repository method creates its own short-lived SQLite connection.
Write operations are serialized via :func:`write_lock` from the connection
module.
"""

import sqlite3
from datetime import datetime

from app.domain.shared.types import Platform
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.db.connection import get_connection, write_lock


# ── Mapping helpers ──────────────────────────────────────────────────


def _to_row(target: StreamTarget) -> dict:
    return {
        "id": target.id,
        "platform": target.platform.value,
        "handle": target.handle,
        "source_url": target.source_url,
        "display_name": target.display_name,
        "enabled": int(target.enabled),
        "favorite": int(target.favorite),
        "preferred_quality": target.preferred_quality,
        "output_profile_id": target.output_profile_id,
        "schedule_mode": target.schedule_mode.value,
        "created_at": target.created_at.isoformat(),
        "updated_at": target.updated_at.isoformat(),
    }


def _from_row(row: sqlite3.Row) -> StreamTarget:
    return StreamTarget(
        id=row["id"],
        platform=Platform(row["platform"]),
        handle=row["handle"],
        source_url=row["source_url"],
        display_name=row["display_name"],
        enabled=bool(row["enabled"]),
        favorite=bool(row["favorite"]),
        preferred_quality=row["preferred_quality"],
        output_profile_id=row["output_profile_id"],
        schedule_mode=ScheduleMode(row["schedule_mode"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── Repository ────────────────────────────────────────────────────────


_COLUMNS = (
    "id",
    "platform",
    "handle",
    "source_url",
    "display_name",
    "enabled",
    "favorite",
    "preferred_quality",
    "output_profile_id",
    "schedule_mode",
    "created_at",
    "updated_at",
)

_PLACEHOLDERS = ", ".join(f":{c}" for c in _COLUMNS)
_COLUMNS_CSV = ", ".join(_COLUMNS)
# UPSERT SET clause — every column except the primary key.
_UPDATE_SET = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "id")


class StreamTargetRepository:
    """Persistence for :class:`StreamTarget` entities.

    Uses a *connection-per-operation* pattern — each method opens a
    fresh SQLite connection and closes it when done.  Write operations
    are serialised through a shared :data:`write_lock`.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def save(self, target: StreamTarget) -> None:
        """Insert a new stream target or update an existing one.

        Uses ``INSERT … ON CONFLICT(id) DO UPDATE SET …`` (UPSERT) instead
        of ``INSERT OR REPLACE`` so that the row is updated in-place without
        a DELETE-then-INSERT cycle.  This avoids triggering ``ON DELETE
        CASCADE`` on child tables (``monitoring_snapshots``,
        ``recording_sessions``) that reference ``stream_targets`` — rows in
        those tables are preserved across target updates.
        """
        row = _to_row(target)
        with write_lock:
            conn = get_connection(self._db_path)
            try:
                conn.execute(
                    f"INSERT INTO stream_targets ({_COLUMNS_CSV}) "
                    f"VALUES ({_PLACEHOLDERS}) "
                    f"ON CONFLICT(id) DO UPDATE SET {_UPDATE_SET}",
                    row,
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, target_id: str) -> StreamTarget | None:
        """Return a target by its id, or ``None`` if not found."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM stream_targets WHERE id = ?",
                (target_id,),
            ).fetchone()
            return _from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_all(self) -> list[StreamTarget]:
        """Return every stream target in the database."""
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM stream_targets ORDER BY display_name"
            ).fetchall()
            return [_from_row(r) for r in rows]
        finally:
            conn.close()
