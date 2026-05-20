"""SQLite connection factory — connection-per-operation style.

Each call to ``get_connection`` returns a *fresh* :class:`sqlite3.Connection`
with WAL mode and sensible PRAGMAs.  Connections are short-lived and do
**not** use ``check_same_thread=False`` — each operation creates its own
connection on the calling thread.

Usage::

    from app.infrastructure.db.connection import get_connection, write_lock

    # Read — no lock needed (WAL handles concurrent readers).
    conn = get_connection("/path/to/db")
    try:
        rows = conn.execute("SELECT * FROM t").fetchall()
    finally:
        conn.close()

    # Write — serialized via write_lock.
    with write_lock:
        conn = get_connection("/path/to/db")
        try:
            conn.execute("INSERT INTO t VALUES (?)", (val,))
            conn.commit()
        finally:
            conn.close()

The ``write_lock`` is a :class:`threading.Lock` used as a context manager.
It serialises all write operations so that only one thread modifies the
database at a time.  Reads do not need the lock because WAL-mode SQLite
handles concurrent readers safely.

This module deliberately avoids any connection pooling, long-lived
connections, or ``check_same_thread=False``.

Compared to the old shared-connection approach:

    * Old: one shared ``sqlite3.Connection`` with ``check_same_thread=False``
      created at startup and reused for every operation.
    * New: one fresh ``sqlite3.Connection`` per call, default
      ``check_same_thread=True``, with explicit ``write_lock`` for writes.
"""

import sqlite3
import threading
from pathlib import Path

_db_write_lock = threading.Lock()


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Return a fresh SQLite connection with recommended PRAGMAs.

    * Creates the parent directory if it does not exist.
    * Enables WAL journal mode for concurrent reads.
    * Enforces foreign key constraints.
    * Sets a busy timeout so concurrent writes wait instead of failing.

    Returns a connection whose rows are returned as :class:`sqlite3.Row`
    (dict-like access by column name).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")       # 64 MB
    conn.execute("PRAGMA busy_timeout=5000")        # 5 s
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    return conn


write_lock = _db_write_lock
"""A :class:`threading.Lock` that serialises database write operations.

Use as a context manager around every repository call that modifies data::

    with write_lock:
        repo.save(some_entity)

Read-only operations do not need the lock.
"""
