"""Repository for RecordingArtifact persistence.

Maps between the domain :class:`RecordingArtifact` and the
``recording_artifacts`` SQLite table.

Each repository method creates its own short-lived SQLite connection.
Write operations are serialized via :func:`write_lock` from the connection
module.
"""

import sqlite3
from datetime import datetime

from app.domain.recording.artifacts import RecordingArtifact
from app.domain.shared.types import ArtifactStatus, ArtifactType, ContainerFormat
from app.infrastructure.db.connection import get_connection, write_lock


# ── Mapping helpers ──────────────────────────────────────────────────


def _to_row(artifact: RecordingArtifact) -> dict:
    return {
        "id": artifact.id,
        "recording_session_id": artifact.recording_session_id,
        "artifact_type": artifact.artifact_type.value,
        "path": artifact.path,
        "container_format": artifact.container_format.value,
        "status": artifact.status.value,
        "size_bytes": artifact.size_bytes,
        "duration_seconds": artifact.duration_seconds,
        "checksum": artifact.checksum,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
    }


def _from_row(row: sqlite3.Row) -> RecordingArtifact:
    return RecordingArtifact(
        id=row["id"],
        recording_session_id=row["recording_session_id"],
        artifact_type=ArtifactType(row["artifact_type"]),
        path=row["path"],
        container_format=ContainerFormat(row["container_format"]),
        status=ArtifactStatus(row["status"]),
        size_bytes=row["size_bytes"],
        duration_seconds=row["duration_seconds"],
        checksum=row["checksum"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── Repository ────────────────────────────────────────────────────────


_COLUMNS = (
    "id",
    "recording_session_id",
    "artifact_type",
    "path",
    "container_format",
    "status",
    "size_bytes",
    "duration_seconds",
    "checksum",
    "created_at",
    "updated_at",
)

_PLACEHOLDERS = ", ".join(f":{c}" for c in _COLUMNS)
_COLUMNS_CSV = ", ".join(_COLUMNS)
_UPDATE_SET = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "id")


class RecordingArtifactRepository:
    """Persistence for :class:`RecordingArtifact` entities.

    Uses a *connection-per-operation* pattern — each method opens a
    fresh SQLite connection and closes it when done.  Write operations
    are serialised through a shared :data:`write_lock`.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def save(self, artifact: RecordingArtifact) -> None:
        """Insert a new artifact or update an existing one.

        Uses ``INSERT … ON CONFLICT(id) DO UPDATE SET …`` (UPSERT).
        """
        row = _to_row(artifact)
        with write_lock:
            conn = get_connection(self._db_path)
            try:
                conn.execute(
                    f"INSERT INTO recording_artifacts ({_COLUMNS_CSV}) "
                    f"VALUES ({_PLACEHOLDERS}) "
                    f"ON CONFLICT(id) DO UPDATE SET {_UPDATE_SET}",
                    row,
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, artifact_id: str) -> RecordingArtifact | None:
        """Return an artifact by its id, or ``None``."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM recording_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            return _from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_by_session(self, session_id: str) -> list[RecordingArtifact]:
        """Return all artifacts for a given recording session."""
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM recording_artifacts "
                "WHERE recording_session_id = ? "
                "ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            return [_from_row(r) for r in rows]
        finally:
            conn.close()
