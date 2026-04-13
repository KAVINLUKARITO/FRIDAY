"""Retry policy engine for architecture task correction guidance."""

from __future__ import annotations

from aiworker.orchestration.architecture_models import FailureType


_RETRY_INSTRUCTIONS = {
    FailureType.SyntaxError: (
        "Fix Python syntax errors and return a minimal corrected diff that compiles."
    ),
    FailureType.ImportError: (
        "Resolve missing or invalid imports using existing project modules only."
    ),
    FailureType.TestFailure: (
        "Adjust logic to satisfy failing tests without broad refactors."
    ),
    FailureType.MissingFile: (
        "Create or reference required files only within allowed paths."
    ),
    FailureType.Timeout: (
        "Reduce complexity and ensure execution terminates deterministically."
    ),
    FailureType.Unknown: (
        "Apply a minimal corrective patch focused on deterministic runtime stability."
    ),
}


def get_retry_instruction(failure_type: FailureType) -> str:
    """Return deterministic corrective instruction for a failure type."""
    return _RETRY_INSTRUCTIONS[failure_type]
