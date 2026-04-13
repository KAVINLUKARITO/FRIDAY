"""SQLite database initialisation and connection management.

Provides a :class:`Database` class that manages the SQLite database
lifecycle: creating tables, enforcing foreign keys, and providing
connection context managers for transactional access.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator

_SCHEMA_STATEMENTS: list[str] = [
    """\
    CREATE TABLE IF NOT EXISTS change_attempts (
        id          TEXT PRIMARY KEY,
        goal        TEXT NOT NULL,
        risk_level  TEXT NOT NULL,
        allowed_files TEXT NOT NULL,
        timestamp   DATETIME NOT NULL
    )""",
    """\
    CREATE TABLE IF NOT EXISTS validation_results (
        id                TEXT PRIMARY KEY,
        attempt_id        TEXT NOT NULL,
        validation_passed BOOLEAN NOT NULL,
        reason            TEXT NOT NULL,
        FOREIGN KEY (attempt_id) REFERENCES change_attempts(id)
    )""",
    """\
    CREATE TABLE IF NOT EXISTS sandbox_results (
        id              TEXT PRIMARY KEY,
        attempt_id      TEXT NOT NULL,
        success         BOOLEAN NOT NULL,
        tests_passed    INTEGER NOT NULL,
        tests_failed    INTEGER NOT NULL,
        execution_time  REAL NOT NULL,
        FOREIGN KEY (attempt_id) REFERENCES change_attempts(id)
    )""",
    """\
    CREATE TABLE IF NOT EXISTS approval_results (
        id                TEXT PRIMARY KEY,
        attempt_id        TEXT NOT NULL,
        approved          BOOLEAN NOT NULL,
        approval_required BOOLEAN NOT NULL,
        final_reason      TEXT NOT NULL,
        FOREIGN KEY (attempt_id) REFERENCES change_attempts(id)
    )""",
]


class Database:
    """Manages a SQLite database for the experience memory system.

    Args:
        db_path: Path to the SQLite database file.  Use ``":memory:"``
            for an in-memory database (useful for testing).

    For file-backed databases each :meth:`connect` call opens a fresh
    connection and closes it when the context exits.  For in-memory
    databases a single persistent connection is reused so that the
    schema and data survive across calls.
    """

    def __init__(self, db_path: str = "aiworker.db") -> None:
        self.db_path: str = db_path
        self._memory_conn: sqlite3.Connection | None = None

    def initialise(self) -> None:
        """Create tables if they do not already exist.

        Uses individual ``execute`` calls (not ``executescript``) so
        that the statements run inside the connection's transaction.
        """
        with self.connect() as conn:
            for stmt in _SCHEMA_STATEMENTS:
                conn.execute(stmt)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a connection with foreign keys enabled and auto-commit
        on successful exit (via context manager).

        For file-backed databases the connection is closed when the
        context exits.  For in-memory databases a single connection is
        kept alive for the lifetime of the :class:`Database` instance.
        Rolls back on exception.
        """
        if self.db_path == ":memory:":
            conn = self._get_memory_conn()
        else:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            # Only close file-backed connections; keep memory alive.
            if self.db_path != ":memory:":
                conn.close()

    def _get_memory_conn(self) -> sqlite3.Connection:
        """Return (or create) the persistent in-memory connection."""
        if self._memory_conn is None:
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.execute("PRAGMA foreign_keys = ON")
        return self._memory_conn
