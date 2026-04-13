"""Two-model deterministic orchestration loop."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Dict, List

from aiworker.execution.sandbox_runner import DefaultSandboxRunner, SandboxRunner
from aiworker.llm.coder_adapter import CoderAdapter
from aiworker.llm.model_router import ModelRole, ModelRouter
from aiworker.llm.planner_adapter import PlannerAdapter, TaskSpec
from aiworker.safety.patch_validator import validate_patch


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate."""
    if not text:
        return 0
    return int(math.ceil(len(text) / 4.0))


def _split_task_for_budget(task: TaskSpec, goal: str, token_cap: int = 3000) -> List[TaskSpec]:
    base_prompt = (
        f"GOAL:{goal}\nTASK:{task.type}:{task.description}\nFILE:{task.file}\nMAX_LINES:{task.max_lines}"
    )
    if estimate_tokens(base_prompt) <= token_cap:
        return [task]

    overhead = estimate_tokens(f"GOAL:{goal}\nFILE:{task.file}\nMAX_LINES:{task.max_lines}\nTASK:{task.type}:")
    available_tokens = max(50, token_cap - overhead)
    chunk_chars = max(200, available_tokens * 4)

    chunks: List[TaskSpec] = []
    text = task.description
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        chunks.append(replace(task, description=text[start:end]))
        start = end
    return chunks or [task]


class OrchestratedLoop:
    """Planner -> coder -> validator -> sandbox loop with bounded retries."""

    def __init__(
        self,
        *,
        planner: PlannerAdapter,
        coder: CoderAdapter,
        sandbox_runner: SandboxRunner | None = None,
        max_retries: int = 2,
        risk_threshold: float = 0.8,
        consecutive_failure_limit: int = 3,
    ) -> None:
        self._planner = planner
        self._coder = coder
        self._sandbox_runner = sandbox_runner or DefaultSandboxRunner()
        self._max_retries = max_retries
        self._risk_threshold = risk_threshold
        self._consecutive_failure_limit = consecutive_failure_limit

    def run(self, *, goal: str, workspace_path: str) -> Dict[str, int | bool]:
        completed_tasks = 0
        failed_tasks = 0
        consecutive_failures = 0

        tasks = self._planner.generate(goal)

        for task in tasks:
            task_success = False
            chunked_tasks = _split_task_for_budget(task, goal)

            for chunked_task in chunked_tasks:
                for _ in range(self._max_retries + 1):
                    try:
                        diff = self._coder.generate(chunked_task, goal)
                    except ValueError:
                        diff = None

                    if diff is None:
                        continue

                    if self._coder.last_risk_score > self._risk_threshold:
                        return {
                            "success": False,
                            "completed_tasks": completed_tasks,
                            "failed_tasks": failed_tasks + 1,
                        }

                    validation = validate_patch(
                        diff,
                        allowed_file=chunked_task.file,
                        max_lines=chunked_task.max_lines,
                    )
                    if not validation.valid:
                        continue

                    apply_result = self._sandbox_runner.apply_patch(
                        workspace_path=workspace_path,
                        patch_content=diff,
                    )
                    if apply_result.success:
                        task_success = True
                        break
                if task_success:
                    break

            if task_success:
                completed_tasks += 1
                consecutive_failures = 0
                continue

            failed_tasks += 1
            consecutive_failures += 1
            if consecutive_failures >= self._consecutive_failure_limit:
                return {
                    "success": False,
                    "completed_tasks": completed_tasks,
                    "failed_tasks": failed_tasks,
                }

        return {
            "success": failed_tasks == 0,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
        }


class _RouterBackend:
    """Backend facade that forwards prompts through ModelRouter roles."""

    def __init__(self, router: ModelRouter, role: ModelRole) -> None:
        self._router = router
        self._role = role

    def generate(self, prompt: str) -> str:
        return self._router.generate(self._role, prompt)


def build_orchestrated_loop(
    *,
    model_router: ModelRouter,
    sandbox_runner: SandboxRunner | None = None,
    max_retries: int = 2,
    risk_threshold: float = 0.8,
    consecutive_failure_limit: int = 3,
) -> OrchestratedLoop:
    """Build loop wired to a role-based model router."""
    planner = PlannerAdapter(_RouterBackend(model_router, ModelRole.PLANNER))
    coder = CoderAdapter(_RouterBackend(model_router, ModelRole.CODER))
    return OrchestratedLoop(
        planner=planner,
        coder=coder,
        sandbox_runner=sandbox_runner,
        max_retries=max_retries,
        risk_threshold=risk_threshold,
        consecutive_failure_limit=consecutive_failure_limit,
    )


__all__ = ["OrchestratedLoop", "build_orchestrated_loop", "estimate_tokens"]
