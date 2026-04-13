from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import runner
from executor import ExecutionResult
from storage import Storage
from validator import ValidatedAction, ValidationError
from verifier import VerificationResult, VerificationStatus


def _validated_action(step_number: int = 1) -> ValidatedAction:
    return ValidatedAction(
        tool_name="list_files",
        parameters={"path": "."},
        reason="reason",
        step_number=step_number,
        checksum=f"checksum-{step_number}",
    )


@dataclass
class PlannerDouble:
    action: dict[str, Any]
    has_more_steps_value: bool = False
    replan_calls: int = 0

    def plan(self, state: Any) -> dict[str, Any]:
        return dict(self.action)

    def replan(self, state: Any, failure_reason: str) -> dict[str, Any]:
        self.replan_calls += 1
        action = dict(self.action)
        action["reason"] = f"replanned because {failure_reason}"
        return action

    def has_more_steps(self, state: Any) -> bool:
        return self.has_more_steps_value


@dataclass
class ValidatorDouble:
    action: ValidatedAction
    should_raise: bool = False

    def validate(self, raw: dict[str, Any]) -> ValidatedAction:
        if self.should_raise:
            raise ValidationError("invalid action")
        return self.action


@dataclass
class ExecutorDouble:
    results: list[ExecutionResult]
    calls: int = 0

    def run(self, action: ValidatedAction) -> ExecutionResult:
        index = min(self.calls, len(self.results) - 1)
        self.calls += 1
        return self.results[index]


@dataclass
class VerifierDouble:
    results: list[VerificationResult]
    calls: int = 0

    def verify(self, action: ValidatedAction, result: ExecutionResult) -> VerificationResult:
        index = min(self.calls, len(self.results) - 1)
        self.calls += 1
        return self.results[index]


