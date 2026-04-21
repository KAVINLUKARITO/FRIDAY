from __future__ import annotations

import copy
import concurrent.futures
import datetime
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import cfg
from config import settings as root_settings
from critic.evaluator import evaluate
from friday.planner import Planner, TOOL_SCHEMA, _fallback_plan
from interpreter.engine import interpret
from memory.store import read_memory, write_memory, write_reflection
from memory.skills import SkillLibrary
from observability.logger import logger
from tools import (
    create_directory,
    delete_file,
    diff_files,
    execute_python,
    execute_python_file,
    lint_file,
    list_files,
    patch_file,
    read_file,
    run_command,
    summarize_file,
    web_fetch,
    web_search,
    write_code,
    write_file,
)
from validator import ValidatedAction

try:
    from tools import system_info
except ImportError:
    from friday.planner import _system_info as system_info


MAX_RETRIES = int(cfg.get("max_retries", 1))
MAX_REPLANS = int(cfg.get("max_replans", 1))
TOOL_TIMEOUTS = {
    "system_info": 5,
    "list_files": 5,
    "read_file": 5,
    "write_file": 10,
    "run_command": int(cfg.get("run_command_timeout", 15)),
    "web_search": int(cfg.get("web_search_timeout", 12)),
    "web_fetch": int(cfg.get("web_fetch_timeout", 15)),
    "write_code": int(cfg.get("write_code_timeout", 60)),
    "execute_python": int(cfg.get("execute_python_timeout", 20)),
    "execute_python_file": 20,
    "lint_file": 15,
    "patch_file": 10,
    "summarize_file": 45,
    "diff_files": 10,
    "create_directory": 10,
    "delete_file": 10,
}


@dataclass
class ExecutionResult:
    success: bool
    output: Any
    error: str | None
    duration_seconds: float
    timed_out: bool


@dataclass
class AgentState:
    last_tool: str = ""
    last_result_summary: dict[str, Any] = field(default_factory=dict)
    current_goal: str = ""
    goal_achieved: bool = False
    goal_evidence: str = ""


