from __future__ import annotations

import logging
import subprocess
import time
from typing import Any

from pydantic import BaseModel, Field

from aiworker.pipeline.validator import ValidatedAction
from aiworker.tools.tool_registry import ToolRegistry, tool_registry

logger = logging.getLogger(__name__)


class ExecutionTimeout(RuntimeError):
    """Raised when a subprocess-backed action exceeds its timeout."""


class ExecutionResult(BaseModel):
    success: bool
    output: Any
    stderr: str | None
    duration_seconds: float = Field(ge=0.0)
    timed_out: bool


class Executor:
    def __init__(self, registry: ToolRegistry = tool_registry, timeout_seconds: float = 30.0) -> None:
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    def run(self, action: ValidatedAction) -> ExecutionResult:
        if not isinstance(action, ValidatedAction):
            raise TypeError("Executor.run only accepts ValidatedAction")

        start = time.monotonic()
        try:
            if self._looks_like_forbidden_shell_request(action.parameters):
                raise ValueError("shell execution is forbidden")

            if action.tool_name == "subprocess":
                result = self._run_subprocess(action.parameters)
                result.duration_seconds = time.monotonic() - start
                return result

            tool_result = self.registry.execute(action.tool_name, action.parameters, config=None)
            return ExecutionResult(
                success=tool_result.success,
                output=tool_result.data,
                stderr=tool_result.error,
                duration_seconds=time.monotonic() - start,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            logger.exception("execution timed out for %s", action.tool_name)
            return ExecutionResult(
                success=False,
                output=exc.stdout or "",
                stderr=exc.stderr or str(exc),
                duration_seconds=time.monotonic() - start,
                timed_out=True,
            )
        except Exception as exc:
            logger.exception("execution failed for %s", action.tool_name)
            return ExecutionResult(
                success=False,
                output={},
                stderr=str(exc),
                duration_seconds=time.monotonic() - start,
                timed_out=False,
            )

    def _run_subprocess(self, parameters: dict[str, Any]) -> ExecutionResult:
        args = parameters.get("args")
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError("subprocess args must be a list of strings")
        timeout = float(parameters.get("timeout_seconds", self.timeout_seconds))
        completed = subprocess.run(
            args,
            shell=False,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
        return ExecutionResult(
            success=completed.returncode == 0,
            output={"stdout": completed.stdout, "returncode": completed.returncode},
            stderr=completed.stderr,
            duration_seconds=0.0,
            timed_out=False,
        )

    @staticmethod
    def _looks_like_forbidden_shell_request(parameters: dict[str, Any]) -> bool:
        return parameters.get("shell") is True or parameters.get("shell") == "true"
