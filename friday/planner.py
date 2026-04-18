from __future__ import annotations

import platform
import re
import sys
from typing import Any

from aiworker.llm.ollama_backend import OllamaBackend
from aiworker.llm.model_router import ModelRole, ModelRouter
from logger import get_logger
from planner import AgentState
from tools import TOOL_REGISTRY

from friday.memory.retrieval import RetrievalEngine


def _system_info(include_environment: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine() or "unknown",
    }
    if include_environment:
        data["executable"] = sys.executable
    return data


TOOL_REGISTRY.setdefault("system_info", _system_info)


class AdaptivePlanner:
    """Planner that selects tools through the LLM planner router."""

    def __init__(self, retrieval: RetrievalEngine | None = None) -> None:
        self.retrieval = retrieval
        self.logger = get_logger("friday.planner")
        self.router = ModelRouter()
        backend = OllamaBackend("llama3:8b")
        self.router._planner_backend = backend
        self.router._coder_backend = backend

    def plan(self, state: AgentState) -> dict[str, Any]:
        task_segment = self._task_segments(state.task)[state.step_number - 1]
        previous_output = state.shared_context.get(state.step_number - 1)
        return self._build_action(
            task_segment,
            state.step_number,
            is_replan=False,
            previous_output=previous_output,
        )

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        task_segment = self._task_segments(state.task)[state.step_number - 1]
        previous_output = state.shared_context.get(state.step_number - 1)
        action = self._build_action(
            task_segment,
            state.step_number,
            is_replan=True,
            previous_output=previous_output,
            failure_reason=failure_reason,
        )
        action["parameters"] = self._variant_parameters(
            str(action["tool_name"]),
            dict(action["parameters"]),
            state.step_number,
        )
        return action

    def has_more_steps(self, state: AgentState) -> bool:
        return state.step_number < len(self._task_segments(state.task))

    def get_confidence(self, task: str) -> float:
        _ = task
        return 1.0

    def _context_for_task(self, task: str) -> dict[str, Any]:
        _ = task
        return {
            "similar_past_tasks": [],
            "recommended_tools": [],
            "known_pitfalls": [],
            "estimated_steps": 0,
            "confidence": 1.0,
        }

    @staticmethod
    def _task_segments(task: str) -> list[str]:
        segments = [
            segment.strip()
            for segment in re.split(r"\bthen\b|\band\b|,", task, flags=re.IGNORECASE)
            if segment.strip()
        ]
        return segments or [task]

    def _build_action(
        self,
        task_segment: str,
        step_number: int,
        is_replan: bool,
        previous_output: Any = None,
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        tool_name = self._select_tool(
            task_segment,
            previous_output=previous_output,
            failure_reason=failure_reason,
        )
        parameters = self._default_parameters(
            tool_name,
            task_segment,
            previous_output=previous_output,
        )
        reason_prefix = "Replanned action" if is_replan else "Planned action"
        reason = f"{reason_prefix}: use {tool_name} for task '{task_segment}'"
        if failure_reason:
            reason = f"{reason} after failure: {failure_reason}"
        return {
            "tool_name": tool_name,
            "parameters": parameters,
            "reason": reason,
            "step_number": step_number,
        }

    def _action_for_tool(
        self,
        tool_name: str,
        task: str,
        step_number: int,
        memory_guided: bool,
    ) -> dict[str, Any]:
        _ = memory_guided
        return {
            "tool_name": tool_name,
            "parameters": self._default_parameters(tool_name, task),
            "reason": f"planned action for task '{task}'",
            "step_number": step_number,
        }

    def _variant_parameters(
        self,
        tool_name: str,
        parameters: dict[str, object],
        step_number: int,
    ) -> dict[str, object]:
        _ = tool_name
        _ = step_number
        return parameters

    def _normalize_tool(self, raw: str) -> str:
        text = raw.strip().lower()

        # remove formatting noise
        text = text.replace("`", "").replace('"', "").replace("'", "")

        # extract valid tool only
        match = re.search(r"\b(system_info|list_files|read_file|web_search)\b", text)

        if match:
            return match.group(1)

        return "list_files"

    def _default_parameters(
        self,
        tool_name: str,
        task: str,
        previous_output: Any = None,
    ) -> dict[str, Any]:
        if tool_name == "system_info":
            return {"include_environment": False}
        if tool_name == "list_files":
            return {"path": "."}
        if tool_name == "read_file":
            resolved_path = self._path_from_task_or_context(task, previous_output)
            if resolved_path:
                return {"path": resolved_path}
            return {"path": "sample.txt"}
        if tool_name == "web_search":
            return {"query": re.sub(r"^(search|look up|find)\s+", "", task, flags=re.IGNORECASE).strip() or task}
        return {}

    @staticmethod
    def _path_from_task_or_context(task: str, previous_output: Any) -> str | None:
        task_match = re.search(r"read(?:\s+file)?\s+(.+)", task, flags=re.IGNORECASE)
        requested_path = task_match.group(1).strip(" .") if task_match else ""
        if requested_path:
            return requested_path

        candidates: list[str] = []
        if isinstance(previous_output, list):
            candidates = [item for item in previous_output if isinstance(item, str) and item.strip()]
        elif isinstance(previous_output, dict):
            values = previous_output.get("files")
            if isinstance(values, list):
                candidates = [item for item in values if isinstance(item, str) and item.strip()]
        elif isinstance(previous_output, str) and previous_output.strip():
            candidates = [line.strip() for line in previous_output.splitlines() if line.strip()]

        for candidate in candidates:
            if "." in candidate:
                return candidate
        return None

    @staticmethod
    def _keyword_fallback(task: str) -> str:
        normalized = task.casefold()
        if any(term in normalized for term in ("search", "look up", "find", "internet", "web")):
            return "web_search"
        if "system" in normalized or "platform" in normalized:
            return "system_info"
        if "read" in normalized:
            return "read_file"
        if "list" in normalized:
            return "list_files"
        return "list_files"

    def _select_tool(
        self,
        task: str,
        previous_output: Any = None,
        failure_reason: str | None = None,
    ) -> str:
        import signal

        if previous_output is not None:
            tool = self._keyword_fallback(task)
            print("[PLANNER FALLBACK TOOL]:", tool)
            return tool

        prompt = f"""
Task: {task}
Previous output: {previous_output if previous_output is not None else "none"}
Previous failure: {failure_reason if failure_reason else "none"}

Available tools:
- system_info
- list_files
- read_file
- web_search

Choose a better tool.
Return ONLY tool name.
"""

        def timeout_handler(signum: int, frame: Any) -> None:
            _ = signum
            _ = frame
            raise TimeoutError("LLM timeout")

        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(10)
            try:
                raw = self.router.generate(ModelRole.PLANNER, prompt)
            finally:
                signal.alarm(0)
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("empty LLM response")
        except TimeoutError:
            print("[PLANNER TIMEOUT] using fallback")
            tool = self._keyword_fallback(task)
            print("[PLANNER FALLBACK TOOL]:", tool)
            return tool
        except Exception as e:
            print(f"[LLM ERROR]: {e}")
            tool = self._keyword_fallback(task)
            print("[PLANNER FALLBACK TOOL]:", tool)
            return tool

        print(f"[LLM RAW]: {raw}")

        tool = self._normalize_tool(raw)
        if tool == "list_files":
            tool = self._keyword_fallback(task)
        print(f"[SELECTED TOOL]: {tool}")
        return tool
