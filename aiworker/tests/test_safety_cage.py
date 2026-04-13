from __future__ import annotations

import pytest

from aiworker.pipeline.state import AgentState
from aiworker.safety.safety_cage import SafetyCage, SafetyViolation


@pytest.fixture
def valid_state() -> AgentState:
    return AgentState(
        task_id="task",
        raw_input="echo",
        planned_actions=[{"tool_name": "echo", "parameters": {"text": "hello"}}],
        steps_planned=1,
    )


def test_step_limit_exceeded_raises_safety_violation(valid_state: AgentState) -> None:
    cage = SafetyCage(step_limit=1)
    valid_state.steps_taken = 1

    with pytest.raises(SafetyViolation, match="step limit exceeded"):
        cage.check(valid_state)


def test_forbidden_operation_raises_safety_violation(valid_state: AgentState) -> None:
    cage = SafetyCage(step_limit=20)
    valid_state.planned_actions[0] = {"tool_name": "subprocess", "parameters": {"shell": True, "args": ["bad"]}}

    with pytest.raises(SafetyViolation, match="forbidden operation detected"):
        cage.check(valid_state)


def test_valid_state_passes_check_without_exception(valid_state: AgentState) -> None:
    cage = SafetyCage(step_limit=20)

    cage.check(valid_state)

    assert cage.is_kill_switch_active() is False
