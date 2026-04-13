"""Sandbox-only patch application wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple



@dataclass(frozen=True)
class SandboxApplyResult:
    success: bool
    touched_files: Tuple[str, ...]
    tests_passed: int
    tests_failed: int
    error: str | None


class SandboxRunner(Protocol):
    """Protocol for sandbox patch execution."""

    def apply_patch(self, *, workspace_path: str, patch_content: str) -> SandboxApplyResult:
        """Apply *patch_content* through sandbox and return structured result."""


class DefaultSandboxRunner:
    """Default sandbox runner backed by SafeApplier."""

    def __init__(self, applier: SafeApplier | None = None) -> None:
        self._applier = applier or SafeApplier()

    def apply_patch(self, *, workspace_path: str, patch_content: str) -> SandboxApplyResult:
        result = self._applier.apply_patch(
            workspace_path=workspace_path,
            patch_content=patch_content,
            allow_deletions=False,
        )
        return SandboxApplyResult(
            success=result.success,
            touched_files=result.touched_files,
            tests_passed=result.tests_passed,
            tests_failed=result.tests_failed,
            error=result.error,
        )


__all__ = ["DefaultSandboxRunner", "SandboxApplyResult", "SandboxRunner"]
