"""Schema migrations for the core SQLite database.

Run on startup to ensure tables exist.
"""


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
"""


def apply_migrations(connection) -> None:
    """Apply pending schema migrations."""
    connection.executescript(SCHEMA_SQL)
    connection.commit()
