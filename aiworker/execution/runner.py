"""Execution runner — orchestrates sandbox lifecycle.

Creates a sandbox, applies a patch, runs ``pytest`` inside the sandbox,
collects structured results, and guarantees cleanup.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

from aiworker.execution.patcher import Patcher, PatchResult
from aiworker.execution.sandbox import Sandbox


DEFAULT_TIMEOUT_SECONDS: int = 120

_PYTEST_SUMMARY_RE = re.compile(
    r"(\d+)\s+passed"
)
_PYTEST_FAILED_RE = re.compile(
    r"(\d+)\s+failed"
)


@dataclass
class ExecutionResult:
    """Structured result of a full sandbox execution run.

    Attributes:
        success: Overall success flag (patch applied **and** all tests passed).
        patch_applied: Whether the patch was applied successfully.
        tests_passed: Number of tests that passed.
        tests_failed: Number of tests that failed.
        stdout: Combined stdout from the test run.
        stderr: Combined stderr from the test run.
        execution_time: Wall-clock duration of the test run in seconds.
        error: Human-readable error description, or ``None``.
    """

    success: bool
    patch_applied: bool
    tests_passed: int
    tests_failed: int
    stdout: str
    stderr: str
    execution_time: float
    error: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "success": self.success,
            "patch_applied": self.patch_applied,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "execution_time": round(self.execution_time, 3),
            "error": self.error,
        }


def _parse_pytest_counts(output: str) -> tuple[int, int]:
    """Extract passed/failed counts from pytest output.

    Returns:
        A ``(passed, failed)`` tuple.
    """
    passed = 0
    failed = 0

    match_passed = _PYTEST_SUMMARY_RE.search(output)
    if match_passed:
        passed = int(match_passed.group(1))

    match_failed = _PYTEST_FAILED_RE.search(output)
    if match_failed:
        failed = int(match_failed.group(1))

    return passed, failed


class Runner:
    """Orchestrate sandbox creation, patching, test execution, and cleanup.

    Args:
        workspace_path: Absolute path to the original workspace directory.
        patch_content: Unified diff to apply inside the sandbox workspace.
        timeout: Maximum number of seconds for the pytest subprocess.
    """

    def __init__(
        self,
        workspace_path: str,
        patch_content: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout < 1 or timeout > DEFAULT_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout must be between 1 and {DEFAULT_TIMEOUT_SECONDS}, "
                f"got {timeout}"
            )
        self.workspace_path: str = workspace_path
        self.patch_content: str = patch_content
        self.timeout: int = timeout

    def execute(self) -> ExecutionResult:
        """Run the full sandbox lifecycle and return structured results.

        The method guarantees that the sandbox directory is deleted
        regardless of whether execution succeeds or fails.
        """
        sandbox = Sandbox(workspace_path=self.workspace_path)
        try:
            sandbox.create()
            workspace_dir = sandbox.get_workspace_dir()

            patcher = Patcher(target_dir=workspace_dir)
            patch_result: PatchResult = patcher.apply(self.patch_content)

            if not patch_result.success:
                return ExecutionResult(
                    success=False,
                    patch_applied=False,
                    tests_passed=0,
                    tests_failed=0,
                    stdout=patch_result.stdout,
                    stderr=patch_result.stderr,
                    execution_time=0.0,
                    error=f"Patch failed (exit code {patch_result.return_code}): "
                    f"{patch_result.stderr}",
                )

            return self._run_tests(workspace_dir)

        except Exception as exc:
            return ExecutionResult(
                success=False,
                patch_applied=False,
                tests_passed=0,
                tests_failed=0,
                stdout="",
                stderr=str(exc),
                execution_time=0.0,
                error=str(exc),
            )
        finally:
            sandbox.destroy()

    def _run_tests(self, workspace_dir: str) -> ExecutionResult:
        """Execute pytest inside *workspace_dir* and return results.

        The subprocess is started in its own session (``start_new_session=True``)
        so that on timeout the entire process group can be killed, preventing
        orphaned grandchild processes.
        """
        start = time.monotonic()
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pytest", "-v", "--tb=short", "--no-header"],
                cwd=workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self._restricted_env(),
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(timeout=self.timeout)
            elapsed = time.monotonic() - start

            passed, failed = _parse_pytest_counts(stdout)

            return ExecutionResult(
                success=proc.returncode == 0,
                patch_applied=True,
                tests_passed=passed,
                tests_failed=failed,
                stdout=stdout,
                stderr=stderr,
                execution_time=elapsed,
                error=None if proc.returncode == 0 else "Some tests failed.",
            )

        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            if proc is not None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                proc.wait()
            return ExecutionResult(
                success=False,
                patch_applied=True,
                tests_passed=0,
                tests_failed=0,
                stdout="",
                stderr="Test execution timed out.",
                execution_time=elapsed,
                error=f"Timeout after {self.timeout} seconds.",
            )

    _ENV_ALLOWLIST: tuple[str, ...] = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "PYTHONPATH",
        "PYTHONHASHSEED",
        "VIRTUAL_ENV",
        "PYENV_ROOT",
    )

    @classmethod
    def _restricted_env(cls) -> dict[str, str]:
        """Build a minimal environment allowlist with network access disabled.

        Only a small set of known-safe variables are forwarded from the
        host environment.  Proxy variables are set to unreachable addresses
        to discourage HTTP-based network access.
        """
        env: dict[str, str] = {}
        for key in cls._ENV_ALLOWLIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value

        env["http_proxy"] = "http://0.0.0.0:0"
        env["https_proxy"] = "http://0.0.0.0:0"
        env["no_proxy"] = ""
        env["HTTP_PROXY"] = "http://0.0.0.0:0"
        env["HTTPS_PROXY"] = "http://0.0.0.0:0"
        return env
