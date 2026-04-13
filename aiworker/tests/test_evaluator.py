from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from aiworker.pipeline.evaluator import EvaluationEngine
from aiworker.pipeline.state import AgentState


@pytest.fixture
def metrics_path() -> Path:
    path = Path("runtime") / f"test_metrics_{uuid4().hex}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def evaluator(metrics_path: Path) -> EvaluationEngine:
    return EvaluationEngine(metrics_path)


def make_state(status: str = "SUCCEEDED") -> AgentState:
    state = AgentState(
        task_id="task",
        raw_input="echo",
        planned_actions=[{"tool_name": "echo", "parameters": {"text": "hello"}}],
        steps_planned=1,
        steps_completed=1,
        total_executions=1,
        verified_successes=1,
        terminal_status=status,
    )
    state.finish(status)
    return state


def test_perfect_run_scores_one(evaluator: EvaluationEngine) -> None:
    metrics = evaluator.score(make_state("SUCCEEDED"))

    assert metrics.score == 1.0


def test_aborted_run_scores_at_most_point_two(evaluator: EvaluationEngine) -> None:
    metrics = evaluator.score(make_state("ABORTED"))

    assert metrics.score <= 0.2


def test_step_limit_reached_run_scores_at_most_point_three(evaluator: EvaluationEngine) -> None:
    metrics = evaluator.score(make_state("STEP_LIMIT_REACHED"))

    assert metrics.score <= 0.3


def test_metrics_are_written_to_runtime_metrics_jsonl(evaluator: EvaluationEngine, metrics_path: Path) -> None:
    metrics = evaluator.score(make_state("SUCCEEDED"))

    assert metrics_path.exists()
    assert metrics.run_id in metrics_path.read_text(encoding="utf-8")


def test_get_summary_returns_correct_rolling_average(evaluator: EvaluationEngine) -> None:
    evaluator.score(make_state("SUCCEEDED"))
    evaluator.score(make_state("ABORTED"))

    summary = evaluator.get_summary(last_n=2)
    rolling_average = sum(item.score for item in summary) / len(summary)

    assert len(summary) == 2
    assert rolling_average == pytest.approx(0.6)
