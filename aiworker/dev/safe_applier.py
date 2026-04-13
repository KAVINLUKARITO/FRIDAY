"""Safe patch application using temporary workspace and sandbox validation."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Protocol, Sequence

from aiworker.dev.patch_validator import extract_touched_files
from aiworker.execution.patcher import Patcher
from aiworker.execution.runner import ExecutionResult, Runner
from aiworker.execution.sandbox_runner import SandboxRunner

@dataclass(frozen=True)
class SafeApplyResult:
    success: bool
    committed: bool
    rolled_back: bool
    touched_files: tuple[str, ...]
    tests_passed: int
    tests_failed: int
    timed_out: bool
    error: str | None


class SandboxExecutor(Protocol):
    """Protocol wrapper for sandbox execution calls."""

    def run(self, workspace_path: str, patch_content: str) -> ExecutionResult:
        """Execute patch validation in a sandbox and return results."""


class RunnerSandboxExecutor:
    """Default sandbox executor backed by aiworker.execution.Runner."""

    def __init__(self, timeout: int = 60) -> None:
        self._timeout = timeout

    def run(self, workspace_path: str, patch_content: str) -> ExecutionResult:
        runner = Runner(
            workspace_path=workspace_path,
            patch_content=patch_content,
            timeout=self._timeout,
        )
        return runner.execute()


def _is_file_deletion(diff_text: str) -> bool:
    for line in diff_text.splitlines():
        if line.startswith("+++ ") and line[4:].strip() in ("/dev/null", "b/dev/null"):
            return True
    return False


def _copy_workspace(src: str, dst: str) -> None:
    shutil.copytree(src, dst)


def _commit_file_from_clone(
    *,
    workspace_path: str,
    clone_path: str,
    relative_file: str,
    delete_file: bool,
) -> None:
    source = os.path.join(clone_path, relative_file)
    target = os.path.join(workspace_path, relative_file)

    if delete_file:
        if os.path.exists(target):
            os.remove(target)
        return

    os.makedirs(os.path.dirname(target), exist_ok=True)

    staging_dir = tempfile.mkdtemp(prefix="aiworker_commit_stage_")
    try:
        staged_file = os.path.join(staging_dir, os.path.basename(relative_file))
        shutil.copy2(source, staged_file)
        os.replace(staged_file, target)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


class SafeApplier:
    """Applies patch safely by staging in temp workspace and sandboxing tests."""

    def __init__(self, sandbox_executor: SandboxExecutor | None = None) -> None:
        self._sandbox_executor = sandbox_executor or RunnerSandboxExecutor()

    def apply_patch(
        self,
        *,
        workspace_path: str,
        patch_content: str,
        allow_deletions: bool = False,
    ) -> SafeApplyResult:
        touched = extract_touched_files(patch_content)
        temp_root = tempfile.mkdtemp(prefix="aiworker_safe_apply_")
        clone_path = os.path.join(temp_root, "workspace_clone")

        try:
            _copy_workspace(workspace_path, clone_path)

            patcher = Patcher(target_dir=os.path.realpath(clone_path))
            patch_result = patcher.apply(patch_content)
            if not patch_result.success:
                return SafeApplyResult(
                    success=False,
                    committed=False,
                    rolled_back=True,
                    touched_files=touched,
                    tests_passed=0,
                    tests_failed=0,
                    timed_out=False,
                    error=patch_result.stderr or "Patch apply failed",
                )

            sandbox_result = self._sandbox_executor.run(workspace_path, patch_content)
            timed_out = "timeout" in (sandbox_result.error or "").lower()
            if not sandbox_result.success:
                return SafeApplyResult(
                    success=False,
                    committed=False,
                    rolled_back=True,
                    touched_files=touched,
                    tests_passed=sandbox_result.tests_passed,
                    tests_failed=sandbox_result.tests_failed,
                    timed_out=timed_out,
                    error=sandbox_result.error,
                )

            delete_file = _is_file_deletion(patch_content)
            if delete_file and not allow_deletions:
                return SafeApplyResult(
                    success=False,
                    committed=False,
                    rolled_back=True,
                    touched_files=touched,
                    tests_passed=sandbox_result.tests_passed,
                    tests_failed=sandbox_result.tests_failed,
                    timed_out=False,
                    error="Deletion not allowed",
                )

            if len(touched) == 1:
                _commit_file_from_clone(
                    workspace_path=workspace_path,
                    clone_path=clone_path,
                    relative_file=touched[0],
                    delete_file=delete_file,
                )

            return SafeApplyResult(
                success=True,
                committed=True,
                rolled_back=False,
                touched_files=touched,
                tests_passed=sandbox_result.tests_passed,
                tests_failed=sandbox_result.tests_failed,
                timed_out=False,
                error=None,
            )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


__all__ = ["SafeApplyResult", "SafeApplier", "SandboxExecutor"]
