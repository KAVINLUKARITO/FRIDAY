"""Data models for the persistent experience memory system.

Each model corresponds to a database table and provides strict
type-hinted dataclasses for structured data transfer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass(frozen=True)
class ChangeAttemptRecord:
    """Represents a single change attempt stored in the database.

    Attributes:
        id: Unique identifier (UUID string).
        goal: Human-readable description of the intended change.
        risk_level: One of ``"low"``, ``"medium"``, ``"high"``.
        allowed_files: JSON-encoded list of allowed file paths.
        timestamp: When the attempt was recorded.
    """

    id: str
    goal: str
    risk_level: str
    allowed_files: str  # JSON-encoded list
    timestamp: str

    def get_allowed_files_list(self) -> List[str]:
        """Deserialise the ``allowed_files`` JSON string to a list."""
        result = json.loads(self.allowed_files)
        if not isinstance(result, list):
            return []
        return [str(item) for item in result]


@dataclass(frozen=True)
class ValidationResultRecord:
    """Persisted validation outcome for a change attempt.

    Attributes:
        id: Unique identifier (UUID string).
        attempt_id: Foreign key to :class:`ChangeAttemptRecord`.
        validation_passed: Whether the patch passed validation.
        reason: Human-readable explanation.
    """

    id: str
    attempt_id: str
    validation_passed: bool
    reason: str


@dataclass(frozen=True)
class SandboxResultRecord:
    """Persisted sandbox execution outcome.

    Attributes:
        id: Unique identifier (UUID string).
        attempt_id: Foreign key to :class:`ChangeAttemptRecord`.
        success: Whether the sandbox run succeeded.
        tests_passed: Number of tests that passed.
        tests_failed: Number of tests that failed.
        execution_time: Wall-clock duration in seconds.
    """

    id: str
    attempt_id: str
    success: bool
    tests_passed: int
    tests_failed: int
    execution_time: float


@dataclass(frozen=True)
class ApprovalResultRecord:
    """Persisted approval gate outcome.

    Attributes:
        id: Unique identifier (UUID string).
        attempt_id: Foreign key to :class:`ChangeAttemptRecord`.
        approved: Whether the patch was approved.
        approval_required: Whether approval was required.
        final_reason: Human-readable reason for the decision.
    """

    id: str
    attempt_id: str
    approved: bool
    approval_required: bool
    final_reason: str
