from __future__ import annotations

import pytest

from executor import ExecutionResult
from validator import ValidatedAction
from verifier import VerificationStatus, Verifier


@pytest.fixture()
def action() -> ValidatedAction:
    return ValidatedAction(
        tool_name="list_files",
        parameters={"path": "."},
        reason="List files",
        step_number=1,
        agent_name="TestAgent",
        checksum="checksum",
    )


def test_success_non_empty_output_success(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output="ok",
        error=None,
        duration_seconds=0.1,
        timed_out=False,
        tool_name="list_files",
        agent_name="TestAgent",
    )
    assert Verifier().verify(action, result).status is VerificationStatus.SUCCESS


def test_success_empty_string_unverified(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output="",
        error=None,
        duration_seconds=0.1,
        timed_out=False,
        tool_name="list_files",
        agent_name="TestAgent",
    )
    assert Verifier().verify(action, result).status is VerificationStatus.UNVERIFIED


def test_success_empty_list_unverified(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output=[],
        error=None,
        duration_seconds=0.1,
        timed_out=False,
        tool_name="list_files",
        agent_name="TestAgent",
    )
    assert Verifier().verify(action, result).status is VerificationStatus.UNVERIFIED


def test_success_none_unverified(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output=None,
        error=None,
        duration_seconds=0.1,
        timed_out=False,
        tool_name="list_files",
        agent_name="TestAgent",
    )
    assert Verifier().verify(action, result).status is VerificationStatus.UNVERIFIED


def test_failure_with_error_failure(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=False,
        output=None,
        error="boom",
        duration_seconds=0.1,
        timed_out=False,
        tool_name="list_files",
        agent_name="TestAgent",
    )
    assert Verifier().verify(action, result).status is VerificationStatus.FAILURE


def test_timed_out_failure(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=False,
        output=None,
        error="boom",
        duration_seconds=0.1,
        timed_out=True,
        tool_name="list_files",
        agent_name="TestAgent",
    )
    assert Verifier().verify(action, result).status is VerificationStatus.FAILURE


@pytest.mark.parametrize(
    "result",
    [
        ExecutionResult(
            success=True,
            output="ok",
            error=None,
            duration_seconds=0.1,
            timed_out=False,
            tool_name="list_files",
            agent_name="TestAgent",
        ),
        ExecutionResult(
            success=True,
            output="",
            error=None,
            duration_seconds=0.1,
            timed_out=False,
            tool_name="list_files",
            agent_name="TestAgent",
        ),
        ExecutionResult(
            success=False,
            output=None,
            error="boom",
            duration_seconds=0.1,
            timed_out=False,
            tool_name="list_files",
            agent_name="TestAgent",
        ),
    ],
)
def test_reason_never_empty(action: ValidatedAction, result: ExecutionResult) -> None:
    assert Verifier().verify(action, result).reason
