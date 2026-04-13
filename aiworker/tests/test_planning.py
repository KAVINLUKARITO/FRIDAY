"""Tests for the structured planning layer (Milestone 5).

Covers:
- Plan generation for each keyword branch
- Risk estimation rules
- Complexity score bounds
- Plan validation (positive and negative)
- Deterministic behaviour
"""

from __future__ import annotations

import pytest

from aiworker.planning.models import Plan, PlanStep, _VALID_RISK_LEVELS
from aiworker.planning.planner import generate_plan, _estimate_risk
from aiworker.planning.validator import validate_plan


# ── generate_plan return type ────────────────────────────────

class TestGeneratePlanBasic:
    """Basic contract tests for generate_plan."""

    def test_returns_plan_instance(self) -> None:
        result = generate_plan("add logging")
        assert isinstance(result, Plan)

    def test_plan_goal_matches_input(self) -> None:
        result = generate_plan("fix the bug")
        assert result.goal == "fix the bug"

    def test_steps_are_plan_step_instances(self) -> None:
        result = generate_plan("add a feature")
        for step in result.steps:
            assert isinstance(step, PlanStep)


# ── keyword branch tests ────────────────────────────────────

class TestKeywordBranches:
    """Verify correct step types for each keyword."""

    def test_add_keyword_steps(self) -> None:
        plan = generate_plan("add user authentication")
        descriptions = [s.description for s in plan.steps]
        assert "Design new component" in descriptions
        assert "Implement component" in descriptions
        assert any("test" in d.lower() for d in descriptions)
        assert len(plan.steps) == 4

    def test_fix_keyword_steps(self) -> None:
        plan = generate_plan("fix login crash")
        descriptions = [s.description for s in plan.steps]
        assert "Reproduce the issue" in descriptions
        assert "Apply patch" in descriptions
        assert any("test" in d.lower() or "verify" in d.lower() for d in descriptions)
        assert len(plan.steps) == 4

    def test_refactor_keyword_steps(self) -> None:
        plan = generate_plan("refactor database module")
        descriptions = [s.description for s in plan.steps]
        assert "Analyse existing code structure" in descriptions
        assert "Modify code structure" in descriptions
        assert any("test" in d.lower() for d in descriptions)
        assert len(plan.steps) == 4

    def test_default_keyword_steps(self) -> None:
        plan = generate_plan("improve performance")
        descriptions = [s.description for s in plan.steps]
        assert "Analyse requirements" in descriptions
        assert "Implement changes" in descriptions
        assert len(plan.steps) == 3


# ── risk estimation ──────────────────────────────────────────

class TestRiskEstimation:
    """Verify risk rules."""

    def test_core_keyword_produces_high_risk(self) -> None:
        plan = generate_plan("refactor core module")
        for step in plan.steps:
            assert step.estimated_risk == "high"

    def test_long_goal_produces_medium_risk(self) -> None:
        long_goal = "add a very detailed and comprehensive logging system to the application"
        assert len(long_goal) > 60
        plan = generate_plan(long_goal)
        for step in plan.steps:
            assert step.estimated_risk == "medium"

    def test_short_goal_without_core_produces_low_risk(self) -> None:
        plan = generate_plan("fix typo")
        for step in plan.steps:
            assert step.estimated_risk == "low"

    def test_core_takes_precedence_over_length(self) -> None:
        """'core' should produce high risk even if goal is also > 60 chars."""
        long_core = "refactor core " + "x" * 60
        assert len(long_core) > 60
        plan = generate_plan(long_core)
        for step in plan.steps:
            assert step.estimated_risk == "high"


# ── complexity score ─────────────────────────────────────────

class TestComplexityScore:
    """Verify complexity score formula and bounds."""

    def test_complexity_bounded_0_1(self) -> None:
        plan = generate_plan("add feature")
        assert 0.0 <= plan.complexity_score <= 1.0

    def test_complexity_equals_steps_over_10(self) -> None:
        plan = generate_plan("add feature")
        expected = min(len(plan.steps) / 10.0, 1.0)
        assert plan.complexity_score == expected

    def test_complexity_for_default_plan(self) -> None:
        plan = generate_plan("improve something")
        assert plan.complexity_score == 0.3  # 3 steps / 10

    def test_complexity_for_keyword_plan(self) -> None:
        plan = generate_plan("add something")
        assert plan.complexity_score == 0.4  # 4 steps / 10


