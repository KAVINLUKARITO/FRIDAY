from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from pydantic import BaseModel

from config import settings
from tools import TOOL_REGISTRY, SafetyError, ToolError
from validator import ValidatedAction

MAX_RETRIES = 2


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

        self._validate_action_parameters(action)
        tool = TOOL_REGISTRY[action.tool_name]
        start = time.perf_counter()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(tool, **action.parameters)

        try:
            output = future.result(timeout=self.timeout_seconds)
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

        output = self._verify_output(action, output)
        duration = max(time.perf_counter() - start, 0.0)
        return ExecutionResult(
            success=True,
            output=output,
            error=None,
            duration_seconds=duration,
            timed_out=False,
        )

    def run_with_retries(
        self,
        action: ValidatedAction,
        *,
        planner: Any,
        validator: Any,
        state: Any,
    ) -> tuple[ValidatedAction, ExecutionResult]:
        current_action = action
        previous_output = getattr(state, "shared_context", {}).get(current_action.step_number - 1)
        if previous_output is not None:
            print(f"[CHAIN INPUT]={previous_output}")

        for attempt in range(MAX_RETRIES):
            print(f"[STEP {current_action.step_number}] TOOL={current_action.tool_name}")
            try:
                result = self.run(current_action)
                if not result.success:
                    raise RuntimeError(result.error or "execution failed")
                return current_action, result
            except Exception as error:
                print(f"[RETRY {attempt + 1}] ERROR={error}")
                if attempt < MAX_RETRIES - 1:
                    replanned = planner.replan(state, str(error))
                    current_action = validator.validate(replanned)
                    continue
                raise RuntimeError("Execution failed after retries") from error

    @staticmethod
    def _validate_action_parameters(action: ValidatedAction) -> None:
        if action.tool_name != "read_file":
            return

        path = action.parameters.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ToolError("read_file requires a non-empty 'path' parameter")

    @staticmethod
    def _verify_output(action: ValidatedAction, output: Any) -> Any:
        if action.tool_name == "web_search":
            if not isinstance(output, str) or "http" not in output:
                raise ToolError("web_search must return a URL")
            return output

        if action.tool_name != "read_file":
            return output

        if isinstance(output, str):
            content = output
        elif isinstance(output, dict):
            content = output.get("content")
        else:
            content = None

        if not isinstance(content, str) or not content:
            raise ToolError("read_file returned empty content")

        return output
