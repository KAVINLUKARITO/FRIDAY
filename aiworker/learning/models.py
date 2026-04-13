"""Immutable data models for the structured learning memory system.

Provides frozen dataclasses for:
- :class:`Lesson` — a single insight extracted from past attempts.
- :class:`GoalPattern` — aggregate statistics for a goal category.
- :class:`LearningContext` — enriched context for a new attempt.

No execution logic, no database access, no side effects.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

LessonCategory = Literal[
    "failure_mode",
    "success_pattern",
    "goal_strategy",
    "patch_heuristic",
]


def _new_lesson_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Lesson:
    """A single structured insight extracted from past evolution attempts.

    Lessons are the atomic unit of learning.  Each captures a specific
    observation about what worked, what failed, or how to approach a
    goal type.

    Attributes:
        lesson_id: Unique identifier (UUID4).
        category: Classification of the lesson type.
        summary: Short one-line description of the insight.
        detail: Longer explanation with actionable context.
        confidence: How reliable this lesson is ``[0, 1]``.
        source_attempt_ids: Attempt IDs that contributed to this lesson.
        source_goal: The original goal that produced this lesson.
        applicable_goal_keywords: Keywords that indicate when this
            lesson is relevant to a new goal.
        created_at: UTC ISO-8601 timestamp.
        times_applied: How many times this lesson has been used.
        times_helpful: How many times applying this lesson led to
            improvement.
    """

    lesson_id: str
    category: LessonCategory
    summary: str
    detail: str
    confidence: float
    source_attempt_ids: tuple[str, ...]
    source_goal: str
    applicable_goal_keywords: tuple[str, ...]
    created_at: str
    times_applied: int = 0
    times_helpful: int = 0

    def __post_init__(self) -> None:
        """Validate all fields immediately after construction."""
        errors: list[str] = []
        if not self.summary or not self.summary.strip():
            errors.append("summary must be a non-empty string")
        if not (0.0 <= self.confidence <= 1.0):
            errors.append(
                f"confidence must be in [0, 1], got {self.confidence}"
            )
        if not self.source_attempt_ids:
            errors.append("source_attempt_ids must not be empty")
        if self.times_applied < 0:
            errors.append(
                f"times_applied must be >= 0, got {self.times_applied}"
            )
        if self.times_helpful < 0:
            errors.append(
                f"times_helpful must be >= 0, got {self.times_helpful}"
            )
        if self.times_helpful > self.times_applied:
            errors.append(
                "times_helpful cannot exceed times_applied"
            )
        if errors:
            raise ValueError("Invalid Lesson: " + "; ".join(errors))

    @property
    def helpfulness_rate(self) -> float:
        """Fraction of applications that led to improvement.

        Returns ``0.0`` if the lesson has never been applied.
        """
        if self.times_applied == 0:
            return 0.0
        return self.times_helpful / self.times_applied

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "lesson_id": self.lesson_id,
            "category": self.category,
            "summary": self.summary,
            "detail": self.detail,
            "confidence": self.confidence,
            "source_attempt_ids": list(self.source_attempt_ids),
            "source_goal": self.source_goal,
            "applicable_goal_keywords": list(self.applicable_goal_keywords),
            "created_at": self.created_at,
            "times_applied": self.times_applied,
            "times_helpful": self.times_helpful,
            "helpfulness_rate": self.helpfulness_rate,
        }


@dataclass(frozen=True)
class GoalPattern:
    """Aggregate statistics for a category of goals.

    Built from historical attempt data to characterise how well the
    system has performed on similar goals in the past.

    Attributes:
        pattern: Normalised keyword cluster identifying this category.
        total_attempts: Total attempts across all matching goals.
        successful_attempts: How many of those succeeded.
        average_confidence: Mean confidence score achieved.
        common_failure_stages: Most frequent failure stage labels,
            ordered by frequency (descending).
        best_confidence_threshold: The threshold value that produced
            the best success rate historically.
    """

    pattern: str
    total_attempts: int
    successful_attempts: int
    average_confidence: float
    common_failure_stages: tuple[str, ...]
    best_confidence_threshold: float = 0.4

    @property
    def success_rate(self) -> float:
        """Fraction of attempts that succeeded."""
        if self.total_attempts == 0:
            return 0.0
        return self.successful_attempts / self.total_attempts

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "pattern": self.pattern,
            "total_attempts": self.total_attempts,
            "successful_attempts": self.successful_attempts,
            "success_rate": self.success_rate,
            "average_confidence": self.average_confidence,
            "common_failure_stages": list(self.common_failure_stages),
            "best_confidence_threshold": self.best_confidence_threshold,
        }


@dataclass(frozen=True)
class LearningContext:
    """Enriched context built from memory for a new evolution attempt.

    The autonomy loop can consult this context before generating a
    plan or patch to benefit from past experience.

    Attributes:
        goal: The goal this context was built for.
        relevant_lessons: Lessons that match the goal keywords.
        goal_pattern: Aggregate statistics for similar goals, or
            ``None`` if no prior history exists.
        recommended_confidence_threshold: Suggested threshold based on
            historical performance.
        common_failure_modes: Failure stages most likely to occur.
        suggested_strategy: Human-readable advice derived from lessons.
        lesson_count: Total number of lessons in the store.
    """

    goal: str
    relevant_lessons: tuple[Lesson, ...] = ()
    goal_pattern: Optional[GoalPattern] = None
    recommended_confidence_threshold: float = 0.4
    common_failure_modes: tuple[str, ...] = ()
    suggested_strategy: str = "No prior history — proceed with default settings."
    lesson_count: int = 0

    @property
    def has_prior_knowledge(self) -> bool:
        """Whether any relevant lessons or patterns exist."""
        return len(self.relevant_lessons) > 0 or self.goal_pattern is not None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "goal": self.goal,
            "relevant_lessons": [l.to_dict() for l in self.relevant_lessons],
            "goal_pattern": (
                self.goal_pattern.to_dict()
                if self.goal_pattern is not None
                else None
            ),
            "recommended_confidence_threshold": self.recommended_confidence_threshold,
            "common_failure_modes": list(self.common_failure_modes),
            "suggested_strategy": self.suggested_strategy,
            "lesson_count": self.lesson_count,
            "has_prior_knowledge": self.has_prior_knowledge,
        }


@dataclass
class Skill:
    """Compatibility model for learning and evaluation modules."""

    name: str
    mastery: float = 0.0
    attempts: int = 0
    successes: int = 0
    last_used: Optional[str] = None
    skill_id: str = ""
    description: str = ""
    category: str = ""
    examples: tuple[str, ...] = field(default_factory=tuple)
    success_contexts: tuple[str, ...] = field(default_factory=tuple)
    failure_contexts: tuple[str, ...] = field(default_factory=tuple)
    mastery_score: Optional[float] = None
    attempt_count: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if self.mastery < 0.0 or self.mastery > 1.0:
            raise ValueError("mastery must be in [0.0, 1.0]")
        if self.attempts < 0:
            raise ValueError("attempts must be >= 0")
        if self.successes < 0:
            raise ValueError("successes must be >= 0")
        if self.successes > self.attempts:
            raise ValueError("successes cannot exceed attempts")
        if not self.skill_id:
            self.skill_id = self.name
        if self.mastery_score is None:
            self.mastery_score = self.mastery
        else:
            self.mastery = self.mastery_score
        if self.attempt_count is None:
            self.attempt_count = self.attempts
        else:
            self.attempts = self.attempt_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mastery": self.mastery,
            "attempts": self.attempts,
            "successes": self.successes,
            "last_used": self.last_used,
            "skill_id": self.skill_id,
            "description": self.description,
            "category": self.category,
            "examples": list(self.examples),
            "success_contexts": list(self.success_contexts),
            "failure_contexts": list(self.failure_contexts),
            "mastery_score": self.mastery_score,
            "attempt_count": self.attempt_count,
        }


__all__ = [
    "GoalPattern",
    "LearningContext",
    "Lesson",
    "LessonCategory",
    "Skill",
]
