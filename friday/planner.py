from __future__ import annotations

import json
import platform
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiworker.llm.ollama_backend import OllamaBackend
from aiworker.llm.model_router import ModelRole, ModelRouter
from config import cfg
from interpreter.engine import interpret
from memory.store import MEMORY_PATH, REFLECTIONS_PATH, _load_records, get_tool_scores, read_memory
from observability.logger import logger
from planner import AgentState
from tools import TOOL_REGISTRY

from friday.config import settings

if TYPE_CHECKING:
    from friday.memory.retrieval import RetrievalEngine


TOOL_SCHEMA = {
    "system_info": {
        "description": "Returns OS, CPU, memory, and platform information.",
        "required_arguments": {},
        "output_type": "dict",
    },
    "list_files": {
        "description": "Lists files in a directory.",
        "required_arguments": {"path": "string — directory path to list"},
        "output_type": "list",
    },
    "read_file": {
        "description": "Reads and returns the content of a file.",
        "required_arguments": {"path": "string — path to file, must not be empty"},
        "output_type": "text",
    },
    "web_search": {
        "description": "Searches the internet and returns structured results.",
        "required_arguments": {"query": "string — search query, must not be empty"},
        "output_type": "list",
    },
    "write_file": {
        "description": "Writes text content to a file at the specified path.",
        "required_arguments": {
            "path": "string — destination file path",
            "content": "string — text content to write",
        },
        "output_type": "dict",
    },
    "run_command": {
        "description": "Executes a shell command and returns stdout/stderr.",
        "required_arguments": {
            "command": "string — shell command to run",
        },
        "output_type": "dict",
    },
    "web_fetch": {
        "description": "Fetches a webpage and returns its cleaned text content.",
        "required_arguments": {
            "url": "string — full URL including http:// or https://",
        },
        "output_type": "dict",
    },
    "write_code": {
        "description": "Generates code using the LLM and writes it to a file.",
        "required_arguments": {
            "filename": "string — output file path",
            "language": "string — programming language (python, js, etc.)",
            "description": "string — what the code should do",
        },
        "output_type": "dict",
    },
    "execute_python": {
        "description": "Executes a Python code string in an isolated subprocess.",
        "required_arguments": {
            "code": "string — Python source code to execute",
        },
        "output_type": "dict",
    },
    "execute_python_file": {
        "description": "Executes a Python file in a subprocess.",
        "required_arguments": {
            "path": "string — path to a Python file",
        },
        "output_type": "dict",
    },
    "lint_file": {
        "description": "Runs a linter or syntax checker against a file.",
        "required_arguments": {
            "path": "string — path to the file to lint",
        },
        "output_type": "dict",
    },
    "patch_file": {
        "description": "Replaces one exact string occurrence in a file.",
        "required_arguments": {
            "path": "string — path to the file to patch",
            "old": "string — exact text to replace",
            "new": "string — replacement text",
        },
        "output_type": "dict",
    },
    "summarize_file": {
        "description": "Summarizes a file with the LLM.",
        "required_arguments": {
            "path": "string — path to the file to summarize",
        },
        "output_type": "dict",
    },
    "diff_files": {
        "description": "Computes a unified diff between two files.",
        "required_arguments": {
            "path_a": "string — first file path",
            "path_b": "string — second file path",
        },
        "output_type": "dict",
    },
    "create_directory": {
        "description": "Creates a directory if it does not already exist.",
        "required_arguments": {
            "path": "string — directory path to create",
        },
        "output_type": "dict",
    },
    "delete_file": {
        "description": "Moves a file into .trash instead of deleting it permanently.",
        "required_arguments": {
            "path": "string — file path to move to trash",
        },
        "output_type": "dict",
    },
}

