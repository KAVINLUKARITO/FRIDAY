"""Deterministic failure classification from sandbox results."""

from __future__ import annotations

from aiworker.orchestration.architecture_models import FailureType, SandboxResult


def classify_failure(sandbox_result: SandboxResult) -> FailureType:
    """Classify sandbox failures into a deterministic failure enum."""
    if sandbox_result.timed_out:
        return FailureType.Timeout

    if sandbox_result.missing_files:
        return FailureType.MissingFile

    output = f"{sandbox_result.stdout}\n{sandbox_result.stderr}".lower()
    if "syntaxerror" in output:
        return FailureType.SyntaxError
    if "importerror" in output or "modulenotfounderror" in output:
        return FailureType.ImportError

    if sandbox_result.tests_total > 0 and sandbox_result.tests_passed < sandbox_result.tests_total:
        return FailureType.TestFailure

    if sandbox_result.exit_code != 0:
        return FailureType.Unknown

    return FailureType.Unknown
