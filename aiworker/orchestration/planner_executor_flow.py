"""Planner/executor orchestration flow with single-runtime enforcement."""

from __future__ import annotations

from typing import Protocol

from aiworker.llm.model_router import ModelRouter


class GenerationBackend(Protocol):
    """Backend protocol for deterministic prompt generation."""

    def generate(self, prompt: str) -> str:
        ...


class PlannerExecutorFlow:
    """Routes and executes a task on exactly one backend at a time."""

    def __init__(
        self,
        router: ModelRouter,
        planner_backend: GenerationBackend,
        executor_backend: GenerationBackend,
    ) -> None:
        self.router = router
        self.planner_backend = planner_backend
        self.executor_backend = executor_backend

    def run(self, task_type: str, prompt: str) -> str:
        profile = self.router.route(task_type)
        limiter = self.router.limiter
        limiter.acquire()
        try:
            if profile.role == "planner":
                return self.planner_backend.generate(prompt)
            return self.executor_backend.generate(prompt)
        finally:
            limiter.release()
