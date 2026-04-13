"""Structured change request definition and validation.

A :class:`ChangeRequest` describes the constraints for a controlled
self-modification operation: which files may be touched, which are
forbidden, line-change budget, risk level, and whether tests are
required to pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal

VALID_RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})
MAX_ALLOWED_LINES_CHANGED: int = 200


@dataclass(frozen=True)
class ChangeRequest:
    """Immutable description of a controlled self-modification request.

    Attributes:
        goal: Human-readable description of the intended change.
        allowed_files: Non-empty list of relative file paths that may
            be modified by the patch.
        forbidden_files: List of relative file paths that must NOT be
            touched by the patch.
        max_lines_changed: Upper bound on the total number of added +
            removed lines.  Must be between 1 and 200 inclusive.
        tests_required: Whether passing tests are required for approval.
        risk_level: One of ``"low"``, ``"medium"``, or ``"high"``.
    """

    goal: str
    allowed_files: List[str]
    forbidden_files: List[str] = field(default_factory=list)
    max_lines_changed: int = 50
    tests_required: bool = True
    risk_level: Literal["low", "medium", "high"] = "low"

    def __post_init__(self) -> None:
        """Validate all fields immediately after construction."""
        errors: list[str] = []

        if not self.goal or not self.goal.strip():
            errors.append("goal must be a non-empty string")

        if not self.allowed_files:
            errors.append("allowed_files must not be empty")

        if self.max_lines_changed < 1:
            errors.append(
                f"max_lines_changed must be >= 1, got {self.max_lines_changed}"
            )
        if self.max_lines_changed > MAX_ALLOWED_LINES_CHANGED:
            errors.append(
                f"max_lines_changed must be <= {MAX_ALLOWED_LINES_CHANGED}, "
                f"got {self.max_lines_changed}"
            )

        if self.risk_level not in VALID_RISK_LEVELS:
            errors.append(
                f"risk_level must be one of {sorted(VALID_RISK_LEVELS)}, "
                f"got {self.risk_level!r}"
            )

        overlap = set(self.allowed_files) & set(self.forbidden_files)
        if overlap:
            errors.append(
                f"Files cannot be both allowed and forbidden: {sorted(overlap)}"
            )

        if errors:
            raise ValueError(
                "Invalid ChangeRequest: " + "; ".join(errors)
            )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dictionary representation."""
        return {
            "goal": self.goal,
            "allowed_files": list(self.allowed_files),
            "forbidden_files": list(self.forbidden_files),
            "max_lines_changed": self.max_lines_changed,
            "tests_required": self.tests_required,
            "risk_level": self.risk_level,
        }