SAFE_FALLBACK = {"tool": "list_files", "arguments": {"path": "."}, "confidence": 1.0}
KEYWORD_TOOL_MAP = [
    (["lint", "ruff", "pyflakes"], "lint_file"),
    (["summarize", "summary"], "summarize_file"),
    (["diff", "compare"], "diff_files"),
    (["create directory", "make directory", "mkdir"], "create_directory"),
    (["delete", "remove", "trash"], "delete_file"),
    (["run python code", "execute python code", "python code:"], "execute_python"),
    (["python file", "execute python file", "run python file"], "execute_python_file"),
    (["write code", "generate code", "python hello world", "python script"], "write_code"),
    (["read", "open", "show", "cat", "print", "load"], "read_file"),
    (["list", "ls", "dir", "files", "directory", "folder"], "list_files"),
    (["search", "find", "google", "look up", "lookup", "web"], "web_search"),
    (["system", "info", "cpu", "memory", "os", "platform"], "system_info"),
    (["write", "save", "create", "output", "generate"], "write_file"),
    (["run", "execute", "shell", "command", "bash", "cmd"], "run_command"),
    (["fetch", "get", "download", "url", "http", "page"], "web_fetch"),
]
CONFIDENCE_THRESHOLD = float(cfg.get("confidence_threshold", 0.6))
ACTION_PREFIXES = (
    "list",
    "read",
    "summarize",
    "search",
    "write",
    "execute",
    "run",
    "lint",
    "diff",
    "create",
    "delete",
    "explore",
    "analyze",
)


def _fallback(reason: str) -> None:
    logger.log("FALLBACK", "reason", reason)


def strip_json_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    if cleaned.lower().startswith("json\n"):
        cleaned = cleaned[5:].strip()
    return cleaned


