"""Tests for the plan simulation engine (Milestone 6).

Covers:
- Return type contract
- Risk penalty effects
- Test bonus effects
- Complexity penalty effects
- Value clamping [0, 1]
- failure = 1 - success identity
- Overall risk classification
- Deterministic behaviour
- Cost score capping
- Empty plan safety
"""

from __future__ import annotations

import pytest

from aiworker.planning.models import Plan, PlanStep
from aiworker.planning.simulator import SimulationResult, simulate_plan


# ── helpers ──────────────────────────────────────────────────

def _step(
    step_id: int = 1,
    risk: str = "low",
    tests: bool = False,
    desc: str = "step",
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        description=desc,
        estimated_risk=risk,
        requires_tests=tests,
    )


def _plan(
    steps: tuple[PlanStep, ...] = (),
    complexity: float = 0.0,
    goal: str = "test goal",
) -> Plan:
    return Plan(goal=goal, steps=steps, complexity_score=complexity)


# ── basic contract ───────────────────────────────────────────

class TestBasicContract:
    """Verify simulate_plan returns correct type and structure."""

    def test_returns_simulation_result(self) -> None:
        plan = _plan(steps=(_step(),), complexity=0.1)
        result = simulate_plan(plan)
        assert isinstance(result, SimulationResult)

    def test_result_is_frozen(self) -> None:
        plan = _plan(steps=(_step(),), complexity=0.1)
        result = simulate_plan(plan)
        with pytest.raises(AttributeError):
            result.overall_risk = "medium"  # type: ignore[misc]


# ── risk penalty ─────────────────────────────────────────────

class TestRiskPenalty:
    """Verify high-risk steps reduce success probability."""

    def test_high_risk_reduces_success(self) -> None:
        low_plan = _plan(steps=(_step(risk="low"),), complexity=0.0)
        high_plan = _plan(steps=(_step(risk="high"),), complexity=0.0)
        low_r = simulate_plan(low_plan)
        high_r = simulate_plan(high_plan)
        assert high_r.estimated_success_probability < low_r.estimated_success_probability

    def test_medium_risk_reduces_success(self) -> None:
        low_plan = _plan(steps=(_step(risk="low"),), complexity=0.0)
        med_plan = _plan(steps=(_step(risk="medium"),), complexity=0.0)
        low_r = simulate_plan(low_plan)
        med_r = simulate_plan(med_plan)
        assert med_r.estimated_success_probability < low_r.estimated_success_probability

    def test_multiple_high_risk_steps(self) -> None:
        steps = tuple(_step(step_id=i, risk="high") for i in range(1, 5))
        plan = _plan(steps=steps, complexity=0.0)
        result = simulate_plan(plan)
        # 0.9 - 4*0.25 = -0.1 → clamped to 0.0
        assert result.estimated_success_probability == 0.0


# ── test bonus ───────────────────────────────────────────────

class TestTestBonus:
    """Verify requires_tests increases success probability."""

    def test_test_bonus_increases_success(self) -> None:
        no_test = _plan(steps=(_step(tests=False),), complexity=0.0)
        with_test = _plan(steps=(_step(tests=True),), complexity=0.0)
        assert simulate_plan(with_test).estimated_success_probability > \
               simulate_plan(no_test).estimated_success_probability

    def test_test_bonus_value(self) -> None:
        no_test = _plan(steps=(_step(tests=False),), complexity=0.0)
        with_test = _plan(steps=(_step(tests=True),), complexity=0.0)
        diff = (
            simulate_plan(with_test).estimated_success_probability
            - simulate_plan(no_test).estimated_success_probability
        )
        assert abs(diff - 0.05) < 1e-9


# ── complexity penalty ───────────────────────────────────────

class TestComplexityPenalty:
    """Verify complexity_score affects success probability."""

    def test_higher_complexity_reduces_success(self) -> None:
        low_c = _plan(steps=(_step(),), complexity=0.0)
        high_c = _plan(steps=(_step(),), complexity=1.0)
        assert simulate_plan(high_c).estimated_success_probability < \
               simulate_plan(low_c).estimated_success_probability

    def test_complexity_penalty_value(self) -> None:
        low_c = _plan(steps=(_step(),), complexity=0.0)
        high_c = _plan(steps=(_step(),), complexity=1.0)
        diff = (
            simulate_plan(low_c).estimated_success_probability
            - simulate_plan(high_c).estimated_success_probability
        )
        # complexity_weight = 0.3, so penalty = 1.0 * 0.3 = 0.3
        assert abs(diff - 0.3) < 1e-9


# ── clamping ─────────────────────────────────────────────────

