from __future__ import annotations

import threading
import time
import unittest

from aiworker.llm.model_registry import ModelProfile, ModelRegistry
from aiworker.llm.model_router import ModelRouter
from aiworker.llm.runtime_limiter import RuntimeLimiter
from aiworker.orchestration.planner_executor_flow import PlannerExecutorFlow


class FakeBackend:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0
        self.last_prompt = ""

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.last_prompt = prompt
        return self.value


def _build_registry() -> ModelRegistry:
    registry = ModelRegistry()
    registry.register(
        ModelProfile(
            name="planner-model",
            role="planner",
            max_context=16000,
            avg_latency_ms=500,
            cost_weight=1.0,
            reliability_score=0.99,
        )
    )
    registry.register(
        ModelProfile(
            name="executor-model",
            role="executor",
            max_context=4096,
            avg_latency_ms=120,
            cost_weight=0.2,
            reliability_score=0.95,
        )
    )
    return registry


class TestModelRouter(unittest.TestCase):
    def test_planner_role_selected_correctly(self) -> None:
        registry = _build_registry()
        router = ModelRouter(registry=registry, limiter=RuntimeLimiter())
        profile = router.route("planning")
        self.assertEqual(profile.role, "planner")
        self.assertEqual(profile.name, "planner-model")

    def test_executor_role_selected_correctly(self) -> None:
        registry = _build_registry()
        router = ModelRouter(registry=registry, limiter=RuntimeLimiter())
        profile = router.route("debug")
        self.assertEqual(profile.role, "executor")
        self.assertEqual(profile.name, "executor-model")

    def test_unknown_task_defaults_to_executor(self) -> None:
        registry = _build_registry()
        router = ModelRouter(registry=registry, limiter=RuntimeLimiter())
        profile = router.route("unmapped_task")
        self.assertEqual(profile.role, "executor")
        self.assertEqual(profile.name, "executor-model")

    def test_runtime_limiter_blocks_concurrent_acquire(self) -> None:
        limiter = RuntimeLimiter()
        limiter.acquire()

        acquired_second = threading.Event()

        def _second_acquire() -> None:
            limiter.acquire()
            acquired_second.set()
            limiter.release()

        worker = threading.Thread(target=_second_acquire)
        worker.start()

        time.sleep(0.05)
        self.assertFalse(acquired_second.is_set())

        limiter.release()
        worker.join(timeout=1.0)
        self.assertTrue(acquired_second.is_set())

    def test_flow_uses_correct_backend(self) -> None:
        registry = _build_registry()
        router = ModelRouter(registry=registry, limiter=RuntimeLimiter())
        planner_backend = FakeBackend("planner-result")
        executor_backend = FakeBackend("executor-result")
        flow = PlannerExecutorFlow(
            router=router,
            planner_backend=planner_backend,
            executor_backend=executor_backend,
        )

        planner_output = flow.run(task_type="architecture", prompt="plan this")
        executor_output = flow.run(task_type="debug", prompt="fix this")

        self.assertEqual(planner_output, "planner-result")
        self.assertEqual(executor_output, "executor-result")
        self.assertEqual(planner_backend.calls, 1)
        self.assertEqual(executor_backend.calls, 1)
        self.assertEqual(planner_backend.last_prompt, "plan this")
        self.assertEqual(executor_backend.last_prompt, "fix this")


if __name__ == "__main__":
    unittest.main()
