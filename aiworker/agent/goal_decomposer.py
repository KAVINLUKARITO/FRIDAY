"""# FILE: aiworker/agent/goal_decomposer.py — Goal decomposition and sequential execution helpers."""

from __future__ import annotations

import json
from typing import Any, Callable


class GoalDecomposer:
    """Break a large goal into atomic sub-tasks."""

    def __init__(self, backend: Any, max_subtasks: int = 7) -> None:
        self._backend = backend
        self._max = max_subtasks

    def decompose(self, goal: str, allowed_files: tuple[str, ...]) -> list[str]:
        prompt = "\n".join(
            [
                "Break the engineering goal into atomic sub-tasks.",
                "Return ONLY a JSON array of strings.",
                "Each sub-task must be achievable by modifying 1-3 Python files.",
                f"Allowed files: {', '.join(allowed_files)}",
                f"Maximum subtasks: {self._max}",
                f"Goal: {goal}",
            ]
        )

        try:
            if self._backend is None or not hasattr(self._backend, "generate"):
                raise ValueError("LLM backend unavailable")
            raw = self._backend.generate(prompt)
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise ValueError("Expected a list")
            subtasks = [str(item).strip() for item in payload]
            if not 1 <= len(subtasks) <= self._max:
                raise ValueError("Invalid list length")
            if any(not item for item in subtasks):
                raise ValueError("Empty sub-task")
            return subtasks
        except Exception:
            return self._fallback_decompose(goal)

    def _fallback_decompose(self, goal: str) -> list[str]:
        lower = goal.lower().strip()
        if lower.startswith("refactor "):
            target = goal[len("refactor ") :].strip() or goal
            return [
                f"analyse {target}",
                f"identify targets in {target}",
                "apply refactoring",
                "run tests",
            ]
        if lower.startswith("add "):
            target = goal[len("add ") :].strip() or goal
            return [
                f"design {target} interface",
                f"implement {target}",
                f"write tests for {target}",
            ]
        if lower.startswith("fix "):
            target = goal[len("fix ") :].strip() or goal
            return [
                f"reproduce {target}",
                "identify root cause",
                "apply fix",
                "verify tests pass",
            ]
        return [goal]

    def execute_sequence(
        self,
        sub_goals: list[str],
        controller_factory: Callable[..., Any],
        stop_on_failure: bool = True,
    ) -> list[Any]:
        results: list[Any] = []
        for sub_goal in sub_goals:
            controller = controller_factory(goal=sub_goal)
            result = controller.run()
            results.append(result)
            if stop_on_failure and not getattr(result, "success", False):
                break
        return results