def _sanitize(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", text)[:500]


def _keyword_match(task_lower: str, keywords: list[str]) -> bool:
    for keyword in keywords:
        if re.search(r"\b" + re.escape(keyword) + r"\b", task_lower):
            return True
    return False


def _extract_path_tokens(task: str) -> list[str]:
    pattern = r'["\']?([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+|[A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+)["\']?'
    tokens: list[str] = []
    for match in re.finditer(pattern, task):
        candidate = match.group(1).strip("\"'`,")
        if candidate and candidate not in tokens:
            tokens.append(candidate)
    return tokens


def _extract_directory_path(task: str) -> str | None:
    lowered = task.lower()
    if "current directory" in lowered:
        return "."
    match = re.search(r"\bin (?:the )?([A-Za-z0-9_./-]+) directory\b", lowered)
    if match:
        return match.group(1).strip("\"'`,")
    return None


def _find_entry_point_path() -> str | None:
    candidates = ("runner.py", "main.py", "app.py", "friday_runner.py")
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _extract_python_code(task: str) -> str:
    stripped = task.strip()
    match = re.search(r"(?:execute|run)\s+python\s+code\s*:?\s*(.+)$", stripped, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return stripped


def _normalize_segment_text(segment: str) -> str:
    cleaned = re.sub(r"^\s*(?:[-*]|\d+[\).:])\s*", "", segment)
    return cleaned.strip(" ,.")


def _resolve_segment(segment: str, previous_file: str | None = None) -> tuple[str, str | None]:
    cleaned = _normalize_segment_text(segment)
    lowered = cleaned.lower()
    path_tokens = _extract_path_tokens(cleaned)
    file_target = path_tokens[0] if path_tokens else previous_file
    if "main entry point" in lowered or "entry point" in lowered:
        entry_point = _find_entry_point_path()
        if entry_point:
            return f"read {entry_point}", entry_point
    if lowered.startswith(("summarize", "summary")) and ("what it does" in lowered or "it does" in lowered):
        if previous_file:
            return f"summarize {previous_file}", previous_file
        entry_point = _find_entry_point_path()
        if entry_point:
            return f"summarize {entry_point}", entry_point
    if path_tokens:
        return cleaned, path_tokens[0]
    return cleaned, file_target


def _split_task_segments(task: str) -> list[str]:
    text = task.strip()
    if not text:
        return [task]
    text = re.sub(r"\s*\n\s*", " ", text)
    segments = [_normalize_segment_text(part) for part in re.split(r"\bthen\b", text, flags=re.IGNORECASE) if part.strip(" ,.")]
    final_segments: list[str] = []
    for segment in segments:
        parts = [
            _normalize_segment_text(part)
            for part in re.split(r",|\band\b", segment, flags=re.IGNORECASE)
            if part.strip(" ,.")
        ]
        if len(parts) <= 1:
            final_segments.append(segment)
            continue
        if all(part.lower().startswith(ACTION_PREFIXES) for part in parts):
            final_segments.extend(parts)
        else:
            final_segments.append(segment)
    return final_segments or [task]


def _fallback_plan(task: str) -> list[dict[str, Any]]:
    raw_segments = _split_task_segments(task)
    steps: list[dict[str, Any]] = []
    previous_file: str | None = None
    for index, raw_segment in enumerate(raw_segments, start=1):
        resolved_segment, previous_file = _resolve_segment(raw_segment, previous_file)
        steps.append({"step": index, "task": resolved_segment or task})
    return steps or [{"step": 1, "task": task}]


def load_reflection_hints(task: str) -> str:
    try:
        lowered = task.lower()
        reflections = [
            item
            for item in json.loads(REFLECTIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(item, dict) and lowered in str(item.get("task", "")).lower()
        ]
        hints = []
        for reflection in reflections[-2:]:
            hints.append(
                "Past reflection: prefer "
                + str(reflection.get("success_pattern", "unknown"))
                + ". Improvement: "
                + str(reflection.get("improvement", "unknown"))
            )
        return "\n".join(hints)
    except Exception:
        return ""


def compress_context(working_memory: dict[str, Any], max_chars: int = 800) -> dict[str, Any]:
    result = dict(working_memory)
    summary = str(result.get("last_result_summary", ""))
    if len(summary) > max_chars - 200:
        summary = summary[: max_chars - 200] + "...[compressed]"
        result["last_result_summary"] = summary
    current_total = len(json.dumps(result, default=str))
    if current_total > max_chars:
        last_tool = str(result.get("last_tool", ""))
        overflow = current_total - max_chars
        if last_tool and overflow > 0:
            clipped = max(0, len(last_tool) - overflow - 12)
            result["last_tool"] = last_tool[:clipped] + "...[compressed]" if clipped else "...[compressed]"
    return result


def calibrate_threshold() -> float:
    try:
        records = _load_records(MEMORY_PATH)[-10:]
        if not records:
            return float(cfg.get("confidence_threshold", 0.6))
        avg = sum(float(record.get("score", 0.0)) for record in records) / len(records)
        if avg > 0.8:
            return 0.5
        if avg < 0.6:
            return 0.75
        return float(cfg.get("confidence_threshold", 0.6))
    except Exception:
        return float(cfg.get("confidence_threshold", 0.6))


def _system_info(include_environment: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine() or "unknown",
    }
    if include_environment:
        data["executable"] = sys.executable
    return data


def _default_args(tool: str, task: str) -> dict[str, Any]:
    tokens = task.strip().split()
    last_token = _normalize_segment_text(tokens[-1].strip("\"'`")) if tokens else ""
    path_tokens = _extract_path_tokens(task)
    if tool == "read_file":
        if "entry point" in task.lower():
            entry_point = _find_entry_point_path()
            if entry_point:
                return {"path": entry_point}
        if path_tokens:
            return {"path": path_tokens[0]}
        return {"path": ""}
    if tool == "list_files":
        directory = _extract_directory_path(task)
        return {"path": directory or "."}
    if tool == "web_search":
        skip = {"search", "find", "google", "look", "lookup", "web", "up"}
        query = " ".join(token for token in tokens if token.lower() not in skip).strip()
        if query.lower().startswith("for "):
            query = query[4:]
        return {"query": query or task}
    if tool == "web_fetch":
        for token in tokens:
            if token.startswith("http://") or token.startswith("https://"):
                return {"url": token}
        return {"url": ""}
    if tool == "run_command":
        skip = {"run", "execute", "shell", "command", "bash", "cmd"}
        command = " ".join(token for token in tokens if token.lower() not in skip)
        return {"command": command}
    if tool == "write_file":
        return {"path": last_token, "content": ""}
    if tool == "write_code":
        filename = next((token for token in path_tokens if token.endswith((".py", ".js", ".ts", ".sh", ".go", ".rs", ".java", ".c", ".cpp", ".rb", ".yaml", ".json"))), last_token)
        language = "python" if filename.endswith(".py") or "python" in task.lower() else "text"
        description = task
        if filename in description:
            description = description.replace(filename, "").strip()
        return {"filename": filename, "language": language, "description": description}
    if tool == "execute_python":
        return {"code": _extract_python_code(task)}
    if tool == "execute_python_file":
        path = next((token for token in path_tokens if token.endswith(".py")), "")
        return {"path": path}
    if tool == "lint_file":
        if "entry point" in task.lower():
            entry_point = _find_entry_point_path()
            if entry_point:
                return {"path": entry_point}
        return {"path": path_tokens[0] if path_tokens else ""}
    if tool == "patch_file":
        return {"path": path_tokens[0] if path_tokens else last_token, "old": "", "new": ""}
    if tool == "summarize_file":
        if "entry point" in task.lower():
            entry_point = _find_entry_point_path()
            if entry_point:
                return {"path": entry_point}
        return {"path": path_tokens[0] if path_tokens else ""}
    if tool == "diff_files":
        first = path_tokens[0] if path_tokens else ""
        second = path_tokens[1] if len(path_tokens) > 1 else ""
        return {"path_a": first, "path_b": second}
    if tool == "create_directory":
        return {"path": path_tokens[0] if path_tokens else last_token}
    if tool == "delete_file":
        return {"path": path_tokens[0] if path_tokens else last_token}
    return {}


TOOL_REGISTRY.setdefault("system_info", _system_info)


class Planner:
    def __init__(self, retrieval: RetrievalEngine | None = None) -> None:
        self.retrieval = retrieval
        self.router = ModelRouter()
        backend = OllamaBackend(
            str(cfg.get("model_name", "llama3:8b")),
            timeout=max(1, int(settings.http_timeout)),
            max_retries=0,
        )
        self.router._planner_backend = backend
        self.router._coder_backend = backend
        self._plan_cache: dict[str, list[dict[str, Any]]] = {}

    def plan(
        self,
        task: str | AgentState,
        memory_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        if isinstance(task, AgentState):
            return self._plan_state(task)
        resolved_memory = memory_context if isinstance(memory_context, dict) else read_memory(task)
        return self._plan_task(task, resolved_memory)

    def select_tool(self, task_segment: str, working_memory: dict[str, Any]) -> dict[str, Any]:
        working_memory = compress_context(working_memory)
        prompt = self._tool_selection_prompt(task_segment, working_memory)
        raw = self._generate(prompt)
        logger.log("PLANNER", "LLM_RAW", raw)
        if not raw.strip():
            tool_call = self._heuristic_fallback(task_segment)
        else:
            tool_call = self._parse_tool_call(raw)
            if tool_call is None:
                tool_call = self._heuristic_fallback(task_segment)
        threshold = calibrate_threshold()
        if float(tool_call["confidence"]) < threshold:
            tool_call = dict(SAFE_FALLBACK)
            logger.log("PLANNER", "CONFIDENCE_GATE", "triggered")
        logger.log("PLANNER", "TOOL_SELECTED", tool_call["tool"])
        logger.log("PLANNER", "ARGUMENTS", tool_call["arguments"])
        return tool_call

    def replan(
        self,
        step_task: str | AgentState,
        failed_tool: str,
        error_class: str = "tool_error",
        working_memory: dict[str, Any] = {},
        critic_history: list[dict[str, Any]] = [],
        *,
        suggested_tool: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(step_task, AgentState):
            state = step_task
            failure_reason = failed_tool
            steps = self._steps_for_task(state.task, read_memory(state.task))
            step_index = max(state.step_number - 1, 0)
            resolved_step_task = steps[min(step_index, len(steps) - 1)]["task"]
            working_memory = self._working_memory_for_state(state, resolved_step_task)
            tool_call = self._replan_tool_call(
                resolved_step_task,
                self._previous_tool_for_state(state),
                failure_reason,
                working_memory,
                suggested_tool=suggested_tool,
                critic_history=critic_history,
            )
            return self._action_from_tool_call(
                resolved_step_task,
                tool_call,
                state.step_number,
                failure_reason,
            )

        return self._replan_tool_call(
            str(step_task),
            failed_tool,
            error_class,
            working_memory,
            suggested_tool=suggested_tool,
            critic_history=critic_history,
        )

    def has_more_steps(self, state: AgentState) -> bool:
        steps = self._steps_for_task(state.task, read_memory(state.task))
        return state.step_number < len(steps)

    def get_confidence(self, task: str) -> float:
        memory_context = read_memory(task)
        if memory_context.get("best_tools"):
            return 0.9
        if memory_context.get("failed_tools"):
            return 0.4
        return 1.0

    def _heuristic_fallback(self, task_segment: str) -> dict[str, Any]:
        task_lower = task_segment.lower()
        for keywords, tool in KEYWORD_TOOL_MAP:
            if _keyword_match(task_lower, keywords):
                logger.log("FALLBACK", "reason", f"heuristic match: {tool}")
                return {
                    "tool": tool,
                    "arguments": _default_args(tool, task_segment),
                    "confidence": 1.0,
                }
        logger.log("FALLBACK", "reason", "no heuristic match, using SAFE_FALLBACK")
        return dict(SAFE_FALLBACK)

    def _plan_state(self, state: AgentState) -> dict[str, Any]:
        memory_context = read_memory(state.task)
        steps = self._steps_for_task(state.task, memory_context)
        step_index = min(max(state.step_number - 1, 0), len(steps) - 1)
        step_task = steps[step_index]["task"]
        tool_call = self.select_tool(step_task, self._working_memory_for_state(state, step_task))
        return self._action_from_tool_call(step_task, tool_call, state.step_number)

    def _plan_task(self, task: str, memory_context: dict[str, Any]) -> list[dict[str, Any]]:
        safe_task = _sanitize(task)
        tool_scores = get_tool_scores()
        hints = load_reflection_hints(task)
        prompt = (
            "system: You are a planning agent. You have access to these tools:\n"
            + json.dumps(TOOL_SCHEMA, indent=2)
            + "\nPast successful tools: "
            + str(memory_context.get("best_tools", []))
            + "\nPreviously failed tools: "
            + str(memory_context.get("failed_tools", []))
            + (
                "\nHistorical tool performance (avg critic score):\n"
                + json.dumps(tool_scores, indent=2)
                + "\nPrefer tools with higher scores."
                if tool_scores
                else ""
            )
            + ("\nLearned from past runs:\n" + hints if hints else "")
            + '\nReturn ONLY a JSON array of step objects.'
            + '\nEach object must have keys: "step" (int) and "task" (string).'
            + "\nMaximum 5 steps. No explanation. No markdown."
            + "\nuser: Task: "
            + safe_task
        )
        raw = self._generate(prompt)
        logger.log("PLANNER", "LLM_RAW", raw)
        parsed = self._parse_plan(raw, task)
        self._plan_cache[task] = parsed
        logger.log("PLANNER", "PLAN", parsed)
        return parsed

    def _replan_tool_call(
        self,
        step_task: str,
        failed_tool: str,
        error_class: str,
        working_memory: dict[str, Any],
        *,
        suggested_tool: str | None = None,
        critic_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        logger.log("PLANNER", "REPLAN", f"step_task={step_task} reason={error_class}")
        working_memory = compress_context(working_memory)
        prompt = self._tool_selection_prompt(
            step_task,
            working_memory,
            failed_tool=failed_tool,
            error_class=error_class,
            suggested_tool=suggested_tool,
            different_tool=True,
            critic_history=critic_history or [],
        )
        raw = self._generate(prompt)
        logger.log("PLANNER", "LLM_RAW", raw)
        if not raw.strip():
            tool_call = self._heuristic_fallback(step_task)
        else:
            tool_call = self._parse_tool_call(raw)
            if tool_call is None:
                tool_call = self._heuristic_fallback(step_task)
        threshold = calibrate_threshold()
        if tool_call["tool"] == failed_tool or float(tool_call["confidence"]) < threshold:
            if float(tool_call["confidence"]) < threshold:
                logger.log("PLANNER", "CONFIDENCE_GATE", "triggered")
            tool_call = self._heuristic_fallback(step_task)
            if tool_call["tool"] == failed_tool:
                tool_call = dict(SAFE_FALLBACK)
        logger.log("PLANNER", "TOOL_SELECTED", tool_call["tool"])
        logger.log("PLANNER", "ARGUMENTS", tool_call["arguments"])
        return tool_call

    def _tool_selection_prompt(
        self,
        task_segment: str,
        working_memory: dict[str, Any],
        *,
        failed_tool: str | None = None,
        error_class: str | None = None,
        suggested_tool: str | None = None,
        different_tool: bool = False,
        critic_history: list[dict[str, Any]] | None = None,
    ) -> str:
        safe_task_segment = _sanitize(task_segment)
        result_summary = self._safe_result_summary(working_memory.get("last_result_summary", "none"))
        system_prompt = (
            "You are a tool selection agent. Available tools:\n"
            + json.dumps(TOOL_SCHEMA, indent=2)
            + "\nCurrent context:\n"
            + "  last_tool: "
            + str(working_memory.get("last_tool", "none"))
            + "\n  last_result_summary: "
            + result_summary[:200]
            + "\n  current_goal: "
            + str(working_memory.get("current_goal", "none"))
            + "\nReturn ONLY a JSON object with exactly these keys:"
            + "\n  tool: string (tool name)"
            + "\n  arguments: dict (tool arguments)"
            + "\n  confidence: float between 0.0 and 1.0"
            + "\nNo explanation. No markdown. No extra keys."
        )
        user_prompt = "Step task: " + safe_task_segment
        if failed_tool is not None and error_class is not None:
            user_prompt = (
                'Previous tool "'
                + failed_tool
                + '" failed.'
                + "\nError class: "
                + error_class
                + "\nStep task: "
                + safe_task_segment
                + "\nSelect a DIFFERENT tool. Return same JSON format."
            )
        if suggested_tool:
            user_prompt += "\nSuggested tool: " + suggested_tool
        if different_tool:
            user_prompt += "\nReturn a different tool than the previous one."
        if critic_history:
            user_prompt += (
                "\nPrevious critic verdicts (most recent first):\n"
                + json.dumps(critic_history[-3:], indent=2)
                + "\nAvoid tools that scored below 0.5."
            )
        return "system: " + system_prompt + "\nuser: " + user_prompt

    def _steps_for_task(self, task: str, memory_context: dict[str, Any]) -> list[dict[str, Any]]:
        cached = self._plan_cache.get(task)
        if cached:
            return cached
        return self._plan_task(task, memory_context)

    def _parse_plan(self, raw: str, task: str) -> list[dict[str, Any]]:
        fallback_steps = _fallback_plan(task)
        stripped = strip_json_fences(raw)
        try:
            parsed = json.loads(stripped)
        except Exception:
            _fallback("invalid plan json")
            return fallback_steps
        if not isinstance(parsed, list):
            _fallback("plan not list")
            return fallback_steps
        steps: list[dict[str, Any]] = []
        previous_file: str | None = None
        for item in parsed:
            if not isinstance(item, dict):
                continue
            step = item.get("step")
            step_task = item.get("task")
            if isinstance(step, int) and isinstance(step_task, str):
                resolved_task, previous_file = _resolve_segment(step_task, previous_file)
                steps.append({"step": step, "task": resolved_task.strip()})
        if not steps:
            _fallback("plan validation failed")
            return fallback_steps
        if len(fallback_steps) > len(steps):
            _fallback("plan under-segmented")
            return fallback_steps
        return steps[:5]

    def _parse_tool_call(self, raw: str) -> dict[str, Any] | None:
        stripped = strip_json_fences(raw)
        try:
            parsed = json.loads(stripped)
        except Exception:
            _fallback("invalid tool json")
            return None
        if not isinstance(parsed, dict):
            _fallback("tool selection not dict")
            return None
        tool = parsed.get("tool")
        arguments = parsed.get("arguments")
        confidence = parsed.get("confidence")
        if not isinstance(tool, str) or tool not in TOOL_SCHEMA:
            _fallback("invalid tool")
            return None
        if not isinstance(arguments, dict):
            _fallback("invalid arguments")
            return None
        if not isinstance(confidence, (int, float)):
            _fallback("invalid confidence")
            return None
        clamped_confidence = max(0.0, min(float(confidence), 1.0))
        return {"tool": tool, "arguments": arguments, "confidence": clamped_confidence}

    def _action_from_tool_call(
        self,
        step_task: str,
        tool_call: dict[str, Any],
        step_number: int,
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        arguments = self._compat_arguments(tool_call["tool"], tool_call["arguments"])
        reason = f"planned step {step_number}: {step_task}"
        if failure_reason:
            reason = f"{reason}; failure={failure_reason}"
        return {
            "tool_name": tool_call["tool"],
            "parameters": arguments,
            "reason": reason,
            "step_number": step_number,
        }

    @staticmethod
    def _compat_arguments(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "system_info":
            return {"include_environment": bool(arguments.get("include_environment", False))}
        if tool == "list_files":
            return {"path": str(arguments.get("path", "."))}
        if tool == "read_file":
            return {"path": str(arguments.get("path", "sample.txt"))}
        if tool == "web_search":
            return {"query": str(arguments.get("query", "workspace"))}
        if tool == "write_file":
            return {
                "path": str(arguments.get("path", "output.txt")),
                "content": str(arguments.get("content", "")),
            }
        if tool == "run_command":
            return {"command": str(arguments.get("command", ""))}
        if tool == "web_fetch":
            return {"url": str(arguments.get("url", ""))}
        if tool == "write_code":
            return {
                "filename": str(arguments.get("filename", "output.py")),
                "language": str(arguments.get("language", "python")),
                "description": str(arguments.get("description", "")),
            }
        if tool == "execute_python":
            return {"code": str(arguments.get("code", ""))}
        if tool == "execute_python_file":
            return {"path": str(arguments.get("path", ""))}
        if tool == "lint_file":
            return {"path": str(arguments.get("path", ""))}
        if tool == "patch_file":
            return {
                "path": str(arguments.get("path", "")),
                "old": str(arguments.get("old", "")),
                "new": str(arguments.get("new", "")),
            }
        if tool == "summarize_file":
            return {"path": str(arguments.get("path", ""))}
        if tool == "diff_files":
            return {
                "path_a": str(arguments.get("path_a", "")),
                "path_b": str(arguments.get("path_b", "")),
            }
        if tool == "create_directory":
            return {"path": str(arguments.get("path", ""))}
        if tool == "delete_file":
            return {"path": str(arguments.get("path", ""))}
        return {"path": "."}

    def _working_memory_for_state(self, state: AgentState, step_task: str) -> dict[str, Any]:
        last_tool = self._previous_tool_for_state(state)
        raw_last_output = state.shared_context.get(state.step_number - 1)
        interpreted = interpret(raw_last_output)
        return {
            "last_tool": last_tool,
            "last_result_summary": interpreted["summary"],
            "current_goal": step_task,
        }

    @staticmethod
    def _previous_tool_for_state(state: AgentState) -> str:
        if state.history:
            return state.history[-1].tool_name
        return "none"

    @staticmethod
    def _safe_result_summary(value: Any) -> str:
        if isinstance(value, dict) and {"summary", "type", "key_info"} <= set(value.keys()):
            return str(value.get("summary", "none"))
        if isinstance(value, str):
            return value
        return interpret(value)["summary"]

    def _generate(self, prompt: str) -> str:
        try:
            return str(self._call_llm(prompt)).strip()
        except Exception as exc:
            _fallback(str(exc))
            return ""

    def _call_llm(self, prompt: str, system: str = "") -> str:
        return self._llm(prompt, system=system)

    def _llm(self, prompt: str, system: str = "") -> str:
        _ = system
        return str(self.router.generate(ModelRole.PLANNER, prompt))

    def decompose_goal(self, goal: str) -> list[str]:
        prompt_system = (
            "You are a goal decomposition agent.\n"
            "Break the following high-level goal into sequential sub-goals.\n"
            "Each sub-goal must be achievable in a single agent run.\n"
            "Return ONLY a JSON array of strings. No explanation.\n"
            "Maximum 5 sub-goals."
        )
        prompt_user = "Goal: " + _sanitize(goal)
        try:
            raw = self._call_llm(prompt_user, system=prompt_system)
            raw = strip_json_fences(raw)
            sub_goals = json.loads(raw)
            if isinstance(sub_goals, list):
                resolved_goals: list[str] = []
                previous_file: str | None = None
                for item in sub_goals[:5]:
                    resolved_goal, previous_file = _resolve_segment(str(item), previous_file)
                    resolved_goals.append(resolved_goal)
                fallback_goals = _fallback_plan(goal)
                if len(fallback_goals) > len(resolved_goals):
                    return [str(item["task"]) for item in fallback_goals]
                return resolved_goals
        except Exception:
            pass
        fallback_parts = [
            part.strip(" .")
            for part in re.split(r"\bthen\b|,|\band\b", goal, flags=re.IGNORECASE)
            if part.strip(" .")
        ]
        if len(fallback_parts) > 1:
            fallback_parts = [
                part
                for part in fallback_parts
                if part.lower() not in {"analyze the project", "analyze project"}
            ] or fallback_parts
        if fallback_parts:
            resolved_parts: list[str] = []
            previous_file: str | None = None
            for part in fallback_parts[:5]:
                resolved_part, previous_file = _resolve_segment(part, previous_file)
                resolved_parts.append(resolved_part)
            return resolved_parts
        return [goal]


class AdaptivePlanner(Planner):
    pass
