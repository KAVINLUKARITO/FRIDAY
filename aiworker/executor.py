from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from pydantic import BaseModel

from aiworker.config import settings
from aiworker.tools import TOOL_REGISTRY, SafetyError, ToolError
from aiworker.validator import ValidatedAction


class ExecutionResult(BaseModel):
    success: bool
    output: Any
    error: str | None
    duration_seconds: float
    timed_out: bool
    tool_name: str
    agent_name: str


class Executor:
    """Execute validated actions with timeout protection."""

    def run(
        self,
        action: ValidatedAction,
        timeout: float | None = None,
    ) -> ExecutionResult:
        if not isinstance(action, ValidatedAction):
            raise TypeError("Executor.run expects a ValidatedAction")

        tool = TOOL_REGISTRY[action.tool_name]
        step_timeout = timeout if timeout is not None else settings.step_timeout
        started = time.perf_counter()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(tool, **action.parameters)
        try:
            output = future.result(timeout=step_timeout)
            duration = max(time.perf_counter() - started, 0.0)
            return ExecutionResult(
                success=True,
                output=output,
                error=None,
                duration_seconds=duration,
                timed_out=False,
                tool_name=action.tool_name,
                agent_name=action.agent_name,
            )
        except FuturesTimeoutError:
            future.cancel()
            duration = max(time.perf_counter() - started, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error="execution timed out",
                duration_seconds=duration,
                timed_out=True,
                tool_name=action.tool_name,
                agent_name=action.agent_name,
            )
        except SafetyError as exc:
            duration = max(time.perf_counter() - started, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc),
                duration_seconds=duration,
                timed_out=False,
                tool_name=action.tool_name,
                agent_name=action.agent_name,
            )
        except ToolError as exc:
            duration = max(time.perf_counter() - started, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc),
                duration_seconds=duration,
                timed_out=False,
                tool_name=action.tool_name,
                agent_name=action.agent_name,
            )
        except TimeoutError as exc:
            duration = max(time.perf_counter() - started, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc) or "execution timed out",
                duration_seconds=duration,
                timed_out=True,
                tool_name=action.tool_name,
                agent_name=action.agent_name,
            )
        except Exception as exc:
            duration = max(time.perf_counter() - started, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc) or exc.__class__.__name__,
                duration_seconds=duration,
                timed_out=False,
                tool_name=action.tool_name,
                agent_name=action.agent_name,
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
