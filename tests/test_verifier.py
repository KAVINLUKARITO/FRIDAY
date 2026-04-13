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
        checksum="checksum",
    )


def test_success_non_empty_output_returns_success(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output="value",
        error=None,
        duration_seconds=0.1,
        timed_out=False,
    )

    verified = Verifier().verify(action, result)

    assert verified.status is VerificationStatus.SUCCESS


def test_success_empty_string_returns_unverified(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output="",
        error=None,
        duration_seconds=0.1,
        timed_out=False,
    )

    verified = Verifier().verify(action, result)

    assert verified.status is VerificationStatus.UNVERIFIED


def test_success_empty_list_returns_unverified(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output=[],
        error=None,
        duration_seconds=0.1,
        timed_out=False,
    )

    verified = Verifier().verify(action, result)

    assert verified.status is VerificationStatus.UNVERIFIED


def test_success_none_output_returns_unverified(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=True,
        output=None,
        error=None,
        duration_seconds=0.1,
        timed_out=False,
    )

    verified = Verifier().verify(action, result)

    assert verified.status is VerificationStatus.UNVERIFIED


def test_failure_with_error_returns_failure(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=False,
        output=None,
        error="boom",
        duration_seconds=0.1,
        timed_out=False,
    )

    verified = Verifier().verify(action, result)

    assert verified.status is VerificationStatus.FAILURE


def test_timed_out_returns_failure(action: ValidatedAction) -> None:
    result = ExecutionResult(
        success=False,
        output=None,
        error="anything",
        duration_seconds=0.1,
        timed_out=True,
    )

    verified = Verifier().verify(action, result)

    assert verified.status is VerificationStatus.FAILURE


@pytest.mark.parametrize(
    ("execution_result", "expected_status"),
    [
        (
            ExecutionResult(
                success=True,
                output="ok",
                error=None,
                duration_seconds=0.1,
                timed_out=False,
            ),
            VerificationStatus.SUCCESS,
        ),
        (
            ExecutionResult(
                success=True,
                output="",
                error=None,
                duration_seconds=0.1,
                timed_out=False,
            ),
            VerificationStatus.UNVERIFIED,
        ),
        (
            ExecutionResult(
                success=False,
                output=None,
                error="fail",
                duration_seconds=0.1,
                timed_out=False,
            ),
            VerificationStatus.FAILURE,
        ),
    ],
)
def test_reason_is_never_empty_for_any_status(
    action: ValidatedAction,
    execution_result: ExecutionResult,
    expected_status: VerificationStatus,
) -> None:
    verified = Verifier().verify(action, execution_result)

    assert verified.status is expected_status
    assert verified.reason
