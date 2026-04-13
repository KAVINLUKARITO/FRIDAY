"""SQLite persistence layer for structured lessons.

Stores :class:`Lesson` objects in a dedicated table and provides
deterministic query methods for retrieval by keyword, category, and
recency.  All SQL uses parameterised queries.

The store extends the existing :class:`Database` with a new ``lessons``
table, created lazily on first use.  It never modifies tables owned
by other subsystems.
"""

from __future__ import annotations

import json
from typing import List, Optional, Sequence

from aiworker.learning.models import Lesson, _new_lesson_id, _utcnow_iso
from aiworker.memory.database import Database

_LESSON_SCHEMA = """\
CREATE TABLE IF NOT EXISTS lessons (
    lesson_id               TEXT PRIMARY KEY,
    category                TEXT NOT NULL,
    summary                 TEXT NOT NULL,
    detail                  TEXT NOT NULL,
    confidence              REAL NOT NULL,
    source_attempt_ids      TEXT NOT NULL,
    source_goal             TEXT NOT NULL,
    applicable_goal_keywords TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    times_applied           INTEGER NOT NULL DEFAULT 0,
    times_helpful           INTEGER NOT NULL DEFAULT 0
)"""


def _lesson_from_row(row: tuple) -> Lesson:
    """Construct a :class:`Lesson` from a database row."""
    return Lesson(
        lesson_id=row[0],
        category=row[1],
        summary=row[2],
        detail=row[3],
        confidence=row[4],
        source_attempt_ids=tuple(json.loads(row[5])),
        source_goal=row[6],
        applicable_goal_keywords=tuple(json.loads(row[7])),
        created_at=row[8],
        times_applied=row[9],
        times_helpful=row[10],
    )


_SELECT_COLS = (
    "lesson_id, category, summary, detail, confidence, "
    "source_attempt_ids, source_goal, applicable_goal_keywords, "
    "created_at, times_applied, times_helpful"
)


class LearningStore:
    """Structured lesson persistence backed by SQLite.

    Args:
        database: An initialised :class:`Database` instance.
    """

    def __init__(self, database: Database) -> None:
        self.db: Database = database
        self._schema_initialised: bool = False

    def _ensure_schema(self) -> None:
        """Create the lessons table if it does not already exist."""
        if self._schema_initialised:
            return
        with self.db.connect() as conn:
            conn.execute(_LESSON_SCHEMA)
        self._schema_initialised = True

    def insert_lesson(self, lesson: Lesson) -> Lesson:
        """Persist a lesson and return it unchanged.

        Args:
            lesson: The :class:`Lesson` to store.

        Returns:
            The same lesson (for chaining convenience).
        """
        self._ensure_schema()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO lessons ("
                "  lesson_id, category, summary, detail, confidence,"
                "  source_attempt_ids, source_goal,"
                "  applicable_goal_keywords, created_at,"
                "  times_applied, times_helpful"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lesson.lesson_id,
                    lesson.category,
                    lesson.summary,
                    lesson.detail,
                    lesson.confidence,
                    json.dumps(list(lesson.source_attempt_ids)),
                    lesson.source_goal,
                    json.dumps(list(lesson.applicable_goal_keywords)),
                    lesson.created_at,
                    lesson.times_applied,
                    lesson.times_helpful,
                ),
            )
        return lesson

    def get_lesson_by_id(self, lesson_id: str) -> Optional[Lesson]:
        """Retrieve a single lesson by its ID."""
        self._ensure_schema()
        with self.db.connect() as conn:
            row = conn.execute(
                f"SELECT {_SELECT_COLS} FROM lessons WHERE lesson_id = ?",
                (lesson_id,),
            ).fetchone()
        if row is None:
            return None
        return _lesson_from_row(row)

    def get_lessons_for_keywords(
        self,
        keywords: Sequence[str],
        limit: int = 10,
    ) -> List[Lesson]:
        """Find lessons whose applicable keywords overlap with *keywords*.

        Uses a SQL ``LIKE`` search across the JSON-encoded keyword
        list.  Results are ordered by confidence descending.

        Args:
            keywords: Search terms to match against lesson keywords.
            limit: Maximum results to return.

        Returns:
            Matching lessons ordered by confidence (highest first).
        """
        self._ensure_schema()
        if not keywords:
            return []

        # Build OR conditions for each keyword.
        conditions = []
        params: list[object] = []
        for kw in keywords:
            normalised = kw.strip().lower()
            if normalised:
                conditions.append(
                    "LOWER(applicable_goal_keywords) LIKE ?"
                )
                params.append(f"%{normalised}%")

        if not conditions:
            return []

        where_clause = " OR ".join(conditions)
        params.append(limit)

        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT {_SELECT_COLS} FROM lessons "
                f"WHERE {where_clause} "
                f"ORDER BY confidence DESC LIMIT ?",
                params,
            ).fetchall()

        return [_lesson_from_row(row) for row in rows]

    def get_lessons_by_category(
        self,
        category: str,
        limit: int = 10,
    ) -> List[Lesson]:
        """Return lessons of a given category, newest first."""
        self._ensure_schema()
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT {_SELECT_COLS} FROM lessons "
                f"WHERE category = ? "
                f"ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        return [_lesson_from_row(row) for row in rows]

    def get_all_lessons(self, limit: int = 50) -> List[Lesson]:
        """Return all lessons, newest first."""
        self._ensure_schema()
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT {_SELECT_COLS} FROM lessons "
                f"ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_lesson_from_row(row) for row in rows]

    def update_lesson_applied(
        self,
        lesson_id: str,
        helpful: bool,
    ) -> Optional[Lesson]:
        """Record that a lesson was applied and whether it helped.

        Increments ``times_applied`` by 1.  If *helpful* is ``True``,
        also increments ``times_helpful`` by 1.

        Args:
            lesson_id: The lesson to update.
            helpful: Whether applying the lesson improved the outcome.

        Returns:
            The updated :class:`Lesson`, or ``None`` if not found.
        """
        self._ensure_schema()
        with self.db.connect() as conn:
            if helpful:
                conn.execute(
                    "UPDATE lessons "
                    "SET times_applied = times_applied + 1, "
                    "    times_helpful = times_helpful + 1 "
                    "WHERE lesson_id = ?",
                    (lesson_id,),
                )
            else:
                conn.execute(
                    "UPDATE lessons "
                    "SET times_applied = times_applied + 1 "
                    "WHERE lesson_id = ?",
                    (lesson_id,),
                )
        return self.get_lesson_by_id(lesson_id)

    def lesson_count(self) -> int:
        """Return the total number of stored lessons."""
        self._ensure_schema()
        with self.db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()
        return row[0] if row else 0

    def delete_lesson(self, lesson_id: str) -> bool:
        """Remove a lesson from the store.

        Returns ``True`` if the lesson existed and was deleted.
        """
        self._ensure_schema()
        with self.db.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM lessons WHERE lesson_id = ?",
                (lesson_id,),
            )
        return cursor.rowcount > 0
