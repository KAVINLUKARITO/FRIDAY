"""Deterministic lesson extraction from evolution results.

Analyses completed :class:`EvolutionResult` objects and produces
structured :class:`Lesson` instances that capture reusable insights.

All analysis is rule-based and deterministic — no randomness, no
LLM calls, no external dependencies.

Extraction rules:

1. **Failure mode lessons** — when attempts fail repeatedly at the
   same stage, a lesson is created identifying that failure mode.
2. **Success pattern lessons** — when an attempt succeeds, a lesson
   captures the conditions (goal keywords, config, confidence).
3. **Goal strategy lessons** — when the overall result reveals a
   pattern (e.g. high threshold → rejection), a lesson is created.
4. **Patch heuristic lessons** — when patch characteristics correlate
   with outcomes, a lesson captures the heuristic.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from aiworker.autonomy.models import AttemptRecord, EvolutionResult
from aiworker.learning.models import (
    Lesson,
    LessonCategory,
    _new_lesson_id,
    _utcnow_iso,
)

# Minimum attempts before a failure pattern is worth recording.
_MIN_FAILURES_FOR_LESSON = 2

# Keywords extracted from goals for lesson applicability.
_GOAL_KEYWORD_STOPWORDS = frozenset({
    "a", "an", "the", "to", "in", "of", "for", "and", "or", "is",
    "it", "on", "at", "by", "with", "from", "as", "this", "that",
})


def _extract_keywords(goal: str) -> tuple[str, ...]:
    """Extract normalised keywords from a goal string.

    Removes stopwords and short tokens.  Deterministic for identical
    input.

    Args:
        goal: The goal text to extract keywords from.

    Returns:
        A sorted tuple of unique lowercase keywords.
    """
    words = goal.lower().split()
    keywords = sorted({
        w for w in words
        if len(w) > 2 and w not in _GOAL_KEYWORD_STOPWORDS
    })
    return tuple(keywords)


def _failure_stage(record: AttemptRecord) -> str:
    """Identify the pipeline stage where an attempt failed.

    Returns a short label suitable for lesson categorisation.
    """
    if not record.policy_allowed:
        return "governance"
    if not record.plan_generated:
        return "planning"
    if not record.patch_generated:
        return "patch_generation"
    if not record.validation_passed:
        return "validation"
    if not record.sandbox_success:
        return "sandbox"
    # If all stages passed but outcome isn't success, scoring rejected it.
    return "scoring"


def _extract_failure_mode_lessons(
    result: EvolutionResult,
    failed_attempts: Sequence[AttemptRecord],
) -> list[Lesson]:
    """Extract lessons from repeated failure patterns."""
    if len(failed_attempts) < _MIN_FAILURES_FOR_LESSON:
        return []

    # Count failure stages.
    stage_counts: Counter[str] = Counter()
    for attempt in failed_attempts:
        stage_counts[_failure_stage(attempt)] += 1

    lessons: list[Lesson] = []
    keywords = _extract_keywords(result.config.goal)

    for stage, count in stage_counts.most_common():
        if count < _MIN_FAILURES_FOR_LESSON:
            continue

        # Confidence scales with sample size, capped at 0.9.
        confidence = min(0.3 + 0.1 * count, 0.9)

        attempt_ids = tuple(
            a.attempt_id for a in failed_attempts
            if _failure_stage(a) == stage
        )

        lessons.append(Lesson(
            lesson_id=_new_lesson_id(),
            category="failure_mode",
            summary=f"Repeated failures at {stage} stage",
            detail=(
                f"Goal '{result.config.goal}' experienced {count} "
                f"failures at the {stage} stage across "
                f"{result.total_attempts} total attempts.  "
                f"Risk level: {result.config.risk_level}.  "
                f"Consider reviewing {stage} constraints before retrying."
            ),
            confidence=confidence,
            source_attempt_ids=attempt_ids,
            source_goal=result.config.goal,
            applicable_goal_keywords=keywords,
            created_at=_utcnow_iso(),
        ))

    return lessons


def _extract_success_pattern_lessons(
    result: EvolutionResult,
    successful_attempts: Sequence[AttemptRecord],
) -> list[Lesson]:
    """Extract lessons from successful attempts."""
    if not successful_attempts:
        return []

    keywords = _extract_keywords(result.config.goal)
    best = max(successful_attempts, key=lambda a: a.confidence_score)

    # Confidence based on success consistency.
    success_rate = len(successful_attempts) / max(result.total_attempts, 1)
    confidence = min(0.4 + 0.4 * success_rate, 0.95)

    return [Lesson(
        lesson_id=_new_lesson_id(),
        category="success_pattern",
        summary=f"Successful approach for {result.config.risk_level}-risk goal",
        detail=(
            f"Goal '{result.config.goal}' succeeded with confidence "
            f"{best.confidence_score:.2f}.  "
            f"Configuration: max_lines={result.config.max_lines_changed}, "
            f"threshold={result.config.confidence_threshold}, "
            f"risk={result.config.risk_level}.  "
            f"Success rate: {success_rate:.0%} "
            f"({len(successful_attempts)}/{result.total_attempts})."
        ),
        confidence=confidence,
        source_attempt_ids=(best.attempt_id,),
        source_goal=result.config.goal,
        applicable_goal_keywords=keywords,
        created_at=_utcnow_iso(),
    )]


def _extract_goal_strategy_lessons(
    result: EvolutionResult,
) -> list[Lesson]:
    """Extract high-level strategy lessons from the overall result."""
    lessons: list[Lesson] = []
    keywords = _extract_keywords(result.config.goal)
    attempt_ids = tuple(a.attempt_id for a in result.attempts[:1]) or ("unknown",)

    # Lesson: threshold too high for goal type.
    if (
        not result.success
        and result.termination_reason in (
            "max_attempts_reached",
            "all_attempts_exhausted",
        )
    ):
        # Check if scoring was the dominant failure.
        scoring_failures = sum(
            1 for a in result.attempts
            if a.outcome == "scoring_below_threshold"
        )
        if scoring_failures >= 2:
            lessons.append(Lesson(
                lesson_id=_new_lesson_id(),
                category="goal_strategy",
                summary="Confidence threshold may be too high",
                detail=(
                    f"Goal '{result.config.goal}' had "
                    f"{scoring_failures} scoring rejections with "
                    f"threshold={result.config.confidence_threshold}.  "
                    f"Consider lowering the threshold or improving "
                    f"historical success rate first."
                ),
                confidence=min(0.3 + 0.1 * scoring_failures, 0.85),
                source_attempt_ids=attempt_ids,
                source_goal=result.config.goal,
                applicable_goal_keywords=keywords,
                created_at=_utcnow_iso(),
            ))

    # Lesson: circuit breaker tripped → systemic instability.
    if result.termination_reason == "circuit_breaker_open":
        lessons.append(Lesson(
            lesson_id=_new_lesson_id(),
            category="goal_strategy",
            summary="Circuit breaker tripped — systemic instability",
            detail=(
                f"Goal '{result.config.goal}' triggered the circuit "
                f"breaker after {result.failed_attempts} consecutive "
                f"failures.  The system may need manual intervention "
                f"or the goal may need decomposition into smaller steps."
            ),
            confidence=0.8,
            source_attempt_ids=attempt_ids,
            source_goal=result.config.goal,
            applicable_goal_keywords=keywords,
            created_at=_utcnow_iso(),
        ))

    return lessons


def _extract_patch_heuristic_lessons(
    result: EvolutionResult,
    successful_attempts: Sequence[AttemptRecord],
    failed_attempts: Sequence[AttemptRecord],
) -> list[Lesson]:
    """Extract lessons about patch characteristics."""
    lessons: list[Lesson] = []
    keywords = _extract_keywords(result.config.goal)

    # Count patches that were generated but failed validation.
    validation_failures = [
        a for a in failed_attempts
        if a.patch_generated and not a.validation_passed
    ]

    if len(validation_failures) >= _MIN_FAILURES_FOR_LESSON:
        attempt_ids = tuple(a.attempt_id for a in validation_failures)
        lessons.append(Lesson(
            lesson_id=_new_lesson_id(),
            category="patch_heuristic",
            summary="Generated patches frequently fail validation",
            detail=(
                f"For goal '{result.config.goal}', "
                f"{len(validation_failures)} patches were generated "
                f"but rejected by the validator.  The patch generator "
                f"may need tighter constraints or the allowed_files "
                f"list may be too restrictive (limit: "
                f"{result.config.max_lines_changed} lines, "
                f"files: {list(result.config.allowed_files)})."
            ),
            confidence=min(0.4 + 0.1 * len(validation_failures), 0.85),
            source_attempt_ids=attempt_ids,
            source_goal=result.config.goal,
            applicable_goal_keywords=keywords,
            created_at=_utcnow_iso(),
        ))

    return lessons


def analyze_result(result: EvolutionResult) -> list[Lesson]:
    """Extract all applicable lessons from a completed evolution result.

    This is the main entry point for the analyzer.  It delegates to
    category-specific extractors and returns the combined list.

    The analysis is fully deterministic: identical results always
    produce identical lessons (modulo UUIDs and timestamps).

    Args:
        result: A completed :class:`EvolutionResult`.

    Returns:
        A list of :class:`Lesson` objects extracted from the result.
        May be empty if the result does not contain enough data to
        generate useful lessons.
    """
    successful = [a for a in result.attempts if a.outcome == "success"]
    failed = [a for a in result.attempts if a.outcome != "success"]

    lessons: list[Lesson] = []
    lessons.extend(_extract_failure_mode_lessons(result, failed))
    lessons.extend(_extract_success_pattern_lessons(result, successful))
    lessons.extend(_extract_goal_strategy_lessons(result))
    lessons.extend(_extract_patch_heuristic_lessons(result, successful, failed))

    return lessons
