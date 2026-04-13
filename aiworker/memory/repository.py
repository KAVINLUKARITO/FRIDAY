"""Data access layer for the experience memory system.

All SQL uses parameterised queries — no string concatenation or
interpolation is ever applied to user-supplied values.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from aiworker.memory.database import Database
from aiworker.memory.models import (
    ApprovalResultRecord,
    ChangeAttemptRecord,
    SandboxResultRecord,
    ValidationResultRecord,
)


def _new_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class MemoryRepository:
    """CRUD operations for the experience memory database.

    Args:
        database: A :class:`Database` instance (already initialised).
    """

    def __init__(self, database: Database) -> None:
        self.db: Database = database

    # ------------------------------------------------------------------
    # Inserts
    # ------------------------------------------------------------------

    def insert_change_attempt(
        self,
        goal: str,
        risk_level: str,
        allowed_files: List[str],
    ) -> ChangeAttemptRecord:
        """Insert a new change attempt and return the persisted record."""
        record = ChangeAttemptRecord(
            id=_new_id(),
            goal=goal,
            risk_level=risk_level,
            allowed_files=json.dumps(allowed_files),
            timestamp=_utcnow_iso(),
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO change_attempts (id, goal, risk_level, allowed_files, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (record.id, record.goal, record.risk_level, record.allowed_files, record.timestamp),
            )
        return record

    def insert_validation_result(
        self,
        attempt_id: str,
        validation_passed: bool,
        reason: str,
    ) -> ValidationResultRecord:
        """Insert a validation result linked to an attempt."""
        record = ValidationResultRecord(
            id=_new_id(),
            attempt_id=attempt_id,
            validation_passed=validation_passed,
            reason=reason,
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO validation_results (id, attempt_id, validation_passed, reason) "
                "VALUES (?, ?, ?, ?)",
                (record.id, record.attempt_id, record.validation_passed, record.reason),
            )
        return record

    def insert_sandbox_result(
        self,
        attempt_id: str,
        success: bool,
        tests_passed: int,
        tests_failed: int,
        execution_time: float,
    ) -> SandboxResultRecord:
        """Insert a sandbox execution result linked to an attempt."""
        record = SandboxResultRecord(
            id=_new_id(),
            attempt_id=attempt_id,
            success=success,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            execution_time=execution_time,
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO sandbox_results "
                "(id, attempt_id, success, tests_passed, tests_failed, execution_time) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.attempt_id,
                    record.success,
                    record.tests_passed,
                    record.tests_failed,
                    record.execution_time,
                ),
            )
        return record

    def insert_approval_result(
        self,
        attempt_id: str,
        approved: bool,
        approval_required: bool,
        final_reason: str,
    ) -> ApprovalResultRecord:
        """Insert an approval gate result linked to an attempt."""
        record = ApprovalResultRecord(
            id=_new_id(),
            attempt_id=attempt_id,
            approved=approved,
            approval_required=approval_required,
            final_reason=final_reason,
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO approval_results "
                "(id, attempt_id, approved, approval_required, final_reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.attempt_id,
                    record.approved,
                    record.approval_required,
                    record.final_reason,
                ),
            )
        return record

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_attempt_by_id(self, attempt_id: str) -> Optional[ChangeAttemptRecord]:
        """Retrieve a single change attempt by its ID."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, goal, risk_level, allowed_files, timestamp "
                "FROM change_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            return None
        return ChangeAttemptRecord(*row)

    def get_last_n_attempts(self, n: int) -> List[ChangeAttemptRecord]:
        """Retrieve the most recent *n* change attempts (newest first)."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, goal, risk_level, allowed_files, timestamp "
                "FROM change_attempts ORDER BY timestamp DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [ChangeAttemptRecord(*row) for row in rows]

    def get_attempts_by_goal(
        self, goal_fragment: str, limit: int = 10
    ) -> List[ChangeAttemptRecord]:
        """Retrieve attempts whose goal contains *goal_fragment*.

        Uses a parameterised ``LIKE`` query — safe against SQL injection.
        """
        pattern = f"%{goal_fragment}%"
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, goal, risk_level, allowed_files, timestamp "
                "FROM change_attempts WHERE goal LIKE ? ORDER BY timestamp DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        return [ChangeAttemptRecord(*row) for row in rows]

    def get_validation_for_attempt(
        self, attempt_id: str
    ) -> Optional[ValidationResultRecord]:
        """Retrieve the validation result for a given attempt."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, attempt_id, validation_passed, reason "
                "FROM validation_results WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            return None
        return ValidationResultRecord(
            id=row[0],
            attempt_id=row[1],
            validation_passed=bool(row[2]),
            reason=row[3],
        )

    def get_sandbox_for_attempt(
        self, attempt_id: str
    ) -> Optional[SandboxResultRecord]:
        """Retrieve the sandbox result for a given attempt."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, attempt_id, success, tests_passed, tests_failed, execution_time "
                "FROM sandbox_results WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            return None
        return SandboxResultRecord(
            id=row[0],
            attempt_id=row[1],
            success=bool(row[2]),
            tests_passed=row[3],
            tests_failed=row[4],
            execution_time=row[5],
        )

    def get_approval_for_attempt(
        self, attempt_id: str
    ) -> Optional[ApprovalResultRecord]:
        """Retrieve the approval result for a given attempt."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, attempt_id, approved, approval_required, final_reason "
                "FROM approval_results WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            return None
        return ApprovalResultRecord(
            id=row[0],
            attempt_id=row[1],
            approved=bool(row[2]),
            approval_required=bool(row[3]),
            final_reason=row[4],
        )
