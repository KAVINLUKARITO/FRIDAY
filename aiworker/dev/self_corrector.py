"""Self-correction prompt engine for deterministic retries."""

from __future__ import annotations

from dataclasses import dataclass

from aiworker.dev.failure_classifier import classify_failure


@dataclass(frozen=True)
class CorrectionPlan:
    failure_type: str
    corrective_prompt: str
    retry_allowed: bool


def _retry_allowed(failure_type: str) -> bool:
    return failure_type in {
        "syntax_error",
        "import_error",
        "validation_error",
        "test_failure",
        "unknown",
    }


def build_correction_prompt(
    *,
    failure_type: str,
    error_message: str,
    failing_file: str,
    failing_test_output: str,
) -> str:
    """Create strict correction prompt with single-file edit constraint."""
    return (
        "CORRECTION REQUIRED\n"
        f"Failure type: {failure_type}\n"
        f"Error message: {error_message}\n"
        f"Failing file: {failing_file}\n"
        f"Failing test output: {failing_test_output}\n"
        "Rules:\n"
        "1. Modify only the failing file listed above.\n"
        "2. Do not refactor unrelated code.\n"
        "3. Return unified diff for one file only.\n"
        "4. Preserve architecture and module boundaries."
    )


def build_correction_plan(
    *,
    error_message: str,
    failing_file: str,
    failing_test_output: str,
    stderr: str = "",
    timed_out: bool = False,
    validation_errors: tuple[str, ...] = (),
    tests_failed: int = 0,
    risk_score: float = 0.0,
    risk_threshold: float = 1.0,
) -> CorrectionPlan:
    """Classify failure and produce deterministic correction plan."""
    failure_type = classify_failure(
        error_message=error_message,
        stderr=stderr,
        timed_out=timed_out,
        validation_errors=validation_errors,
        tests_failed=tests_failed,
        risk_score=risk_score,
        risk_threshold=risk_threshold,
    )
    prompt = build_correction_prompt(
        failure_type=failure_type,
        error_message=error_message,
        failing_file=failing_file,
        failing_test_output=failing_test_output,
    )
    return CorrectionPlan(
        failure_type=failure_type,
        corrective_prompt=prompt,
        retry_allowed=_retry_allowed(failure_type),
    )


__all__ = [
    "CorrectionPlan",
    "build_correction_plan",
    "build_correction_prompt",
]
