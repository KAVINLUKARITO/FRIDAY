from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

from failure import FailureClassifier, report_failure
from logger import get_logger


class TaskPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ScheduledTask:
    id: str
    callback: Callable[..., Any]
    priority: TaskPriority
    scheduled_time: datetime
    recurring: bool = False
    interval_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionStage(Enum):
    VALIDATION = "validation"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    COMPLETE = "complete"


@dataclass
class DeterministicExecutionResult:
    stage: ExecutionStage
    success: bool
    output: Any
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DeterministicExecutionEngine:
    """Enforce validator -> executor -> verifier ordering."""

    def __init__(
        self,
        validator: Callable[[dict[str, Any]], tuple[bool, str | None]],
        executor: Callable[[dict[str, Any]], Any],
        verifier: Callable[[Any], tuple[bool, str | None]],
        supervisor: Any | None = None,
    ) -> None:
        self.validator = validator
        self.executor = executor
        self.verifier = verifier
        self.supervisor = supervisor
        self._llm_direct_execution_blocked = True

    def execute(self, action: dict[str, Any]) -> DeterministicExecutionResult:
        if self.supervisor is not None:
            is_safe, reason = self.supervisor.check_action(action)
            if not is_safe:
                return DeterministicExecutionResult(
                    stage=ExecutionStage.VALIDATION,
                    success=False,
                    output=None,
                    error=f"Supervisor blocked: {reason}",
                )

        is_valid, validation_error = self.validator(action)
        if not is_valid:
            return DeterministicExecutionResult(
                stage=ExecutionStage.VALIDATION,
                success=False,
                output=None,
                error=validation_error or "Validation failed",
            )

        try:
            output = self.executor(action)
        except Exception as exc:
            failure = FailureClassifier.classify_execution_error(exc, {"action": action})
            report_failure(failure)
            return DeterministicExecutionResult(
                stage=ExecutionStage.EXECUTION,
                success=False,
                output=None,
                error=f"Execution failed: {exc}",
                metadata={"failure": failure.to_dict()},
            )

        is_verified, verification_error = self.verifier(output)
        if not is_verified:
            failure = FailureClassifier.classify_verification_error(
                verification_error or "Verification failed",
                {"action": action, "output": str(output)},
            )
            report_failure(failure)
            return DeterministicExecutionResult(
                stage=ExecutionStage.VERIFICATION,
                success=False,
                output=output,
                error=verification_error or "Verification failed",
                metadata={"failure": failure.to_dict()},
            )

        if self.supervisor is not None:
            self.supervisor.record_step()
            self.supervisor.record_success()

        return DeterministicExecutionResult(
            stage=ExecutionStage.COMPLETE,
            success=True,
            output=output,
        )

    def block_llm_execution(self) -> None:
        self._llm_direct_execution_blocked = True

    def is_llm_execution_blocked(self) -> bool:
        return self._llm_direct_execution_blocked


class RuntimeEngine:
    """Real-time execution engine with background event loop support."""

    def __init__(self, tick_interval: float = 1.0) -> None:
        self.tick_interval = tick_interval
        self._running = False
        self._paused = False
        self._task_queue: list[ScheduledTask] = []
        self._event_handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._agent_cycle: Callable[[], Any] | None = None
        self._logger = get_logger("runtime")

    def register_agent_cycle(self, cycle_func: Callable[[], Any]) -> None:
        self._agent_cycle = cycle_func

    def register_event_handler(self, event_type: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._event_handlers.setdefault(event_type, []).append(handler)

    def schedule_task(
        self,
        task_id: str,
        callback: Callable[..., Any],
        delay_seconds: float = 0.0,
        priority: TaskPriority = TaskPriority.MEDIUM,
        recurring: bool = False,
        interval_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ScheduledTask:
        scheduled_time = datetime.now() + timedelta(seconds=delay_seconds)
        task = ScheduledTask(
            id=task_id,
            callback=callback,
            priority=priority,
            scheduled_time=scheduled_time,
            recurring=recurring,
            interval_seconds=interval_seconds,
            metadata=metadata or {},
        )
        with self._lock:
            self._task_queue.append(task)
            self._task_queue.sort(key=lambda item: (item.scheduled_time, -item.priority.value))
        return task

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            for index, task in enumerate(self._task_queue):
                if task.id == task_id:
                    self._task_queue.pop(index)
                    return True
        return False

    def emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        for handler in list(self._event_handlers.get(event_type, [])):
            try:
                handler(data)
            except Exception as exc:
                self._logger.error("Event handler error for %s: %s", event_type, exc)

    async def run_once(self) -> None:
        if not self._paused:
            if self._agent_cycle is not None:
                await self._execute_callback(self._agent_cycle)
            await self._process_tasks()

    async def _process_tasks(self) -> None:
        current_time = datetime.now()
        tasks_to_run: list[ScheduledTask] = []
        with self._lock:
            remaining_tasks: list[ScheduledTask] = []
            for task in self._task_queue:
                if task.scheduled_time <= current_time:
                    tasks_to_run.append(task)
                else:
                    remaining_tasks.append(task)
            self._task_queue = remaining_tasks

        for task in tasks_to_run:
            try:
                await self._execute_callback(task.callback)
                if task.recurring and task.interval_seconds is not None:
                    self.schedule_task(
                        task_id=task.id,
                        callback=task.callback,
                        delay_seconds=task.interval_seconds,
                        priority=task.priority,
                        recurring=True,
                        interval_seconds=task.interval_seconds,
                        metadata=task.metadata,
                    )
            except Exception as exc:
                failure = FailureClassifier.classify_system_error(
                    exc,
                    {"task_id": task.id, "metadata": task.metadata},
                )
                report_failure(failure)
                self._logger.error("Task execution error for %s: %s", task.id, exc)

    async def run(self) -> None:
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        while self._running:
            await self.run_once()
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.tick_interval)
            except asyncio.TimeoutError:
                continue

    def start(self) -> bool:
        if self._running:
            return False
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._thread_main, name="RuntimeEngine", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._loop is not None and self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def is_running(self) -> bool:
        return self._running

    async def _execute_callback(self, callback: Callable[..., Any]) -> Any:
        if asyncio.iscoroutinefunction(callback):
            return await callback()
        result = callback()
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._shutdown_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self.run())
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()
            self._loop = None
