"""Sandbox verification for generated patches.

Applies a patch inside a temporary sandbox, runs the failing test
subset first, then (on success) runs the full suite.  Collects
structured metrics.

All execution is sandboxed.  No writes outside the temp directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from aiworker.execution.runner import Runner, ExecutionResult


@dataclass(frozen=True)
class VerificationResult:
    """Immutable outcome of sandbox verification.

    Attributes:
        success: Whether all tests passed.
        passed_tests: Number of tests that passed.
        failed_tests: Number of tests that failed.
        regression_detected: Whether previously passing tests broke.
        execution_time: Total sandbox execution time in seconds.
        error: Error description if verification failed.
    """

    success: bool
    passed_tests: int
    failed_tests: int
    regression_detected: bool
    execution_time: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "success": self.success,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "regression_detected": self.regression_detected,
            "execution_time": round(self.execution_time, 3),
            "error": self.error,
        }


def verify(
    workspace_path: str,
    patch_text: str,
    timeout: int = 60,
    baseline_passed: int = 0,
    baseline_failed: int = 0,
) -> VerificationResult:
    """Apply a patch in a sandbox and verify test results.

    Steps:
    1. Apply patch to a temporary sandbox copy.
    2. Run the test suite inside the sandbox.
    3. Compare results against baseline for regression detection.
    4. Sandbox is always cleaned up regardless of outcome.

    Args:
        workspace_path: Absolute path to the original workspace.
        patch_text: Unified diff to apply.
        timeout: Maximum seconds for test execution.
        baseline_passed: Number of tests passing before the patch.
        baseline_failed: Number of tests failing before the patch.

    Returns:
        A frozen :class:`VerificationResult`.
    """
    try:
        runner = Runner(
            workspace_path=workspace_path,
            patch_content=patch_text,
            timeout=min(timeout, 120),
        )
        exec_result: ExecutionResult = runner.execute()
    except Exception as exc:
        return VerificationResult(
            success=False,
            passed_tests=0,
            failed_tests=0,
            regression_detected=False,
            error=f"Sandbox execution error: {exc}",
        )

    # Detect regression: more failures than baseline
    regression = False
    if baseline_passed > 0:
        if exec_result.tests_passed < baseline_passed:
            regression = True
    if baseline_failed > 0:
        if exec_result.tests_failed > baseline_failed:
            regression = True

    return VerificationResult(
        success=exec_result.success and not regression,
        passed_tests=exec_result.tests_passed,
        failed_tests=exec_result.tests_failed,
        regression_detected=regression,
        execution_time=exec_result.execution_time,
        error=exec_result.error,
    )