class Executor:
    def __init__(self) -> None:
        self.planner = Planner()

    def run(self, task: str | ValidatedAction) -> dict[str, Any] | ExecutionResult:
        if isinstance(task, ValidatedAction):
            return self._run_validated_action(task)
        if not str(task).strip():
            return {
                "run_id": "",
                "task": str(task),
                "steps_completed": 0,
                "failures": [],
                "final_summary": {"summary": "no task provided", "type": "empty", "key_info": []},
                "goal_achieved": False,
                "goal_evidence": "no task provided",
                "suggested_next_task": None,
            }

        planner = self.planner
        skills = SkillLibrary()
        state = AgentState(current_goal=task)
        failures: list[dict[str, str]] = []
        all_results: list[dict[str, Any]] = []
        critic_history: list[dict[str, Any]] = []

        logger.begin_run(task)
        run_id = getattr(logger, "_run_id", "")
        try:
            memory_context = read_memory(task)
            skill = skills.find_skill(task)
            if skill and float(skill.get("avg_score", 0.0)) >= 0.8 and self._skill_is_applicable(skill, str(task)):
                logger.log("EXECUTOR", "SKILL_HIT", str(skill.get("name", "")))
                skills.increment_use(str(skill.get("name", "")))
                steps = [
                    {
                        "step": index,
                        "task": task,
                        "tool_call": {
                            "tool": str(step.get("tool", "list_files")),
                            "arguments": dict(step.get("arguments", {})),
                            "confidence": 1.0,
                        },
                    }
                    for index, step in enumerate(skill.get("steps", []), start=1)
                ]
            else:
                steps = planner.plan(task, memory_context)
            if not steps:
                steps = [{"step": 1, "task": task}]
                logger.log("PLANNER", "PLAN_FALLBACK", "empty plan replaced with single-step")
            logger.log("EXECUTOR", "PLAN", steps)
            logger.trace("PLAN", {"steps": steps})

            for step_index, step_obj in enumerate(steps, start=1):
                step_task = str(step_obj["task"])
                state.current_goal = step_task
                retry_count = 0
                replan_count = 0
                step_success = False
                tool_call: dict[str, Any] | None = dict(step_obj.get("tool_call", {})) if isinstance(step_obj.get("tool_call"), dict) else None

                while not step_success:
                    if retry_count > MAX_RETRIES and replan_count > MAX_REPLANS:
                        logger.log(
                            "EXECUTOR",
                            "STEP_FAILED",
                            {"step": step_task, "reason": "limits exhausted"},
                        )
                        failures.append({"step": step_task, "reason": "limits exhausted"})
                        logger.trace("STEP_FAILED", {"step": step_task, "reason": "limits exhausted"})
                        break
                    working_memory = {
                        "last_tool": state.last_tool,
                        "last_result_summary": json.dumps(state.last_result_summary)[:200],
                        "current_goal": state.current_goal,
                    }
                    if step_index > 1 and state.last_result_summary:
                        preview = str(state.last_result_summary.get("summary", ""))[:200]
                        logger.log("EXECUTOR", "CHAIN_INPUT", preview)
                    if tool_call is None:
                        tool_call = planner.select_tool(step_task, working_memory)
                    tool = str(tool_call["tool"])
                    arguments = dict(tool_call["arguments"])
                    expected_tool = self._expected_tool_for_task(step_task)
                    logger.trace("TOOL_SELECTED", {"step": step_task, "tool": tool, "arguments": arguments})

                    valid, reason = validate_arguments(tool, arguments)
                    if not valid:
                        logger.log("EXECUTOR", "ARG_INVALID", f"tool={tool} reason={reason}")
                        if retry_count < MAX_RETRIES:
                            retry_count += 1
                            logger.log("EXECUTOR", "RETRY", f"attempt={retry_count}")
                            tool_call = None
                            continue
                        if replan_count < MAX_REPLANS:
                            replan_count += 1
                            tool_call = planner.replan(
                                step_task,
                                tool,
                                "argument_error",
                                working_memory,
                                suggested_tool=expected_tool,
                                critic_history=critic_history[-3:],
                            )
                            logger.log("EXECUTOR", "REPLAN", f"step={step_task}")
                            continue
                        failures.append({"step": step_task, "reason": reason})
                        logger.log("EXECUTOR", "STEP_FAILED", step_task)
                        logger.trace("STEP_FAILED", {"step": step_task, "reason": reason})
                        break

                    raw_output = None
                    exec_error: Exception | None = None
                    try:
                        raw_output = execute_tool_with_timeout(tool, arguments)
                    except Exception as exc:
                        exec_error = exc
                        error_class = classify_error(exc)
                        logger.log("EXECUTOR", "EXEC_ERROR", str(exc))
                        if retry_count < MAX_RETRIES:
                            retry_count += 1
                            logger.log("EXECUTOR", "RETRY", f"attempt={retry_count}")
                            tool_call = None
                            continue
                        if replan_count < MAX_REPLANS:
                            replan_count += 1
                            tool_call = planner.replan(
                                step_task,
                                tool,
                                error_class,
                                working_memory,
                                suggested_tool=expected_tool,
                                critic_history=critic_history[-3:],
                            )
                            logger.log("EXECUTOR", "REPLAN", f"step={step_task}")
                            continue
                        failures.append({"step": step_task, "reason": str(exc)})
                        logger.log("EXECUTOR", "STEP_FAILED", step_task)
                        logger.trace("STEP_FAILED", {"step": step_task, "reason": str(exc)})
                        break

                    reported_error = self._tool_reported_error(tool, raw_output)
                    if reported_error is not None:
                        logger.log("EXECUTOR", "TOOL_REPORTED_ERROR", {"tool": tool, "error": reported_error})

                    result_summary = interpret(raw_output)
                    logger.log("EXECUTOR", "RESULT_SUMMARY", result_summary)
                    logger.trace("RESULT_SUMMARY", {"step": step_task, "summary": result_summary})

                    verdict = evaluate(
                        step_task,
                        tool,
                        arguments,
                        result_summary,
                        reported_error or (str(exec_error) if exec_error else None),
                    )
                    if not self._step_matches_task(step_task, tool, arguments, result_summary):
                        verdict = {
                            "score": 0.0,
                            "decision": "incorrect",
                            "reason": "tool output did not satisfy task intent",
                            "suggested_tool": expected_tool or tool,
                        }
                    critic_history.append(verdict)
                    logger.trace("CRITIC_SCORE", {"step": step_task, "verdict": verdict})

                    memory_record = {
                        "task": step_task,
                        "tool": tool,
                        "success": verdict["decision"] == "correct",
                        "score": verdict["score"],
                        "timestamp": datetime.datetime.utcnow().isoformat(),
                    }
                    write_memory(memory_record)
                    logger.trace("MEMORY_WRITE", memory_record)

                    state.last_tool = tool
                    state.last_result_summary = copy.deepcopy(result_summary)
                    if verdict["decision"] == "correct":
                        all_results.append(
                            {
                                "step": step_task,
                                "tool": tool,
                                "args": dict(arguments),
                                "summary": result_summary,
                                "verdict": verdict,
                            }
                        )
                        step_success = True
                        break
                    if replan_count < MAX_REPLANS:
                        replan_count += 1
                        tool_call = planner.replan(
                            step_task,
                            tool,
                            "reasoning_error",
                            working_memory,
                            suggested_tool=expected_tool,
                            critic_history=critic_history[-3:],
                        )
                        logger.log("EXECUTOR", "REPLAN", f"step={step_task}")
                        continue
                    failures.append({"step": step_task, "reason": verdict["reason"]})
                    logger.log("EXECUTOR", "STEP_FAILED", step_task)
                    logger.trace("STEP_FAILED", {"step": step_task, "reason": verdict["reason"]})
                    break

            state.goal_achieved, state.goal_evidence = self._evaluate_goal(task, steps, all_results, failures)
            success_steps = [item for item in all_results if item["verdict"]["decision"] == "correct"]
            success_pattern = success_steps[-1]["tool"] if success_steps else "none"
            write_reflection(
                {
                    "task": task,
                    "failures": failures,
                    "success_pattern": success_pattern,
                    "improvement": "prefer " + success_pattern if success_pattern != "none" else "replan more aggressively",
                }
            )
            avg_score = (
                sum(float(item["verdict"].get("score", 0.0)) for item in all_results) / len(all_results)
                if all_results
                else 0.0
            )
            if state.goal_achieved and avg_score >= 0.75:
                steps_for_skill = [
                    {
                        "tool": item["tool"],
                        "arguments": item.get("args", {}),
                        "score": float(item["verdict"].get("score", 0.0)),
                    }
                    for item in all_results
                    if item["verdict"].get("decision") == "correct"
                ]
                if steps_for_skill:
                    skills.save_skill(str(task)[:50], steps_for_skill, avg_score)
            result = {
                "run_id": run_id,
                "task": task,
                "steps_completed": len(all_results),
                "failures": failures,
                "final_summary": state.last_result_summary,
                "goal_achieved": state.goal_achieved,
                "goal_evidence": state.goal_evidence,
            }
            result["suggested_next_task"] = self._suggest_next_task(task, result, state)
            logger.end_run(result)
            return result
        except Exception as exc:
            failure_result = {
                "run_id": run_id,
                "task": task,
                "steps_completed": len(all_results),
                "failures": failures + [{"step": state.current_goal or task, "reason": str(exc)}],
                "final_summary": state.last_result_summary,
                "goal_achieved": False,
                "goal_evidence": str(exc),
            }
            logger.end_run(failure_result)
            raise

    def run_with_retries(
        self,
        action: ValidatedAction,
        *,
        planner: Any,
        validator: Any,
        state: Any,
    ) -> tuple[ValidatedAction, ExecutionResult]:
        step_task = self._step_task_from_state(state)
        working_memory = {
            "last_tool": getattr(state.history[-1], "tool_name", "none") if getattr(state, "history", None) else "none",
            "last_result_summary": json.dumps(interpret(getattr(state, "shared_context", {}).get(action.step_number - 1)))[:200],
            "current_goal": step_task,
        }
        retry_count = 0
        replan_count = 0
        critic_history: list[dict[str, Any]] = []
        tool_call = {
            "tool": action.tool_name,
            "arguments": dict(action.parameters),
            "confidence": 1.0,
        }

        while True:
            if retry_count > MAX_RETRIES and replan_count > MAX_REPLANS:
                logger.log(
                    "EXECUTOR",
                    "STEP_FAILED",
                    {"step": step_task, "reason": "limits exhausted"},
                )
                write_reflection(
                    {
                        "task": getattr(state, "task", step_task),
                        "failures": [{"step": step_task, "reason": "limits exhausted"}],
                        "success_pattern": "none",
                        "improvement": "replan more aggressively",
                    }
                )
                raise RuntimeError("limits exhausted")
            tool = str(tool_call["tool"])
            arguments = dict(tool_call["arguments"])
            expected_tool = self._expected_tool_for_task(step_task)

            valid, reason = validate_arguments(tool, arguments)
            if not valid:
                logger.log("EXECUTOR", "ARG_INVALID", f"tool={tool} reason={reason}")
                if retry_count < MAX_RETRIES:
                    retry_count += 1
                    logger.log("EXECUTOR", "RETRY", f"attempt={retry_count}")
                    continue
                if replan_count < MAX_REPLANS:
                    replan_count += 1
                    tool_call = planner.replan(
                        step_task,
                        tool,
                        "argument_error",
                        working_memory,
                        suggested_tool=expected_tool,
                        critic_history=critic_history[-3:],
                    )
                    logger.log("EXECUTOR", "REPLAN", f"step={step_task}")
                    continue
                logger.log("EXECUTOR", "STEP_FAILED", step_task)
                write_reflection(
                    {
                        "task": getattr(state, "task", step_task),
                        "failures": [{"step": step_task, "reason": reason}],
                        "success_pattern": "none",
                        "improvement": "replan more aggressively",
                    }
                )
                raise RuntimeError(reason)

            start = time.perf_counter()
            exec_error: Exception | None = None
            raw_output = None
            try:
                raw_output = execute_tool_with_timeout(tool, arguments)
            except Exception as exc:
                exec_error = exc
                error_class = classify_error(exc)
                logger.log("EXECUTOR", "EXEC_ERROR", str(exc))
                if retry_count < MAX_RETRIES:
                    retry_count += 1
                    logger.log("EXECUTOR", "RETRY", f"attempt={retry_count}")
                    continue
                if replan_count < MAX_REPLANS:
                    replan_count += 1
                    tool_call = planner.replan(
                        step_task,
                        tool,
                        error_class,
                        working_memory,
                        suggested_tool=expected_tool,
                        critic_history=critic_history[-3:],
                    )
                    logger.log("EXECUTOR", "REPLAN", f"step={step_task}")
                    continue
                logger.log("EXECUTOR", "STEP_FAILED", step_task)
                write_reflection(
                    {
                        "task": getattr(state, "task", step_task),
                        "failures": [{"step": step_task, "reason": str(exc)}],
                        "success_pattern": "none",
                        "improvement": "replan more aggressively",
                    }
                )
                raise RuntimeError(str(exc))

            duration = max(time.perf_counter() - start, 0.0)
            reported_error = self._tool_reported_error(tool, raw_output)
            if reported_error is not None:
                logger.log("EXECUTOR", "TOOL_REPORTED_ERROR", {"tool": tool, "error": reported_error})
            result_summary = interpret(raw_output)
            logger.log("EXECUTOR", "RESULT_SUMMARY", result_summary)
            verdict = evaluate(step_task, tool, arguments, result_summary, reported_error or (str(exec_error) if exec_error else None))
            if not self._step_matches_task(step_task, tool, arguments, result_summary):
                verdict = {
                    "score": 0.0,
                    "decision": "incorrect",
                    "reason": "tool output did not satisfy task intent",
                    "suggested_tool": expected_tool or tool,
                }
            critic_history.append(verdict)
            write_memory(
                {
                    "task": step_task,
                    "tool": tool,
                    "success": verdict["decision"] == "correct",
                    "score": verdict["score"],
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                }
            )

            if verdict["decision"] == "correct":
                write_reflection(
                    {
                        "task": getattr(state, "task", step_task),
                        "failures": [],
                        "success_pattern": tool,
                        "improvement": "prefer " + tool,
                    }
                )
                raw_action = {
                    "tool_name": tool,
                    "parameters": self._compat_parameters(tool, arguments),
                    "reason": f"executed step: {step_task}",
                    "step_number": action.step_number,
                }
                validated_action = validator.validate(raw_action)
                return (
                    validated_action,
                    ExecutionResult(
                        success=True,
                        output=raw_output,
                        error=None,
                        duration_seconds=duration,
                        timed_out=False,
                    ),
                )

            if replan_count < MAX_REPLANS:
                replan_count += 1
                tool_call = planner.replan(
                    step_task,
                    tool,
                    "reasoning_error",
                    working_memory,
                    suggested_tool=expected_tool,
                    critic_history=critic_history[-3:],
                )
                logger.log("EXECUTOR", "REPLAN", f"step={step_task}")
                continue

            logger.log("EXECUTOR", "STEP_FAILED", step_task)
            write_reflection(
                {
                    "task": getattr(state, "task", step_task),
                    "failures": [{"step": step_task, "reason": verdict["reason"]}],
                    "success_pattern": "none",
                    "improvement": "replan more aggressively",
                }
            )
            raise RuntimeError(verdict["reason"])

    @staticmethod
    def _run_validated_action(action: ValidatedAction) -> ExecutionResult:
        start = time.perf_counter()
        try:
            output = execute_tool_with_timeout(action.tool_name, dict(action.parameters))
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=True,
                output=output,
                error=None,
                duration_seconds=duration,
                timed_out=False,
            )
        except Exception as exc:
            duration = max(time.perf_counter() - start, 0.0)
            return ExecutionResult(
                success=False,
                output=None,
                error=str(exc),
                duration_seconds=duration,
                timed_out=isinstance(exc, TimeoutError),
            )

    @staticmethod
    def _compat_parameters(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "system_info":
            return {"include_environment": False}
        if tool == "list_files":
            return {"path": str(arguments.get("path", "."))}
        if tool == "read_file":
            return {"path": str(arguments.get("path", ""))}
        if tool == "web_search":
            return {"query": str(arguments.get("query", ""))}
        if tool == "write_file":
            return {"path": str(arguments.get("path", "")), "content": str(arguments.get("content", ""))}
        if tool == "run_command":
            return {"command": str(arguments.get("command", ""))}
        if tool == "web_fetch":
            return {"url": str(arguments.get("url", ""))}
        if tool == "write_code":
            return {
                "filename": str(arguments.get("filename", "")),
                "language": str(arguments.get("language", "")),
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

    @staticmethod
    def _step_task_from_state(state: Any) -> str:
        task = str(getattr(state, "task", ""))
        if hasattr(state, "step_number"):
            segments = [item.strip() for item in task.split(" then ") if item.strip()]
            if segments:
                index = min(max(int(getattr(state, "step_number", 1)) - 1, 0), len(segments) - 1)
                return segments[index]
        return task

    @staticmethod
    def _evaluate_goal(
        task: str,
        steps: list[dict[str, Any]],
        all_results: list[dict[str, Any]],
        failures: list[dict[str, str]],
    ) -> tuple[bool, str]:
        _ = task
        if failures:
            return False, failures[-1].get("reason", "one or more steps failed")
        if len(all_results) != len(steps):
            return False, "not all planned steps completed successfully"
        if not all_results:
            return False, "no successful step produced non-empty output"
        for expected_step, actual in zip(steps, all_results, strict=False):
            if not Executor._step_matches_task(
                str(expected_step.get("task", task)),
                str(actual.get("tool", "")),
                dict(actual.get("args", {})),
                dict(actual.get("summary", {})),
            ):
                return False, "one or more completed steps did not satisfy the planned task"
        return True, str(all_results[-1]["summary"].get("summary", ""))

    @staticmethod
    def _expected_tool_for_task(task: str) -> str | None:
        lowered = task.lower()
        if "execute python code" in lowered or "run python code" in lowered:
            return "execute_python"
        if re.search(r"\b(?:execute|run)\s+python\s+file\b", lowered) or re.search(r"\bpython\s+file\b", lowered):
            return "execute_python_file"
        if any(keyword in lowered for keyword in ("search", "google", "look up", "lookup", "documentation")):
            return "web_search"
        if any(keyword in lowered for keyword in ("read", "open", "show", "cat", "entry point")):
            return "read_file"
        if any(keyword in lowered for keyword in ("summarize", "summary", "analyze")):
            return "summarize_file"
        if any(keyword in lowered for keyword in ("lint", "ruff", "pyflakes")):
            return "lint_file"
        if any(keyword in lowered for keyword in ("write code", "python script", "hello world")):
            return "write_code"
        if any(keyword in lowered for keyword in ("list", "files", "directory", "folder")):
            return "list_files"
        return None

    @staticmethod
    def _extract_task_path(task: str) -> str | None:
        match = next(iter(re.findall(r'([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+|[A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+)', task)), None)
        return match

    @classmethod
    def _step_matches_task(
        cls,
        step_task: str,
        tool: str,
        arguments: dict[str, Any],
        result_summary: dict[str, Any],
    ) -> bool:
        lowered = step_task.lower()
        expected_tool = cls._expected_tool_for_task(step_task)
        if expected_tool and tool != expected_tool:
            return False
        if result_summary.get("type") == "empty":
            return False
        path = cls._extract_task_path(step_task)
        if tool in {"read_file", "summarize_file", "lint_file", "execute_python_file"} and path:
            return Path(str(arguments.get("path", ""))).name == Path(path).name
        if tool == "list_files":
            if "current directory" in lowered:
                return str(arguments.get("path", "")) == "."
            directory_match = re.search(r"\bin (?:the )?([A-Za-z0-9_./-]+) directory\b", lowered)
            if directory_match:
                return str(arguments.get("path", "")) == directory_match.group(1)
            return str(arguments.get("path", ".")) == "."
        if tool == "execute_python":
            code = str(arguments.get("code", "")).strip()
            if "print(2 + 2)" in lowered:
                return "print(2 + 2)" in code
            return bool(code)
        if tool == "web_search":
            return result_summary.get("type") == "list"
        return True

    @staticmethod
    def _tool_reported_error(tool: str, raw_output: Any) -> str | None:
        if not isinstance(raw_output, dict):
            return None
        if raw_output.get("success") is False:
            return str(raw_output.get("error") or f"{tool} returned success=false")
        return None

    @classmethod
    def _skill_is_applicable(cls, skill: dict[str, Any], task: str) -> bool:
        skill_steps = [item for item in skill.get("steps", []) if isinstance(item, dict)]
        expected_steps = _fallback_plan(task)
        if not skill_steps:
            return False
        if len(skill_steps) != len(expected_steps):
            return False
        for expected, actual in zip(expected_steps, skill_steps, strict=False):
            tool = str(actual.get("tool", ""))
            arguments = dict(actual.get("arguments", {}))
            if not cls._step_matches_task(str(expected.get("task", task)), tool, arguments, {"type": "dict", "summary": "skill", "key_info": []}):
                return False
        return True

    def _suggest_next_task(self, task: str, result: dict[str, Any], state: AgentState) -> str | None:
        if not result.get("goal_achieved"):
            return None
        prompt = (
            "The agent just completed: "
            + task
            + "\nFinal result: "
            + json.dumps(state.last_result_summary, default=str)[:200]
            + "\nSuggest ONE next logical task as a single sentence.\n"
            + "Return ONLY the task sentence. No explanation."
        )
        try:
            suggestion = self.planner._call_llm(prompt).strip()
            if len(suggestion) > 10:
                logger.log("EXECUTOR", "NEXT_TASK_SUGGESTION", suggestion)
                return suggestion
        except Exception:
            pass
        lowered = task.lower()
        if "read " in lowered:
            path = self._extract_task_path(task)
            if path:
                return f"summarize {path}"
        if "list" in lowered and "files" in lowered:
            return "read one of the relevant files from the listing"
        if "search" in lowered:
            return "fetch one of the returned URLs"
        if "summarize" in lowered:
            return "identify the key functions or entry points mentioned in the summary"
        return None


def classify_error(e: Exception) -> str:
    try:
        import requests
    except Exception:
        requests = None  # type: ignore[assignment]

    if isinstance(e, (FileNotFoundError, PermissionError)):
        return "argument_error"
    if requests is not None and isinstance(e, requests.exceptions.RequestException):
        return "network_error"
    if isinstance(e, (ValueError, KeyError, TypeError)):
        return "reasoning_error"
    return "tool_error"


def validate_arguments(tool: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    if tool == "read_file":
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        if not _path_exists(path):
            return False, "file does not exist: " + path
        return True, ""
    if tool == "web_search":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return False, "missing or empty query"
        return True, ""
    if tool == "list_files":
        arguments.setdefault("path", ".")
        return True, ""
    if tool == "system_info":
        return True, ""
    if tool == "write_file":
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        if "content" not in arguments:
            return False, "missing content"
        normalized_path = os.path.abspath(path)
        for blocked in ("/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc"):
            if normalized_path.startswith(blocked):
                return False, "write to system path is not permitted"
        return True, ""
    if tool == "run_command":
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return False, "missing or empty command"
        return True, ""
    if tool == "web_fetch":
        url = arguments.get("url")
        if not isinstance(url, str) or not url.strip():
            return False, "missing or empty url"
        if not url.startswith(("http://", "https://")):
            return False, "url must start with http:// or https://"
        return True, ""
    if tool == "write_code":
        filename = arguments.get("filename")
        language = arguments.get("language")
        description = arguments.get("description")
        if not isinstance(filename, str) or not filename.strip():
            return False, "missing or empty filename"
        if not filename.endswith((".py", ".js", ".ts", ".sh", ".go", ".rs", ".java", ".c", ".cpp", ".rb", ".yaml", ".json")):
            return False, "filename must use a supported code extension"
        if not isinstance(language, str) or not language.strip():
            return False, "missing or empty language"
        if not isinstance(description, str) or len(description.strip()) < 5:
            return False, "description must be at least 5 characters"
        return True, ""
    if tool == "execute_python":
        code = arguments.get("code")
        if not isinstance(code, str) or len(code.strip()) < 3:
            return False, "missing or empty code"
        return True, ""
    if tool == "execute_python_file":
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        if not path.endswith(".py"):
            return False, "path must end with .py"
        if not _path_exists(path):
            return False, "file does not exist: " + path
        return True, ""
    if tool == "lint_file":
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        if not _path_exists(path):
            return False, "file does not exist: " + path
        return True, ""
    if tool == "patch_file":
        path = arguments.get("path")
        old = arguments.get("old")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        if not _path_exists(path):
            return False, "file does not exist: " + path
        if not isinstance(old, str) or not old:
            return False, "missing or empty old"
        if "new" not in arguments:
            return False, "missing new"
        return True, ""
    if tool == "summarize_file":
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        if not _path_exists(path):
            return False, "file does not exist: " + path
        return True, ""
    if tool == "diff_files":
        path_a = arguments.get("path_a")
        path_b = arguments.get("path_b")
        if not isinstance(path_a, str) or not path_a.strip():
            return False, "missing or empty path_a"
        if not isinstance(path_b, str) or not path_b.strip():
            return False, "missing or empty path_b"
        if not _path_exists(path_a):
            return False, "file does not exist: " + path_a
        if not _path_exists(path_b):
            return False, "file does not exist: " + path_b
        return True, ""
    if tool == "create_directory":
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        return True, ""
    if tool == "delete_file":
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "missing or empty path"
        if not _path_exists(path):
            return False, "file does not exist: " + path
        return True, ""
    return False, "unknown tool"


def execute_tool(tool: str, arguments: dict[str, Any]) -> Any:
    dispatch = {
        "system_info": lambda: system_info(),
        "list_files": lambda: list_files(arguments.get("path", ".")),
        "read_file": lambda: read_file(arguments["path"]),
        "write_file": lambda: write_file(arguments["path"], arguments.get("content", "")),
        "run_command": lambda: run_command(arguments["command"]),
        "web_search": lambda: web_search(arguments["query"]),
        "web_fetch": lambda: web_fetch(arguments["url"]),
        "write_code": lambda: write_code(arguments["filename"], arguments["language"], arguments["description"]),
        "execute_python": lambda: execute_python(arguments["code"]),
        "execute_python_file": lambda: execute_python_file(arguments["path"]),
        "lint_file": lambda: lint_file(arguments["path"]),
        "patch_file": lambda: patch_file(arguments["path"], arguments["old"], arguments["new"]),
        "summarize_file": lambda: summarize_file(arguments["path"]),
        "diff_files": lambda: diff_files(arguments["path_a"], arguments["path_b"]),
        "create_directory": lambda: create_directory(arguments["path"]),
        "delete_file": lambda: delete_file(arguments["path"]),
    }
    if tool not in dispatch:
        raise ValueError("Unknown tool: " + tool)
    return dispatch[tool]()


def _path_exists(path: str) -> bool:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.exists()
    return (Path(root_settings.workspace_dir) / candidate).exists()


def execute_tool_with_timeout(tool: str, arguments: dict[str, Any]) -> Any:
    timeout = TOOL_TIMEOUTS.get(tool, 10)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(execute_tool, tool, arguments)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"{tool} timed out after {timeout}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
