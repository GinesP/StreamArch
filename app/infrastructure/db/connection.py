"""SQLite connection management with WAL mode support."""

import sqlite3
from pathlib import Path


def create_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with recommended PRAGMAs.

    Returns a connection configured for WAL mode and concurrent reads.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn
