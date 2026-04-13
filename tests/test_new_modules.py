from __future__ import annotations

import asyncio

import pytest

from control import AgentConfig, AgentControlState, AgentController
from failure import FailureClassifier, FailureType, Severity, clear_failure_handlers
from monitor import Monitor
from runtime import (
    DeterministicExecutionEngine,
    ExecutionStage,
    RuntimeEngine,
    TaskPriority,
)
from stress_test import StressTester
from supervisor import Supervisor, SupervisorState


class TestSupervisor:
    def test_max_steps_enforcement(self) -> None:
        supervisor = Supervisor(max_steps=3)
        supervisor.step_count = 3
        is_safe, reason = supervisor.check_action({"action": "test"})
        assert not is_safe
        assert reason is not None
        assert "Max steps" in reason

    def test_repeat_detection(self) -> None:
        supervisor = Supervisor(repeat_threshold=2, time_window=60.0)
        action = {"action": "same"}
        supervisor.check_action(action)
        supervisor.check_action(action)
        is_safe, reason = supervisor.check_action(action)
        assert not is_safe
        assert reason is not None
        assert "repeated" in reason.lower()
        assert supervisor.get_state() is SupervisorState.WARNING

    def test_retry_exhaustion_triggers_abort(self) -> None:
        aborted: list[str] = []
        supervisor = Supervisor(max_retries=2)
        supervisor.register_callbacks(lambda: None, aborted.append)
        assert supervisor.record_retry() is True
        assert supervisor.record_retry() is False
        assert aborted == ["Max retries (2) exceeded"]


class TestFailureSystem:
    def test_failure_creation(self) -> None:
        failure = FailureClassifier.classify_validation_error("bad input", {"task": "test"})
        assert failure.type is FailureType.VALIDATION
        assert failure.retryable is False
        assert failure.severity is Severity.MEDIUM

    def test_classifier_execution_error(self) -> None:
        try:
            raise ValueError("boom")
        except Exception as exc:
            failure = FailureClassifier.classify_execution_error(exc, {"task": "test"})
        assert failure.type is FailureType.EXECUTION
        assert failure.retryable is True
        assert failure.message == "boom"


class TestDeterministicExecutionEngine:
    def test_execute_success_pipeline(self) -> None:
        supervisor = Supervisor()
        engine = DeterministicExecutionEngine(
            validator=lambda action: (True, None),
            executor=lambda action: {"result": action["value"]},
            verifier=lambda output: (True, None),
            supervisor=supervisor,
        )
        result = engine.execute({"value": 1})
        assert result.stage is ExecutionStage.COMPLETE
        assert result.success is True
        assert result.output == {"result": 1}

    def test_execute_validation_failure(self) -> None:
        engine = DeterministicExecutionEngine(
            validator=lambda action: (False, "invalid"),
            executor=lambda action: action,
            verifier=lambda output: (True, None),
        )
        result = engine.execute({"value": 1})
        assert result.stage is ExecutionStage.VALIDATION
        assert result.success is False
        assert result.error == "invalid"


class TestRuntime:
    def test_task_scheduling(self) -> None:
        runtime = RuntimeEngine(tick_interval=0.01)
        executed: list[int] = []

        def task() -> None:
            executed.append(1)

        runtime.schedule_task("test", task, delay_seconds=0.0, priority=TaskPriority.HIGH)
        asyncio.run(runtime.run_once())
        assert executed == [1]


class TestMonitor:
    def test_metrics_collection(self) -> None:
        monitor = Monitor(db_path=":memory:")
        monitor.record_task_start()
        monitor.record_task_success(1.0)
        snapshot = monitor.get_snapshot()
        assert snapshot.total_tasks == 1
        assert snapshot.successful_tasks == 1
        assert snapshot.task_success_rate == 100.0
        monitor.close()


class TestControl:
    def test_state_transitions(self) -> None:
        class RuntimeDouble:
            def __init__(self) -> None:
                self.running = False
                self.paused = False

            def start(self) -> bool:
                self.running = True
                return True

            def stop(self) -> None:
                self.running = False

            def pause(self) -> None:
                self.paused = True

            def resume(self) -> None:
                self.paused = False

        controller = AgentController(AgentConfig(name="test"))
        controller.register_runtime(RuntimeDouble())
        assert controller.state is AgentControlState.STOPPED
        assert controller.start_agent() is True
        assert controller.state is AgentControlState.RUNNING
        assert controller.pause_agent() is True
        assert controller.state is AgentControlState.PAUSED
        assert controller.resume_agent() is True
        assert controller.state is AgentControlState.RUNNING
        assert controller.stop_agent() is True
        assert controller.state is AgentControlState.STOPPED


class TestStressTester:
    def test_stress_test_runs_and_collects_results(self) -> None:
        controller = AgentController(AgentConfig(name="stress"))
        monitor = Monitor(db_path=":memory:")
        supervisor = Supervisor(max_steps=1000, max_retries=3, repeat_threshold=1)
        tester = StressTester(controller, monitor, supervisor)
        result = asyncio.run(tester.run_stress_test(cycles=10, inject_failures=False))
        assert result.total_cycles == 10
        assert result.successful_cycles == 10
        assert result.failed_cycles == 0
        monitor.close()


def teardown_module(module) -> None:  # type: ignore[no-untyped-def]
    del module
    clear_failure_handlers()
