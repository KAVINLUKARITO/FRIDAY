"""Runtime model router for planner/coder orchestration."""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol


class Backend(Protocol):
    """Minimal generation backend contract."""

    def generate(self, prompt: str) -> str:
        """Return model text for *prompt*."""


class ModelRole(Enum):
    """Explicit model roles."""

    PLANNER = "planner"
    CODER = "coder"


class ModelRouter:
    """Routes one generation call to exactly one backend."""

    def __init__(
        self,
        planner_backend: Backend | None = None,
        coder_backend: Backend | None = None,
        *,
        registry: Any | None = None,
        limiter: Any | None = None,
    ) -> None:
        self._planner_backend = planner_backend
        self._coder_backend = coder_backend
        self.registry = registry
        self.limiter = limiter

    def generate(self, role: ModelRole, prompt: str) -> str:
        """Generate text from the backend bound to *role*."""
        if self._planner_backend is None or self._coder_backend is None:
            raise ValueError("planner_backend and coder_backend must be configured")
        print(f"[MODEL ROUTER] Using model: {self._planner_backend.model_name}")
        if role is ModelRole.PLANNER:
            return self._planner_backend.generate(prompt)
        if role is ModelRole.CODER:
            return self._coder_backend.generate(prompt)
        raise ValueError(f"Invalid model role: {role!r}")

    def route(self, task_type: str) -> Any:
        """Legacy compatibility: map task type to registry profile."""
        if self.registry is None:
            raise ValueError("registry is not configured for route()")

        planner_tasks = {"architecture", "planning", "large_patch"}
        executor_tasks = {"extraction", "small_patch", "refactor", "debug"}
        if task_type in planner_tasks:
            return self.registry.get_by_role("planner")
        if task_type in executor_tasks:
            return self.registry.get_by_role("executor")
        return self.registry.get_by_role("executor")


__all__ = ["Backend", "ModelRole", "ModelRouter"]