# ── validate_plan ────────────────────────────────────────────

class TestValidatePlan:
    """Positive and negative validation tests."""

    def test_valid_generated_plan(self) -> None:
        plan = generate_plan("add feature")
        assert validate_plan(plan) is True

    def test_valid_all_keyword_plans(self) -> None:
        for kw in ("add x", "fix y", "refactor z", "something else"):
            plan = generate_plan(kw)
            assert validate_plan(plan) is True, f"Failed for: {kw}"

    def test_invalid_empty_steps(self) -> None:
        plan = Plan(goal="empty", steps=(), complexity_score=0.0)
        assert validate_plan(plan) is False

    def test_invalid_non_sequential_ids(self) -> None:
        steps = (
            PlanStep(step_id=1, description="a", estimated_risk="low", requires_tests=False),
            PlanStep(step_id=3, description="b", estimated_risk="low", requires_tests=False),
        )
        plan = Plan(goal="bad ids", steps=steps, complexity_score=0.2)
        assert validate_plan(plan) is False

    def test_invalid_risk_level(self) -> None:
        steps = (
            PlanStep(step_id=1, description="a", estimated_risk="critical", requires_tests=False),
        )
        plan = Plan(goal="bad risk", steps=steps, complexity_score=0.1)
        assert validate_plan(plan) is False

    def test_invalid_complexity_above_1(self) -> None:
        steps = (
            PlanStep(step_id=1, description="a", estimated_risk="low", requires_tests=False),
        )
        plan = Plan(goal="high complexity", steps=steps, complexity_score=1.5)
        assert validate_plan(plan) is False

    def test_invalid_complexity_below_0(self) -> None:
        steps = (
            PlanStep(step_id=1, description="a", estimated_risk="low", requires_tests=False),
        )
        plan = Plan(goal="neg complexity", steps=steps, complexity_score=-0.1)
        assert validate_plan(plan) is False

    def test_invalid_step_id_starts_at_0(self) -> None:
        steps = (
            PlanStep(step_id=0, description="a", estimated_risk="low", requires_tests=False),
        )
        plan = Plan(goal="zero start", steps=steps, complexity_score=0.1)
        assert validate_plan(plan) is False


# ── determinism ──────────────────────────────────────────────

class TestDeterminism:
    """Verify identical input always produces identical output."""

    def test_same_goal_same_plan(self) -> None:
        plans = [generate_plan("add caching layer") for _ in range(100)]
        first = plans[0]
        for p in plans[1:]:
            assert p.goal == first.goal
            assert p.steps == first.steps
            assert p.complexity_score == first.complexity_score

    def test_same_goal_same_risk(self) -> None:
        risks = [_estimate_risk("refactor core engine") for _ in range(50)]
        assert all(r == "high" for r in risks)


# ── model immutability ───────────────────────────────────────

class TestModelImmutability:
    """Verify frozen dataclasses cannot be mutated."""

    def test_plan_step_frozen(self) -> None:
        step = PlanStep(step_id=1, description="a", estimated_risk="low", requires_tests=False)
        with pytest.raises(AttributeError):
            step.step_id = 2  # type: ignore[misc]

    def test_plan_frozen(self) -> None:
        plan = generate_plan("add feature")
        with pytest.raises(AttributeError):
            plan.goal = "modified"  # type: ignore[misc]


# ── edge cases ───────────────────────────────────────────────

class TestEdgeCases:
    """Edge case coverage."""

    def test_empty_goal(self) -> None:
        plan = generate_plan("")
        assert validate_plan(plan) is True
        assert plan.steps  # should still have default steps

    def test_case_insensitive_keywords(self) -> None:
        plan_lower = generate_plan("add feature")
        plan_upper = generate_plan("ADD feature")
        assert len(plan_lower.steps) == len(plan_upper.steps)
        for s1, s2 in zip(plan_lower.steps, plan_upper.steps):
            assert s1.description == s2.description

    def test_valid_risk_levels_constant(self) -> None:
        assert _VALID_RISK_LEVELS == {"low", "medium", "high"}
