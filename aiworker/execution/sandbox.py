"""Secure sandbox execution environment.

Creates isolated temporary directories for safe code execution,
copies workspace contents, validates path boundaries, and guarantees
cleanup after use.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Sandbox:
    """Manages an isolated temporary execution environment.

    Attributes:
        workspace_path: Absolute path to the source workspace to copy.
        sandbox_dir: The created sandbox directory (set after creation).
    """

    workspace_path: str
    sandbox_dir: Optional[str] = field(default=None, init=False)

    def create(self) -> str:
        """Create the sandbox directory and copy workspace contents into it.

        Returns:
            The absolute path to the sandbox directory.

        Raises:
            FileNotFoundError: If *workspace_path* does not exist.
            ValueError: If *workspace_path* is not an absolute path.
        """
        workspace = Path(self.workspace_path).resolve()

        if not workspace.is_absolute():
            raise ValueError(
                f"workspace_path must be an absolute path, got: {self.workspace_path}"
            )

        if not workspace.is_dir():
            raise FileNotFoundError(
                f"Workspace directory does not exist: {workspace}"
            )

        self.sandbox_dir = tempfile.mkdtemp(prefix="aiworker_sandbox_")
        sandbox_workspace = os.path.join(self.sandbox_dir, "workspace")
        shutil.copytree(str(workspace), sandbox_workspace)

        return self.sandbox_dir

    def get_workspace_dir(self) -> str:
        """Return the path to the copied workspace inside the sandbox.

        Raises:
            RuntimeError: If the sandbox has not been created yet.
        """
        if self.sandbox_dir is None:
            raise RuntimeError("Sandbox has not been created yet. Call create() first.")
        return os.path.join(self.sandbox_dir, "workspace")

    def validate_path(self, path: str) -> str:
        """Validate that *path* resides inside the sandbox directory.

        Args:
            path: The path to validate.

        Returns:
            The resolved absolute path if it is inside the sandbox.

        Raises:
            RuntimeError: If the sandbox has not been created yet.
            ValueError: If the resolved path escapes the sandbox boundary.
        """
        if self.sandbox_dir is None:
            raise RuntimeError("Sandbox has not been created yet. Call create() first.")

        resolved = os.path.realpath(path)
        sandbox_real = os.path.realpath(self.sandbox_dir)

        if not resolved.startswith(sandbox_real + os.sep) and resolved != sandbox_real:
            raise ValueError(
                f"Path traversal detected: {path!r} resolves to {resolved!r} "
                f"which is outside the sandbox {sandbox_real!r}"
            )

        return resolved

    @staticmethod
    def _force_remove_readonly(
        func: object, path: str, exc_info: object
    ) -> None:
        """Error handler for :func:`shutil.rmtree`.

        If a file cannot be removed because it is read-only, grant write
        permission and retry.  For any other error, re-raise.
        """
        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
        if callable(func):
            func(path)

    def destroy(self) -> None:
        """Remove the sandbox directory and all its contents.

        Safe to call multiple times; does nothing if the sandbox
        directory has already been removed or was never created.

        Uses an ``onexc`` / ``onerror`` handler to force-remove
        read-only files instead of silently ignoring failures.
        """
        if self.sandbox_dir is not None and os.path.exists(self.sandbox_dir):
            try:
                shutil.rmtree(self.sandbox_dir, onerror=self._force_remove_readonly)
            except Exception:
                logger.warning(
                    "Failed to fully remove sandbox directory: %s",
                    self.sandbox_dir,
                    exc_info=True,
                )
        self.sandbox_dir = None
