"""Deterministic task complexity classifier — Phase 4."""
from __future__ import annotations
from aiworker.meta.models import TaskComplexity

_CRITICAL_KEYWORDS = frozenset({"core", "engine", "pipeline", "bootstrap", "architecture"})
_COMPLEX_KEYWORDS  = frozenset({"refactor", "redesign", "migrate", "overhaul", "concurrent"})
_MODERATE_KEYWORDS = frozenset({"integrate", "implement", "extend", "hook"})
_SIMPLE_KEYWORDS   = frozenset({"add", "fix", "patch", "update", "tweak", "adjust"})
_TRIVIAL_KEYWORDS  = frozenset({"rename", "format", "typo", "comment", "docstring"})


def classify(
    goal: str,
    risk_level: str = "low",
    plan_complexity: float = 0.0,
    num_files: int = 1,
) -> TaskComplexity:
    lower = goal.lower()
    words = set(lower.split())

    # Trivial first (highest specificity, lowest risk)
    if words & _TRIVIAL_KEYWORDS:
        return TaskComplexity.TRIVIAL

    if words & _CRITICAL_KEYWORDS:
        return TaskComplexity.CRITICAL

    if words & _COMPLEX_KEYWORDS:
        if risk_level == "high" or num_files > 3:
            return TaskComplexity.CRITICAL
        return TaskComplexity.COMPLEX

    if words & _MODERATE_KEYWORDS:
        if risk_level == "high":
            return TaskComplexity.COMPLEX
        if plan_complexity >= 0.4:
            return TaskComplexity.MODERATE
        return TaskComplexity.SIMPLE

    if words & _SIMPLE_KEYWORDS:
        if risk_level == "high":
            return TaskComplexity.COMPLEX
        if risk_level == "medium":
            return TaskComplexity.MODERATE
        return TaskComplexity.SIMPLE

    # Fallback: use plan_complexity
    if plan_complexity >= 0.7:
        return TaskComplexity.COMPLEX
    if plan_complexity >= 0.4:
        return TaskComplexity.MODERATE
    return TaskComplexity.SIMPLE
