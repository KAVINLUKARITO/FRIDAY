from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from pydantic import BaseModel

from config import settings
from tools import TOOL_REGISTRY, SafetyError, ToolError
from validator import ValidatedAction


class ExecutionResult(BaseModel):
    success: bool
    output: Any
    error: str | None
    duration_seconds: float
    timed_out: bool


class Executor:
    """Execute validated tool invocations with timeout protection."""

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.http_timeout
        )

    def run(self, action: ValidatedAction) -> ExecutionResult:
        if not isinstance(action, ValidatedAction):
            raise TypeError("Executor.run expects a ValidatedAction")

        tool = TOOL_REGISTRY[action.tool_name]
        start = time.perf_counter()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(tool, **action.parameters)

        try:
            output = future.result(timeout=self.timeout_seconds)
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=True,
                output=output,
                error=None,
                duration_seconds=duration,
                timed_out=False,
            )
        except FuturesTimeoutError:
            future.cancel()
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error="execution timed out",
                duration_seconds=duration,
                timed_out=True,
            )
        except SafetyError as exc:
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc),
                duration_seconds=duration,
                timed_out=False,
            )
        except ToolError as exc:
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc),
                duration_seconds=duration,
                timed_out=False,
            )
        except TimeoutError as exc:
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc) or "execution timed out",
                duration_seconds=duration,
                timed_out=True,
            )
        except Exception as exc:
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc) or exc.__class__.__name__,
                duration_seconds=duration,
                timed_out=False,
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
