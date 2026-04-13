from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from logger import get_logger
from planner import AgentState
from tools import TOOL_REGISTRY

from friday.memory.retrieval import RetrievalEngine


class AdaptivePlanner:
    """Planner that remains deterministic but can use prior experience."""

    def __init__(self, retrieval: RetrievalEngine | None = None) -> None:
        self.retrieval = retrieval
        self.logger = get_logger("friday.planner")

    def plan(self, state: AgentState) -> dict[str, Any]:
        context = self._context_for_task(state.task)
        action = None
        if (
            state.step_number == 1
            and context["confidence"] > 0.7
            and context["recommended_tools"]
        ):
            preferred_tool = context["recommended_tools"][0]
            if preferred_tool in TOOL_REGISTRY:
                action = self._action_for_tool(
                    preferred_tool,
                    state.task,
                    state.step_number,
                    memory_guided=True,
                )
        if action is None:
            task_segment = self._task_segments(state.task)[state.step_number - 1]
            action = self._build_action(task_segment, state.step_number, is_replan=False)

        if context["known_pitfalls"]:
            pitfalls = "; ".join(context["known_pitfalls"][:3])
            action["reason"] = f"{action['reason']} | known pitfalls: {pitfalls}"
        return action

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        context = self._context_for_task(state.task)
        similar = context["similar_past_tasks"]
        memory_tool = None
        failure_text = failure_reason.lower()
        for episode_info in similar:
            lessons = [lesson.lower() for lesson in episode_info.get("lessons", [])]
            if any(failure_text in lesson for lesson in lessons):
                tools_used = episode_info.get("tools_used", [])
                if tools_used:
                    memory_tool = tools_used[0]
                    break
        if memory_tool and memory_tool in TOOL_REGISTRY:
            self.logger.info("memory-guided replan selected tool=%s", memory_tool)
            action = self._action_for_tool(memory_tool, state.task, state.step_number, memory_guided=True)
            action["reason"] = f"{action['reason']} after failure: {failure_reason}"
            return action

        self.logger.info("default replan selected for failure=%s", failure_reason)
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

    def get_confidence(self, task: str) -> float:
        return float(self._context_for_task(task)["confidence"])

    def _context_for_task(self, task: str) -> dict[str, Any]:
        if self.retrieval is None:
            return {
                "similar_past_tasks": [],
                "recommended_tools": [],
                "known_pitfalls": [],
                "estimated_steps": 0,
                "confidence": 0.0,
            }
        return self.retrieval.get_context_for_task(task)

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
    ) -> dict[str, Any]:
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

    def _action_for_tool(
        self,
        tool_name: str,
        task: str,
        step_number: int,
        memory_guided: bool,
    ) -> dict[str, Any]:
        defaults = {
            "read_file": {"path": "sample.txt"},
            "write_file": {"path": "out.txt", "content": "task result"},
            "list_files": {"path": "."},
            "http_get": {"url": "https://example.com"},
            "parse_csv": {"path": "sample.csv"},
        }
        parameters = defaults.get(tool_name, {"path": "."})
        reason_prefix = "memory-guided: similar task succeeded with this tool" if memory_guided else "planned action"
        return {
            "tool_name": tool_name,
            "parameters": parameters,
            "reason": f"{reason_prefix} for task '{task}'",
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
