from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aiworker.pipeline.decision_engine import DecisionEngine
from aiworker.pipeline.state import AgentState
from aiworker.pipeline.verifier import VerificationResult


@pytest.fixture
def state() -> AgentState:
    return AgentState(
        task_id="task",
        raw_input="echo",
        planned_actions=[{"tool_name": "echo", "parameters": {"text": "hello"}}],
        steps_planned=1,
    )


@pytest.fixture
def delays() -> list[int]:
    return []


@pytest.fixture
def engine(delays: list[int]) -> DecisionEngine:
    return DecisionEngine(max_retries=3, max_replans=2, step_limit=20, sleep_func=delays.append)


def verification(status: str) -> VerificationResult:
    return VerificationResult(
        status=status,
        reason=f"{status} reason",
        raw_output={"text": "hello"},
        verified_at=datetime.now(timezone.utc),
    )


def test_success_result_advances_to_continue(engine: DecisionEngine, state: AgentState) -> None:
    decision = engine.decide(verification("SUCCESS"), state)

    assert decision.action == "CONTINUE"
    assert state.steps_completed == 1


def test_failure_retries_up_to_max_retries_then_replan(engine: DecisionEngine, state: AgentState) -> None:
    assert engine.decide(verification("FAILURE"), state).action == "RETRY"
    assert engine.decide(verification("FAILURE"), state).action == "RETRY"
    assert engine.decide(verification("FAILURE"), state).action == "RETRY"
    decision = engine.decide(verification("FAILURE"), state)

    assert decision.action == "REPLAN"
    assert decision.replan_count == 1


def test_exceeding_max_replans_returns_aborted(engine: DecisionEngine, state: AgentState) -> None:
    state.current_action_retries = 3
    state.replans = 2

    decision = engine.decide(verification("FAILURE"), state)

    assert decision.action == "ABORTED"
    assert state.terminal_status == "ABORTED"


def test_step_count_at_step_limit_returns_step_limit_reached(state: AgentState) -> None:
    engine = DecisionEngine(max_retries=3, max_replans=2, step_limit=1, sleep_func=lambda _: None)
    state.steps_taken = 1

    decision = engine.decide(verification("FAILURE"), state)

    assert decision.action == "STEP_LIMIT_REACHED"
    assert state.terminal_status == "STEP_LIMIT_REACHED"


def test_backoff_delay_increases_exponentially_on_retries(engine: DecisionEngine, state: AgentState, delays: list[int]) -> None:
    engine.decide(verification("FAILURE"), state)
    engine.decide(verification("FAILURE"), state)
    engine.decide(verification("FAILURE"), state)

    assert delays == [1, 2, 4]