@pytest.fixture()
def configured_runner(
    workspace: Path,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(runner.settings, "workspace_dir", workspace)
    monkeypatch.setattr(runner.settings, "db_path", db_path)
    monkeypatch.setattr(runner.settings, "max_steps", 5)
    monkeypatch.setattr(runner.settings, "max_retries", 1)
    monkeypatch.setattr(runner.settings, "max_replans", 1)
    monkeypatch.setattr(runner.settings, "retry_backoff_base", 0.1)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    return workspace


def test_successful_single_step_task_returns_status_completed(
    configured_runner: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner_double = PlannerDouble(
        action={"tool_name": "list_files", "parameters": {"path": "."}, "reason": "list", "step_number": 1}
    )
    validator_double = ValidatorDouble(_validated_action())
    executor_double = ExecutorDouble(
        [ExecutionResult(success=True, output=["sample.txt"], error=None, duration_seconds=0.1, timed_out=False)]
    )
    verifier_double = VerifierDouble(
        [
            VerificationResult(
                status=VerificationStatus.SUCCESS,
                reason="ok",
                verified_at=datetime.now(timezone.utc),
            )
        ]
    )

    monkeypatch.setattr(runner, "Planner", lambda: planner_double)
    monkeypatch.setattr(runner, "Validator", lambda: validator_double)
    monkeypatch.setattr(runner, "Executor", lambda: executor_double)
    monkeypatch.setattr(runner, "Verifier", lambda: verifier_double)

    state = runner.run_task("list files")

    assert state.status == "completed"


def test_failed_task_retries_up_to_max_retries(
    configured_runner: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.settings, "max_retries", 2)
    monkeypatch.setattr(runner.settings, "max_replans", 0)
    planner_double = PlannerDouble(
        action={"tool_name": "list_files", "parameters": {"path": "."}, "reason": "list", "step_number": 1}
    )
    validator_double = ValidatorDouble(_validated_action())
    failure_exec = ExecutionResult(success=False, output=None, error="boom", duration_seconds=0.1, timed_out=False)
    executor_double = ExecutorDouble([failure_exec, failure_exec, failure_exec])
    failure_verification = VerificationResult(
        status=VerificationStatus.FAILURE,
        reason="boom",
        verified_at=datetime.now(timezone.utc),
    )
    verifier_double = VerifierDouble([failure_verification, failure_verification, failure_verification])

    monkeypatch.setattr(runner, "Planner", lambda: planner_double)
    monkeypatch.setattr(runner, "Validator", lambda: validator_double)
    monkeypatch.setattr(runner, "Executor", lambda: executor_double)
    monkeypatch.setattr(runner, "Verifier", lambda: verifier_double)

    state = runner.run_task("list files")

    assert state.status == "aborted"
    assert executor_double.calls == 3


def test_after_max_retries_triggers_replan(
    configured_runner: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.settings, "max_retries", 1)
    monkeypatch.setattr(runner.settings, "max_replans", 1)
    planner_double = PlannerDouble(
        action={"tool_name": "list_files", "parameters": {"path": "."}, "reason": "list", "step_number": 1}
    )
    validator_double = ValidatorDouble(_validated_action())
    executor_double = ExecutorDouble(
        [
            ExecutionResult(success=False, output=None, error="boom", duration_seconds=0.1, timed_out=False),
            ExecutionResult(success=False, output=None, error="boom", duration_seconds=0.1, timed_out=False),
            ExecutionResult(success=True, output=["sample.txt"], error=None, duration_seconds=0.1, timed_out=False),
        ]
    )
    verifier_double = VerifierDouble(
        [
            VerificationResult(
                status=VerificationStatus.FAILURE,
                reason="boom",
                verified_at=datetime.now(timezone.utc),
            ),
            VerificationResult(
                status=VerificationStatus.FAILURE,
                reason="boom",
                verified_at=datetime.now(timezone.utc),
            ),
            VerificationResult(
                status=VerificationStatus.SUCCESS,
                reason="ok",
                verified_at=datetime.now(timezone.utc),
            ),
        ]
    )

    monkeypatch.setattr(runner, "Planner", lambda: planner_double)
    monkeypatch.setattr(runner, "Validator", lambda: validator_double)
    monkeypatch.setattr(runner, "Executor", lambda: executor_double)
    monkeypatch.setattr(runner, "Verifier", lambda: verifier_double)

    state = runner.run_task("list files")

    assert state.status == "completed"
    assert planner_double.replan_calls == 1


def test_after_max_replans_returns_status_aborted(
    configured_runner: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.settings, "max_retries", 0)
    monkeypatch.setattr(runner.settings, "max_replans", 1)
    planner_double = PlannerDouble(
        action={"tool_name": "list_files", "parameters": {"path": "."}, "reason": "list", "step_number": 1}
    )
    validator_double = ValidatorDouble(_validated_action())
    failure_exec = ExecutionResult(success=False, output=None, error="boom", duration_seconds=0.1, timed_out=False)
    executor_double = ExecutorDouble([failure_exec, failure_exec])
    failure_verification = VerificationResult(
        status=VerificationStatus.FAILURE,
        reason="boom",
        verified_at=datetime.now(timezone.utc),
    )
    verifier_double = VerifierDouble([failure_verification, failure_verification])

    monkeypatch.setattr(runner, "Planner", lambda: planner_double)
    monkeypatch.setattr(runner, "Validator", lambda: validator_double)
    monkeypatch.setattr(runner, "Executor", lambda: executor_double)
    monkeypatch.setattr(runner, "Verifier", lambda: verifier_double)

    state = runner.run_task("list files")

    assert state.status == "aborted"
    assert planner_double.replan_calls == 1


def test_exceeding_max_steps_returns_status_step_limit_reached(
    configured_runner: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.settings, "max_steps", 1)
    planner_double = PlannerDouble(
        action={"tool_name": "list_files", "parameters": {"path": "."}, "reason": "list", "step_number": 1},
        has_more_steps_value=True,
    )
    validator_double = ValidatorDouble(_validated_action())
    executor_double = ExecutorDouble(
        [ExecutionResult(success=True, output=["sample.txt"], error=None, duration_seconds=0.1, timed_out=False)]
    )
    verifier_double = VerifierDouble(
        [
            VerificationResult(
                status=VerificationStatus.SUCCESS,
                reason="ok",
                verified_at=datetime.now(timezone.utc),
            )
        ]
    )

    monkeypatch.setattr(runner, "Planner", lambda: planner_double)
    monkeypatch.setattr(runner, "Validator", lambda: validator_double)
    monkeypatch.setattr(runner, "Executor", lambda: executor_double)
    monkeypatch.setattr(runner, "Verifier", lambda: verifier_double)

    state = runner.run_task("list files")

    assert state.status == "step_limit_reached"


def test_every_step_is_persisted_to_storage(
    configured_runner: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.settings, "max_retries", 1)
    monkeypatch.setattr(runner.settings, "max_replans", 0)
    planner_double = PlannerDouble(
        action={"tool_name": "list_files", "parameters": {"path": "."}, "reason": "list", "step_number": 1}
    )
    validator_double = ValidatorDouble(_validated_action())
    failure_exec = ExecutionResult(success=False, output=None, error="boom", duration_seconds=0.1, timed_out=False)
    executor_double = ExecutorDouble([failure_exec, failure_exec])
    failure_verification = VerificationResult(
        status=VerificationStatus.FAILURE,
        reason="boom",
        verified_at=datetime.now(timezone.utc),
    )
    verifier_double = VerifierDouble([failure_verification, failure_verification])

    monkeypatch.setattr(runner, "Planner", lambda: planner_double)
    monkeypatch.setattr(runner, "Validator", lambda: validator_double)
    monkeypatch.setattr(runner, "Executor", lambda: executor_double)
    monkeypatch.setattr(runner, "Verifier", lambda: verifier_double)

    state = runner.run_task("list files")
    storage = Storage(runner.settings.db_path)
    records = storage.get_run(state.run_id)

    assert len(records) == 2
    assert len(state.history) == 2


def test_validation_error_from_validator_sets_status_aborted(
    configured_runner: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner_double = PlannerDouble(
        action={"tool_name": "list_files", "parameters": {"path": "."}, "reason": "list", "step_number": 1}
    )
    validator_double = ValidatorDouble(_validated_action(), should_raise=True)

    monkeypatch.setattr(runner, "Planner", lambda: planner_double)
    monkeypatch.setattr(runner, "Validator", lambda: validator_double)

    state = runner.run_task("list files")

    assert state.status == "aborted"
    assert state.history == []
