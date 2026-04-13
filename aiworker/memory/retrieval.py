"""High-level retrieval functions for the experience memory system.

Provides convenience functions that query the database for similar
past change attempts.  All SQL is parameterised — no string
concatenation is applied to user-supplied values.
"""

from __future__ import annotations

from typing import List

from aiworker.memory.database import Database
from aiworker.memory.models import ChangeAttemptRecord


def find_similar_attempts(
    database: Database,
    goal: str,
    limit: int = 5,
) -> List[ChangeAttemptRecord]:
    """Find past change attempts with goals similar to *goal*.

    Uses a SQL ``LIKE`` pattern match (case-insensitive on most SQLite
    builds) with parameterised binding to prevent injection.

    Args:
        database: An initialised :class:`Database` instance.
        goal: The goal text to search for (substring match).
        limit: Maximum number of results to return.

    Returns:
        A list of :class:`ChangeAttemptRecord` ordered by most recent
        first, up to *limit* entries.
    """
    if not goal or not goal.strip():
        return []

    pattern = f"%{goal}%"
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT id, goal, risk_level, allowed_files, timestamp "
            "FROM change_attempts "
            "WHERE goal LIKE ? "
            "ORDER BY timestamp DESC "
            "LIMIT ?",
            (pattern, limit),
        ).fetchall()

    return [ChangeAttemptRecord(*row) for row in rows]
