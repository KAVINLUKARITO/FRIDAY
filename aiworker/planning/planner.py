"""Deterministic rule-based plan generator.

Converts a goal string into a structured :class:`Plan` using keyword
matching.  No randomness, no external calls, no execution.
"""

from __future__ import annotations

from aiworker.planning.models import Plan, PlanStep


def _estimate_risk(goal: str) -> str:
    """Determine risk level from goal text.

    Rules (applied in order):
    * Contains ``"core"`` → ``"high"``
    * Length > 60 characters → ``"medium"``
    * Otherwise → ``"low"``
    """
    lower = goal.lower()
    if "core" in lower:
        return "high"
    if len(goal) > 60:
        return "medium"
    return "low"


def _build_steps(keywords: list[tuple[str, bool]], risk: str) -> tuple[PlanStep, ...]:
    """Create a tuple of :class:`PlanStep` from (description, requires_tests) pairs."""
    return tuple(
        PlanStep(
            step_id=idx,
            description=desc,
            estimated_risk=risk,
            requires_tests=tests,
        )
        for idx, (desc, tests) in enumerate(keywords, start=1)
    )


def generate_plan(goal: str) -> Plan:
    """Generate a deterministic plan from a goal string.

    Keyword rules:

    * ``"refactor"`` → analyse existing code, modify structure, run tests
    * ``"add"`` → design component, implement, run tests
    * ``"fix"`` → reproduce issue, apply patch, run tests
    * default → analyse requirements, implement changes, run tests

    Args:
        goal: A human-readable goal description.

    Returns:
        A :class:`Plan` with sequentially numbered steps and a
        complexity score clamped to ``[0.0, 1.0]``.
    """
    risk = _estimate_risk(goal)
    lower = goal.lower()

    if "refactor" in lower:
        step_defs: list[tuple[str, bool]] = [
            ("Analyse existing code structure", False),
            ("Identify refactoring targets", False),
            ("Modify code structure", False),
            ("Run tests to verify refactoring", True),
        ]
    elif "add" in lower:
        step_defs = [
            ("Design new component", False),
            ("Implement component", False),
            ("Write tests for new component", True),
            ("Run full test suite", True),
        ]
    elif "fix" in lower:
        step_defs = [
            ("Reproduce the issue", False),
            ("Identify root cause", False),
            ("Apply patch", False),
            ("Run tests to verify fix", True),
        ]
    else:
        step_defs = [
            ("Analyse requirements", False),
            ("Implement changes", False),
            ("Run tests", True),
        ]

    steps = _build_steps(step_defs, risk)
    complexity = min(len(steps) / 10.0, 1.0)

    return Plan(goal=goal, steps=steps, complexity_score=complexity)
