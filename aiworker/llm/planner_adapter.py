"""Planner adapter for strict JSON task decomposition."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Protocol


TaskType = Literal["create", "modify"]


@dataclass(frozen=True)
class TaskSpec:
    """Single atomic implementation task."""

    file: str
    type: TaskType
    description: str
    max_lines: int


class GenerationBackend(Protocol):
    """Minimal backend protocol."""

    def generate(self, prompt: str) -> str:
        """Return a raw response string."""


def _ensure_json_only(raw: str) -> dict[str, object]:
    text = raw.strip()
    if not text:
        raise ValueError("Planner returned empty response")
    if "```" in text:
        raise ValueError("Planner response contains markdown")
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError("Planner response must be JSON object only")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Planner response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Planner response root must be object")
    return parsed


def _validate_task(task: object) -> TaskSpec:
    if not isinstance(task, dict):
        raise ValueError("Each task must be an object")

    file_path = task.get("file")
    task_type = task.get("type")
    description = task.get("description")
    max_lines = task.get("max_lines")

    if not isinstance(file_path, str) or not file_path.startswith("aiworker/"):
        raise ValueError("Task file must be a string starting with 'aiworker/'")
    if task_type not in ("create", "modify"):
        raise ValueError("Task type must be 'create' or 'modify'")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Task description must be non-empty string")
    if not isinstance(max_lines, int):
        raise ValueError("Task max_lines must be an integer")
    if max_lines < 1 or max_lines > 200:
        raise ValueError("Task max_lines must be in range [1, 200]")

    return TaskSpec(
        file=file_path,
        type=task_type,
        description=description.strip(),
        max_lines=max_lines,
    )


class PlannerAdapter:
    """Planner model adapter with strict JSON schema validation."""

    def __init__(self, backend: GenerationBackend) -> None:
        self._backend = backend

    def _build_prompt(self, goal: str) -> str:
        return (
            "You are a planning model.\n"
            "Return STRICT JSON ONLY. No markdown. No prose.\n"
            "GOAL:\n"
            f"{goal}\n\n"
            "RULES:\n"
            "- Output one JSON object with key: tasks\n"
            "- tasks must be a non-empty array\n"
            "- type must be create or modify\n"
            "- max_lines must be integer <= 200\n"
            "- file must be inside aiworker/\n\n"
            "FILE RESTRICTIONS:\n"
            "- file must start with aiworker/\n"
            "- exactly one file per task\n\n"
            "MAX_LINES:\n"
            "- 200\n\n"
            "JSON SCHEMA:\n"
            '{"tasks":[{"file":"aiworker/path.py","type":"create","description":"...",'
            '"max_lines":120}]}'
        )

    def generate(self, goal: str) -> list[TaskSpec]:
        """Generate and validate task list from goal."""
        raw = self._backend.generate(self._build_prompt(goal))
        payload = _ensure_json_only(raw)
        tasks_raw = payload.get("tasks")
        if not isinstance(tasks_raw, list) or len(tasks_raw) == 0:
            raise ValueError("Planner payload must include non-empty tasks list")

        tasks = [_validate_task(item) for item in tasks_raw]
        if not tasks:
            raise ValueError("Planner returned empty task list")
        return tasks


__all__ = ["GenerationBackend", "PlannerAdapter", "TaskSpec", "TaskType"]
