"""Deterministic plan simulation engine.

Estimates success probability, failure risk, and execution cost for a
:class:`Plan` without performing any real operations.  No randomness,
no database access, no sandbox calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiworker.planning.models import Plan

_VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})

_RISK_PENALTY: dict[str, float] = {
    "low": 0.0,
    "medium": 0.1,
    "high": 0.25,
}

_BASE_SUCCESS = 0.9
_TEST_BONUS = 0.05
_COMPLEXITY_WEIGHT = 0.3
_COST_DIVISOR = 8.0


@dataclass(frozen=True)
class SimulationResult:
    """Result of a deterministic plan simulation.

    Attributes:
        estimated_success_probability: Likelihood of plan success ``[0, 1]``.
        estimated_failure_probability: ``1 - estimated_success_probability``.
        estimated_cost_score: Execution cost estimate ``[0, 1]``.
        overall_risk: Categorical risk label derived from success probability.
    """

    estimated_success_probability: float
    estimated_failure_probability: float
    estimated_cost_score: float
    overall_risk: str


def simulate_plan(plan: Plan) -> SimulationResult:
    """Simulate expected outcomes for *plan*.

    The simulation is fully deterministic: identical plans always
    produce identical results.  All numeric outputs are clamped to
    ``[0.0, 1.0]``.

    Args:
        plan: The :class:`Plan` to simulate.

    Returns:
        A :class:`SimulationResult` with estimated probabilities, cost,
        and overall risk classification.
    """
    # Handle empty plan safely.
    if not plan.steps:
        return SimulationResult(
            estimated_success_probability=0.0,
            estimated_failure_probability=1.0,
            estimated_cost_score=0.0,
            overall_risk="high",
        )

    # Accumulate risk penalties and test bonuses across steps.
    total_risk_penalty = 0.0
    total_test_bonus = 0.0
    for step in plan.steps:
        total_risk_penalty += _RISK_PENALTY.get(step.estimated_risk, 0.0)
        if step.requires_tests:
            total_test_bonus += _TEST_BONUS

    complexity_penalty = plan.complexity_score * _COMPLEXITY_WEIGHT

    success_probability = (
        _BASE_SUCCESS
        + total_test_bonus
        - total_risk_penalty
        - complexity_penalty
    )

    # Clamp to [0, 1].
    success_probability = max(0.0, min(1.0, success_probability))
    failure_probability = 1.0 - success_probability

    estimated_cost_score = max(0.0, min(len(plan.steps) / _COST_DIVISOR, 1.0))

    # Classify overall risk.
    if success_probability >= 0.75:
        overall_risk = "low"
    elif success_probability >= 0.4:
        overall_risk = "medium"
    else:
        overall_risk = "high"

    return SimulationResult(
        estimated_success_probability=success_probability,
        estimated_failure_probability=failure_probability,
        estimated_cost_score=estimated_cost_score,
        overall_risk=overall_risk,
    )
