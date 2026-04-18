from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from config import settings
from storage import StepRecord


class PlannerMode(str, Enum):
    ECHO = "echo"
    LLM = "llm"


class AgentState(BaseModel):
    run_id: str
    task: str
    step_number: int = 1
    history: list[StepRecord] = Field(default_factory=list)
    shared_context: dict[int, Any] = Field(default_factory=dict)
    retries: int = 0
    replans: int = 0
    status: str = "running"


class Planner:
    """Deterministic planner for local tool actions."""

    def __init__(self) -> None:
        self.mode = PlannerMode(settings.planner_mode)

    def plan(self, state: AgentState) -> dict[str, object]:
        if self.mode is PlannerMode.LLM:
            raise NotImplementedError("LLM planner not yet implemented")
        task_segment = self._task_segments(state.task)[state.step_number - 1]
        return self._build_action(task_segment, state.step_number, is_replan=False)

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, object]:
        if self.mode is PlannerMode.LLM:
            raise NotImplementedError("LLM planner not yet implemented")
        task_segment = self._task_segments(state.task)[state.step_number - 1]
        action = self._build_action(task_segment, state.step_number, is_replan=True)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        action["parameters"] = self._variant_parameters(
            str(action["tool_name"]),
            dict(action["parameters"]),
            state.step_number,
        )
        return action

    def has_more_steps(self, state: AgentState) -> bool:
        return state.step_number < len(self._task_segments(state.task))

    @staticmethod
    def _task_segments(task: str) -> list[str]:
        segments = [
            segment.strip()
            for segment in re.split(r"\bthen\b|\band\b", task, flags=re.IGNORECASE)
            if segment.strip()
        ]
        return segments or [task]

    def _build_action(
        self,
        task_segment: str,
        step_number: int,
        is_replan: bool,
    ) -> dict[str, object]:
        normalized = task_segment.casefold()
        reason_prefix = "Replanned action" if is_replan else "Planned action"

        if "read" in normalized:
            return {
                "tool_name": "read_file",
                "parameters": {"path": "sample.txt"},
                "reason": f"{reason_prefix}: read sample text file",
                "step_number": step_number,
            }
        if "write" in normalized:
            return {
                "tool_name": "write_file",
                "parameters": {"path": "out.txt", "content": "task result"},
                "reason": f"{reason_prefix}: write task result to workspace",
                "step_number": step_number,
            }
        if "list" in normalized:
            return {
                "tool_name": "list_files",
                "parameters": {"path": "."},
                "reason": f"{reason_prefix}: list workspace files",
                "step_number": step_number,
            }
        if "http" in normalized or "get" in normalized:
            return {
                "tool_name": "http_get",
                "parameters": {"url": "https://example.com"},
                "reason": f"{reason_prefix}: fetch a stable example URL",
                "step_number": step_number,
            }
        if "csv" in normalized:
            return {
                "tool_name": "parse_csv",
                "parameters": {"path": "sample.csv"},
                "reason": f"{reason_prefix}: parse workspace CSV data",
                "step_number": step_number,
            }
        return {
            "tool_name": "list_files",
            "parameters": {"path": "."},
            "reason": f"{reason_prefix}: default to listing workspace files",
            "step_number": step_number,
        }

    def _variant_parameters(
        self,
        tool_name: str,
        parameters: dict[str, object],
        step_number: int,
    ) -> dict[str, object]:
        if tool_name == "write_file":
            path = Path(str(parameters["path"]))
            variant_path = path.with_name(f"{path.stem}_{step_number}{path.suffix}")
            return {
                "path": variant_path.as_posix(),
                "content": f"{parameters['content']} {step_number}",
            }
        if tool_name == "http_get":
            separator = "&" if "?" in str(parameters["url"]) else "?"
            return {"url": f"{parameters['url']}{separator}step={step_number}"}
        if tool_name == "read_file":
            return {"path": str(parameters["path"])}
        if tool_name == "parse_csv":
            return {"path": str(parameters["path"])}
        return {"path": str(parameters.get("path", "."))}
