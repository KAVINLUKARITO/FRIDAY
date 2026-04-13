"""Build learning context for a new evolution attempt.

Queries the :class:`LearningStore` for relevant lessons and goal
patterns, then assembles a :class:`LearningContext` that the autonomy
loop can consult before generating plans and patches.

All logic is deterministic — identical store state and goal produce
identical context.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional, Sequence

from aiworker.learning.models import (
    GoalPattern,
    LearningContext,
    Lesson,
)
from aiworker.learning.store import LearningStore

# How many lessons to retrieve per query.
_MAX_RELEVANT_LESSONS = 10

# Default threshold when no history exists.
_DEFAULT_THRESHOLD = 0.4

# Minimum lessons needed to recommend a threshold change.
_MIN_LESSONS_FOR_THRESHOLD = 2


def _extract_keywords(goal: str) -> list[str]:
    """Extract search keywords from a goal string.

    Deterministic: same input → same output.
    """
    stopwords = {
        "a", "an", "the", "to", "in", "of", "for", "and", "or", "is",
        "it", "on", "at", "by", "with", "from", "as", "this", "that",
    }
    words = goal.lower().split()
    return sorted({w for w in words if len(w) > 2 and w not in stopwords})


def _build_goal_pattern(lessons: Sequence[Lesson]) -> Optional[GoalPattern]:
    """Build a :class:`GoalPattern` from a set of relevant lessons.

    Returns ``None`` if there are no lessons to analyse.
    """
    if not lessons:
        return None

    # Count successes and failures across lesson sources.
    total = 0
    successes = 0
    confidence_sum = 0.0
    failure_stages: Counter[str] = Counter()

    for lesson in lessons:
        total += 1
        confidence_sum += lesson.confidence

        if lesson.category == "success_pattern":
            successes += 1
        elif lesson.category == "failure_mode":
            # Extract stage from summary (format: "Repeated failures at X stage").
            summary_parts = lesson.summary.split()
            if "at" in summary_parts and "stage" in summary_parts:
                idx = summary_parts.index("at")
                stage = summary_parts[idx + 1] if idx + 1 < len(summary_parts) else "unknown"
                failure_stages[stage] += 1

    avg_confidence = confidence_sum / total if total > 0 else 0.0

    # Compute best threshold from success patterns.
    success_lessons = [l for l in lessons if l.category == "success_pattern"]
    if success_lessons:
        # Use the average confidence from successful lessons as guide.
        best_threshold = sum(l.confidence for l in success_lessons) / len(success_lessons)
        best_threshold = max(0.2, min(best_threshold - 0.1, 0.8))
    else:
        best_threshold = _DEFAULT_THRESHOLD

    common_stages = tuple(
        stage for stage, _ in failure_stages.most_common(5)
    )

    return GoalPattern(
        pattern=", ".join(_extract_keywords(lessons[0].source_goal)) if lessons else "",
        total_attempts=total,
        successful_attempts=successes,
        average_confidence=round(avg_confidence, 3),
        common_failure_stages=common_stages,
        best_confidence_threshold=round(best_threshold, 3),
    )


def _compute_recommended_threshold(
    goal_pattern: Optional[GoalPattern],
    lessons: Sequence[Lesson],
) -> float:
    """Compute a recommended confidence threshold.

    Strategy:
    - If we have a goal pattern with a best threshold, use that.
    - If strategy lessons suggest threshold is too high, lower it.
    - Otherwise, use the default.
    """
    threshold = _DEFAULT_THRESHOLD

    if goal_pattern is not None:
        threshold = goal_pattern.best_confidence_threshold

    # Check for "threshold too high" strategy lessons.
    threshold_lessons = [
        l for l in lessons
        if l.category == "goal_strategy"
        and "threshold" in l.summary.lower()
    ]
    if len(threshold_lessons) >= _MIN_LESSONS_FOR_THRESHOLD:
        # Reduce threshold slightly.
        threshold = max(0.2, threshold - 0.05 * len(threshold_lessons))

    return round(max(0.1, min(threshold, 0.9)), 3)


def _compute_failure_modes(lessons: Sequence[Lesson]) -> tuple[str, ...]:
    """Extract common failure modes from failure-mode lessons."""
    stages: Counter[str] = Counter()
    for lesson in lessons:
        if lesson.category == "failure_mode":
            # Parse stage from summary.
            parts = lesson.summary.split()
            if "at" in parts and "stage" in parts:
                idx = parts.index("at")
                if idx + 1 < len(parts):
                    stages[parts[idx + 1]] += 1
    return tuple(stage for stage, _ in stages.most_common(5))


def _build_strategy(
    lessons: Sequence[Lesson],
    goal_pattern: Optional[GoalPattern],
) -> str:
    """Generate a human-readable strategy suggestion.

    This is deterministic prose construction, not LLM generation.
    """
    if not lessons and goal_pattern is None:
        return "No prior history — proceed with default settings."

    parts: list[str] = []

    if goal_pattern is not None and goal_pattern.total_attempts > 0:
        rate = goal_pattern.success_rate
        parts.append(
            f"Historical success rate: {rate:.0%} "
            f"({goal_pattern.successful_attempts}/{goal_pattern.total_attempts})."
        )

    # Gather unique advice from lessons.
    failure_lessons = [l for l in lessons if l.category == "failure_mode"]
    success_lessons = [l for l in lessons if l.category == "success_pattern"]
    strategy_lessons = [l for l in lessons if l.category == "goal_strategy"]

    if failure_lessons:
        stages = set()
        for l in failure_lessons:
            p = l.summary.split()
            if "at" in p and "stage" in p:
                idx = p.index("at")
                if idx + 1 < len(p):
                    stages.add(p[idx + 1])
        if stages:
            parts.append(
                f"Watch for failures at: {', '.join(sorted(stages))}."
            )

    if success_lessons:
        best = max(success_lessons, key=lambda l: l.confidence)
        parts.append(
            f"Best prior approach achieved confidence {best.confidence:.2f}."
        )

    for sl in strategy_lessons[:2]:
        parts.append(sl.summary + ".")

    if not parts:
        return "Limited prior history — proceed with caution."

    return "  ".join(parts)


def build_context(
    goal: str,
    store: LearningStore,
) -> LearningContext:
    """Build a :class:`LearningContext` for a new evolution goal.

    Queries the store for relevant lessons, computes aggregate
    statistics, and assembles actionable advice.

    This function is deterministic: identical store state and goal
    always produce identical context.

    Args:
        goal: The goal for the new evolution attempt.
        store: The :class:`LearningStore` to query.

    Returns:
        A :class:`LearningContext` with relevant lessons, patterns,
        and recommendations.
    """
    keywords = _extract_keywords(goal)
    relevant = store.get_lessons_for_keywords(
        keywords, limit=_MAX_RELEVANT_LESSONS
    )

    goal_pattern = _build_goal_pattern(relevant)
    threshold = _compute_recommended_threshold(goal_pattern, relevant)
    failure_modes = _compute_failure_modes(relevant)
    strategy = _build_strategy(relevant, goal_pattern)
    total = store.lesson_count()

    return LearningContext(
        goal=goal,
        relevant_lessons=tuple(relevant),
        goal_pattern=goal_pattern,
        recommended_confidence_threshold=threshold,
        common_failure_modes=failure_modes,
        suggested_strategy=strategy,
        lesson_count=total,
    )
