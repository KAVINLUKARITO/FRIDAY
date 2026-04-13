"""Pattern extractor — derives generalised principles from attempt outcomes.

Deterministic. No LLM calls. No randomness.
"""
from __future__ import annotations
import uuid
from typing import Optional

from aiworker.learning.models import ExtractedPattern


_STRATEGY_PRINCIPLES: dict[str, str] = {
    "refactor": "Isolate refactoring from feature changes for cleaner diffs.",
    "add": "Design the interface before implementation to reduce rework.",
    "fix": "Reproduce the bug in a test before patching to prevent regression.",
    "default": "Break large changes into incremental, testable steps.",
}


def extract_pattern(
    goal: str,
    strategy: str,
    success: bool,
    score: float,
) -> ExtractedPattern:
    """Derive an ExtractedPattern from a completed attempt.

    Args:
        goal: The original goal string.
        strategy: Which strategy branch was used (refactor/add/fix/default).
        success: Whether the attempt succeeded.
        score: Confidence/scoring result.

    Returns:
        An ExtractedPattern with a generalised principle.
    """
    lower_goal = goal.lower()
    # Detect primary keyword
    detected = "default"
    for kw in ("refactor", "add", "fix"):
        if kw in lower_goal:
            detected = kw
            break

    base_principle = _STRATEGY_PRINCIPLES.get(detected, _STRATEGY_PRINCIPLES["default"])

    if success:
        generalisation = f"[SUCCESS] {base_principle} Score: {score:.2f}."
        outcome = "success"
    else:
        generalisation = (
            f"[FAILURE] Strategy '{strategy}' underperformed for "
            f"'{detected}' goals. Consider alternative decomposition. Score: {score:.2f}."
        )
        outcome = "failure"

    return ExtractedPattern(
        pattern_id=str(uuid.uuid4()),
        goal_fragment=detected,
        strategy_used=strategy,
        outcome=outcome,
        score=round(score, 4),
        generalisation=generalisation,
    )
