"""Schema migrations for the core SQLite database.

Run on startup to ensure tables exist.  Uses ``CREATE TABLE IF NOT EXISTS``
so it is safe to run multiple times — there is no version tracking yet.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stream_targets (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    source_url TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    favorite INTEGER NOT NULL DEFAULT 0,
    preferred_quality TEXT,
    output_profile_id TEXT,
    schedule_mode TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitoring_snapshots (
    stream_target_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    queue_band TEXT,
    current_likelihood REAL NOT NULL,
    current_confidence TEXT NOT NULL,
    next_check_at TEXT,
    last_checked_at TEXT,
    last_live_at TEXT,
    current_recording_session_id TEXT,
    last_error_code TEXT,
    last_error_message TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (stream_target_id) REFERENCES stream_targets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recording_sessions (
    id TEXT PRIMARY KEY,
    stream_target_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    stream_title TEXT,
    detected_by_queue TEXT,
    detection_latency_seconds REAL,
    scheduled_hint_delay_minutes INTEGER,
    split_reason TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (stream_target_id) REFERENCES stream_targets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recording_artifacts (
    id TEXT PRIMARY KEY,
    recording_session_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    container_format TEXT NOT NULL,
    status TEXT NOT NULL,
    size_bytes INTEGER,
    duration_seconds REAL,
    checksum TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (recording_session_id) REFERENCES recording_sessions(id) ON DELETE CASCADE
);
"""


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply pending schema migrations.

    Idempotent — safe to call on every startup.
    """
    connection.executescript(SCHEMA_SQL)

    _migrate_add_column(
        connection,
        table="monitoring_snapshots",
        column="resolved_stream_url",
        definition="TEXT",
    )

    connection.commit()


def _migrate_add_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Add a column to an existing table if it does not already exist.

    SQLite does not support ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``,
    so we catch :class:`sqlite3.OperationalError` when the column is
    already present.
    """
    try:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
        logger.info("Migration: added column %s to %s", column, table)
    except sqlite3.OperationalError as exc:
        if "duplicate column" in str(exc).lower():
            logger.debug("Column %s already exists on %s (skipped)", column, table)
        else:
            raise
