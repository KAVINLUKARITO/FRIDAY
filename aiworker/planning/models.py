"""Data models for the structured planning layer.

Provides immutable dataclasses for plan steps and plans.
No execution logic, no database access, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

_VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class PlanStep:
    """A single step in a structured plan.

    Attributes:
        step_id: Sequential identifier starting at 1.
        description: Human-readable description of the step.
        estimated_risk: One of ``"low"``, ``"medium"``, ``"high"``.
        requires_tests: Whether this step should include test verification.
    """

    step_id: int
    description: str
    estimated_risk: str
    requires_tests: bool


@dataclass(frozen=True)
class Plan:
    """A structured plan for achieving a goal.

    Attributes:
        goal: The original goal string that produced this plan.
        steps: Ordered list of :class:`PlanStep` objects.
        complexity_score: A value in ``[0.0, 1.0]`` reflecting plan
            complexity based on the number of steps.
    """

    goal: str
    steps: tuple[PlanStep, ...] = field(default_factory=tuple)
    complexity_score: float = 0.0
