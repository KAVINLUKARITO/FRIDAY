"""Immutable data models for the autonomous evolution controller.

Provides frozen dataclasses for:
- :class:`EvolutionState` — current loop iteration state.
- :class:`EvolutionConfig` — loop parameters and safety bounds.
- :class:`AttemptRecord` — snapshot of a single evolution attempt.
- :class:`EvolutionResult` — final immutable outcome of the loop.

No execution logic, no database access, no side effects.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

AttemptOutcome = Literal[
    "success",
    "policy_denied",
    "plan_failed",
    "patch_generation_failed",
    "validation_failed",
    "sandbox_failed",
    "scoring_below_threshold",
    "dry_run_skip",
    "error",
]

LoopTermination = Literal[
    "success",
    "max_attempts_reached",
    "max_failures_reached",
    "circuit_breaker_open",
    "all_attempts_exhausted",
    "error",
]


@dataclass(frozen=True)
class EvolutionConfig:
    """Configuration for a single evolution loop run.

    All parameters are validated at construction time.

    Attributes:
        goal: Human-readable description of the improvement target.
        allowed_files: Files that may be modified by generated patches.
        forbidden_files: Files that must never be touched.
        max_attempts: Upper bound on total loop iterations (budget).
        max_failures: Consecutive failures before the loop aborts.
        confidence_threshold: Minimum confidence score to accept a
            change (from the scoring subsystem).
        max_lines_changed: Per-patch line budget.
        tests_required: Whether all tests must pass for approval.
        risk_level: Risk classification for the change.
        dry_run: When ``True``, the loop runs through all checks but
            skips sandbox execution and patch application.
        sandbox_timeout: Maximum seconds for each sandbox run.
        seed: Optional deterministic seed passed to the patch
            generator for replay capability.
    """

    goal: str
    allowed_files: tuple[str, ...]
    forbidden_files: tuple[str, ...] = ()
    max_attempts: int = 5
    max_failures: int = 3
    confidence_threshold: float = 0.4
    max_lines_changed: int = 50
    tests_required: bool = True
    risk_level: Literal["low", "medium", "high"] = "low"
    dry_run: bool = False
    sandbox_timeout: int = 60
    seed: Optional[int] = None

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.goal or not self.goal.strip():
            errors.append("goal must be a non-empty string")
        if not self.allowed_files:
            errors.append("allowed_files must not be empty")
        if self.max_attempts < 1:
            errors.append(
                f"max_attempts must be >= 1, got {self.max_attempts}"
            )
        if self.max_failures < 1:
            errors.append(
                f"max_failures must be >= 1, got {self.max_failures}"
            )
        if not (0.0 <= self.confidence_threshold <= 1.0):
            errors.append(
                f"confidence_threshold must be in [0, 1], "
                f"got {self.confidence_threshold}"
            )
        if self.max_lines_changed < 1:
            errors.append(
                f"max_lines_changed must be >= 1, got {self.max_lines_changed}"
            )
        if self.sandbox_timeout < 1:
            errors.append(
                f"sandbox_timeout must be >= 1, got {self.sandbox_timeout}"
            )
        if errors:
            raise ValueError(
                "Invalid EvolutionConfig: " + "; ".join(errors)
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "goal": self.goal,
            "allowed_files": list(self.allowed_files),
            "forbidden_files": list(self.forbidden_files),
            "max_attempts": self.max_attempts,
            "max_failures": self.max_failures,
            "confidence_threshold": self.confidence_threshold,
            "max_lines_changed": self.max_lines_changed,
            "tests_required": self.tests_required,
            "risk_level": self.risk_level,
            "dry_run": self.dry_run,
            "sandbox_timeout": self.sandbox_timeout,
            "seed": self.seed,
        }


@dataclass(frozen=True)
class EvolutionState:
    """Snapshot of the evolution loop's current iteration state.

    Used to track progress through the loop without mutable fields.

    Attributes:
        goal: The evolution goal being pursued.
        iteration: Current 1-based iteration index.
        max_iterations: Total iteration budget.
        active: ``True`` while the loop is still running.
    """

    goal: str
    iteration: int
    max_iterations: int
    active: bool

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.goal or not self.goal.strip():
            errors.append("goal must be a non-empty string")
        if self.iteration < 0:
            errors.append(
                f"iteration must be >= 0, got {self.iteration}"
            )
        if self.max_iterations < 1:
            errors.append(
                f"max_iterations must be >= 1, got {self.max_iterations}"
            )
        if self.iteration > self.max_iterations:
            errors.append(
                f"iteration ({self.iteration}) cannot exceed "
                f"max_iterations ({self.max_iterations})"
            )
        if errors:
            raise ValueError(
                "Invalid EvolutionState: " + "; ".join(errors)
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "goal": self.goal,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "active": self.active,
        }


@dataclass(frozen=True)
class AttemptRecord:
    """Immutable snapshot of a single evolution attempt.

    Captures the full context of one loop iteration for deterministic
    replay and audit analysis.

    Attributes:
        attempt_number: 1-based iteration index.
        attempt_id: Unique UUID for correlation.
        timestamp: UTC ISO-8601 creation time.
        outcome: Classification of what happened.
        policy_allowed: Whether the governance gate passed.
        plan_generated: Whether a plan was successfully generated.
        patch_generated: Whether a patch was generated from the plan.
        validation_passed: Whether the patch passed validation.
        sandbox_success: Whether sandbox execution succeeded.
        confidence_score: Score from the scoring subsystem.
        patch_text: The patch that was attempted (if any).
        detail: Human-readable explanation.
        error: Exception message if an error occurred.
    """

    attempt_number: int
    attempt_id: str
    timestamp: str
    outcome: AttemptOutcome
    policy_allowed: bool = False
    plan_generated: bool = False
    patch_generated: bool = False
    validation_passed: bool = False
    sandbox_success: bool = False
    confidence_score: float = 0.0
    patch_text: Optional[str] = None
    detail: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "attempt_number": self.attempt_number,
            "attempt_id": self.attempt_id,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "policy_allowed": self.policy_allowed,
            "plan_generated": self.plan_generated,
            "patch_generated": self.patch_generated,
            "validation_passed": self.validation_passed,
            "sandbox_success": self.sandbox_success,
            "confidence_score": self.confidence_score,
            "detail": self.detail,
            "error": self.error,
        }


def _new_attempt_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EvolutionResult:
    """Immutable outcome of a complete evolution loop run.

    Attributes:
        config: The configuration that was used.
        success: Whether the loop achieved its goal.
        termination_reason: Why the loop stopped.
        total_attempts: How many iterations were executed.
        successful_attempts: How many iterations succeeded.
        failed_attempts: How many iterations failed.
        attempts: Ordered sequence of all attempt records.
        final_confidence: Confidence score from the last attempt.
        detail: Human-readable summary.
    """

    config: EvolutionConfig
    success: bool
    termination_reason: LoopTermination
    total_attempts: int
    successful_attempts: int
    failed_attempts: int
    attempts: tuple[AttemptRecord, ...] = ()
    final_confidence: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "config": self.config.to_dict(),
            "success": self.success,
            "termination_reason": self.termination_reason,
            "total_attempts": self.total_attempts,
            "successful_attempts": self.successful_attempts,
            "failed_attempts": self.failed_attempts,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_confidence": self.final_confidence,
            "detail": self.detail,
        }
