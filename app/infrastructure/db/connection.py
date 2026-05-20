"""SQLite connection management with WAL mode support.

Ensures the parent data directory exists before opening the database
and configures sensible PRAGMAs for concurrent read-heavy workloads.
"""

import sqlite3
from pathlib import Path


def create_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with recommended PRAGMAs.

    * Creates the parent directory if it does not exist.
    * Enables WAL journal mode for concurrent reads.
    * Enforces foreign key constraints.
    * Sets a busy timeout so concurrent writes wait instead of failing.

    Returns a connection whose rows are returned as :class:`sqlite3.Row`
    (dict-like access by column name).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")       # 64 MB
    conn.execute("PRAGMA busy_timeout=5000")        # 5 s
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    return conn
