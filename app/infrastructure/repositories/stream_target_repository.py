"""Repository for StreamTarget persistence.

Maps between the domain :class:`StreamTarget` and the ``stream_targets``
SQLite table.  Datetimes are stored as ISO-8601 text, booleans as 0/1,
and enums as their string value.
"""

import sqlite3
from datetime import datetime

from app.domain.shared.types import Platform
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode


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


class StreamTargetRepository:
    """Persistence for :class:`StreamTarget` entities."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def save(self, target: StreamTarget) -> None:
        """Insert or replace a stream target."""
        row = _to_row(target)
        self._conn.execute(
            f"INSERT OR REPLACE INTO stream_targets ({_COLUMNS_CSV}) "
            f"VALUES ({_PLACEHOLDERS})",
            row,
        )
        self._conn.commit()

    def get(self, target_id: str) -> StreamTarget | None:
        """Return a target by its id, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM stream_targets WHERE id = ?",
            (target_id,),
        ).fetchone()
        return _from_row(row) if row is not None else None

    def list_all(self) -> list[StreamTarget]:
        """Return every stream target in the database."""
        rows = self._conn.execute(
            "SELECT * FROM stream_targets ORDER BY display_name"
        ).fetchall()
        return [_from_row(r) for r in rows]
