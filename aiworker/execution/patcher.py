"""Unified-diff patch applicator.

Applies a unified diff patch file inside a sandbox workspace directory
using the system ``patch`` utility.  Returns a structured result.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class PatchResult:
    """Structured outcome of a patch operation.

    Attributes:
        success: Whether the patch was applied cleanly.
        return_code: Exit code of the ``patch`` process.
        stdout: Standard output captured from ``patch``.
        stderr: Standard error captured from ``patch``.
    """

    success: bool
    return_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, object]:
        """Serialise to a plain dictionary."""
        return {
            "success": self.success,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class Patcher:
    """Apply a unified diff patch inside a target directory.

    Args:
        target_dir: Absolute path to the directory where the patch
            should be applied (i.e. the sandbox workspace).
    """

    PATCH_TIMEOUT_SECONDS: int = 30

    def __init__(self, target_dir: str) -> None:
        resolved = os.path.realpath(target_dir)
        if not os.path.isabs(resolved):
            raise ValueError(f"target_dir must be absolute, got: {target_dir}")
        if not os.path.isdir(resolved):
            raise FileNotFoundError(f"target_dir does not exist: {resolved}")
        self.target_dir: str = resolved

    _DIFF_HEADER_RE = re.compile(r"^(?:---|\ \+\+\+)\s+(.+?)(?:\t.*)?$", re.MULTILINE)

    def _validate_patch_paths(self, patch_content: str) -> str | None:
        """Scan unified diff headers for paths that escape the target directory.

        Returns:
            An error message if a dangerous path is found, or ``None``
            if all paths are safe.
        """
        for match in re.finditer(
            r"^(?:---|\+\+\+)\s+(.+?)(?:\t.*)?$", patch_content, re.MULTILINE
        ):
            raw_path = match.group(1).strip()

            if raw_path in ("/dev/null", "a/dev/null", "b/dev/null"):
                continue

            # Strip the a/ or b/ prefix that -p1 removes
            if raw_path.startswith(("a/", "b/")):
                stripped = raw_path[2:]
            else:
                stripped = raw_path

            # Reject absolute paths
            if os.path.isabs(stripped):
                return (
                    f"Patch contains absolute path that would escape sandbox: "
                    f"{stripped!r}"
                )

            # Resolve relative to target_dir and verify containment
            resolved = os.path.normpath(os.path.join(self.target_dir, stripped))
            if not resolved.startswith(self.target_dir + os.sep) and resolved != self.target_dir:
                return (
                    f"Patch path traversal detected: {stripped!r} resolves to "
                    f"{resolved!r} outside {self.target_dir!r}"
                )

        return None

    def apply(self, patch_content: str) -> PatchResult:
        """Apply a unified diff given as a string.

        Before invoking the ``patch`` utility the diff headers are
        scanned for absolute or traversal paths.  If any are found the
        patch is rejected without executing ``patch``.

        The content is written to a temporary file which is then passed
        to ``patch -p1 -i <file>``.  The temporary file is always
        deleted afterwards.

        Args:
            patch_content: The full unified diff text.

        Returns:
            A :class:`PatchResult` describing the outcome.
        """
        path_error = self._validate_patch_paths(patch_content)
        if path_error is not None:
            return PatchResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=path_error,
            )

        patch_file_path: str | None = None
        try:
            fd, patch_file_path = tempfile.mkstemp(
                suffix=".patch", prefix="aiworker_"
            )
            with os.fdopen(fd, "w") as fh:
                fh.write(patch_content)

            result = subprocess.run(
                ["patch", "-p1", "-i", patch_file_path],
                cwd=self.target_dir,
                capture_output=True,
                text=True,
                timeout=self.PATCH_TIMEOUT_SECONDS,
            )

            return PatchResult(
                success=result.returncode == 0,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        except subprocess.TimeoutExpired:
            return PatchResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr="Patch operation timed out.",
            )
        except FileNotFoundError:
            return PatchResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr="The 'patch' utility is not installed or not found on PATH.",
            )
        except Exception as exc:
            return PatchResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=str(exc),
            )
        finally:
            if patch_file_path is not None and os.path.exists(patch_file_path):
                os.unlink(patch_file_path)