class TestClamping:
    """Verify all values are clamped to [0, 1]."""

    def test_success_clamped_lower(self) -> None:
        # Many high-risk steps push success below 0
        steps = tuple(_step(step_id=i, risk="high") for i in range(1, 10))
        plan = _plan(steps=steps, complexity=1.0)
        result = simulate_plan(plan)
        assert result.estimated_success_probability >= 0.0

    def test_success_clamped_upper(self) -> None:
        # Many test bonuses could push above 1
        steps = tuple(_step(step_id=i, tests=True) for i in range(1, 10))
        plan = _plan(steps=steps, complexity=0.0)
        result = simulate_plan(plan)
        assert result.estimated_success_probability <= 1.0

    def test_failure_clamped(self) -> None:
        steps = tuple(_step(step_id=i, risk="high") for i in range(1, 10))
        plan = _plan(steps=steps, complexity=1.0)
        result = simulate_plan(plan)
        assert 0.0 <= result.estimated_failure_probability <= 1.0

    def test_cost_clamped(self) -> None:
        steps = tuple(_step(step_id=i) for i in range(1, 20))
        plan = _plan(steps=steps, complexity=0.0)
        result = simulate_plan(plan)
        assert result.estimated_cost_score <= 1.0


# ── failure = 1 - success ────────────────────────────────────

class TestFailureIdentity:
    """Verify failure_probability = 1 - success_probability."""

    def test_identity_low_risk(self) -> None:
        plan = _plan(steps=(_step(),), complexity=0.1)
        r = simulate_plan(plan)
        assert abs(r.estimated_failure_probability - (1.0 - r.estimated_success_probability)) < 1e-9

    def test_identity_high_risk(self) -> None:
        steps = tuple(_step(step_id=i, risk="high") for i in range(1, 4))
        plan = _plan(steps=steps, complexity=0.5)
        r = simulate_plan(plan)
        assert abs(r.estimated_failure_probability - (1.0 - r.estimated_success_probability)) < 1e-9


# ── overall risk mapping ─────────────────────────────────────

class TestOverallRisk:
    """Verify overall_risk classification thresholds."""

    def test_low_risk_threshold(self) -> None:
        # 1 low-risk step, no complexity → success = 0.9 ≥ 0.75
        plan = _plan(steps=(_step(),), complexity=0.0)
        assert simulate_plan(plan).overall_risk == "low"

    def test_medium_risk_threshold(self) -> None:
        # 1 high-risk step, complexity=0.5 → 0.9 - 0.25 - 0.15 = 0.5
        plan = _plan(steps=(_step(risk="high"),), complexity=0.5)
        r = simulate_plan(plan)
        assert 0.4 <= r.estimated_success_probability < 0.75
        assert r.overall_risk == "medium"

    def test_high_risk_threshold(self) -> None:
        # 3 high-risk steps → 0.9 - 0.75 = 0.15 < 0.4
        steps = tuple(_step(step_id=i, risk="high") for i in range(1, 4))
        plan = _plan(steps=steps, complexity=0.0)
        r = simulate_plan(plan)
        assert r.estimated_success_probability < 0.4
        assert r.overall_risk == "high"


# ── determinism ──────────────────────────────────────────────

class TestDeterminism:
    """Verify identical input always produces identical output."""

    def test_deterministic_100_calls(self) -> None:
        steps = (
            _step(step_id=1, risk="medium", tests=True),
            _step(step_id=2, risk="low", tests=False),
        )
        plan = _plan(steps=steps, complexity=0.3)
        results = [simulate_plan(plan) for _ in range(100)]
        first = results[0]
        for r in results[1:]:
            assert r.estimated_success_probability == first.estimated_success_probability
            assert r.estimated_failure_probability == first.estimated_failure_probability
            assert r.estimated_cost_score == first.estimated_cost_score
            assert r.overall_risk == first.overall_risk


# ── cost score ───────────────────────────────────────────────

class TestCostScore:
    """Verify cost score formula."""

    def test_cost_score_formula(self) -> None:
        steps = tuple(_step(step_id=i) for i in range(1, 5))
        plan = _plan(steps=steps, complexity=0.0)
        result = simulate_plan(plan)
        assert result.estimated_cost_score == 4 / 8.0

    def test_large_step_count_caps_at_1(self) -> None:
        steps = tuple(_step(step_id=i) for i in range(1, 20))
        plan = _plan(steps=steps, complexity=0.0)
        result = simulate_plan(plan)
        assert result.estimated_cost_score == 1.0


# ── empty plan ───────────────────────────────────────────────

class TestEmptyPlan:
    """Verify safe handling of empty plans."""

    def test_zero_steps_returns_safe_defaults(self) -> None:
        plan = _plan(steps=(), complexity=0.0)
        r = simulate_plan(plan)
        assert r.estimated_success_probability == 0.0
        assert r.estimated_failure_probability == 1.0
        assert r.estimated_cost_score == 0.0
        assert r.overall_risk == "high"
