"""Maintained ReAct-style task agent loop."""

from __future__ import annotations

import logging
import signal
from typing import Iterable

from aiworker.config import AIWorkerConfig
from aiworker.memory.store import MemoryStore
from aiworker.models import (
    AgentPlan,
    AgentRunResult,
    AgentTask,
    PlanStep,
    TaskIntent,
    TaskStatus,
    ToolResult,
)
from aiworker.pipeline.decision_engine import DecisionEngine
from aiworker.pipeline.evaluator import EvaluationEngine
from aiworker.pipeline.executor import Executor
from aiworker.pipeline.state import AgentState
from aiworker.pipeline.validator import Validator
from aiworker.pipeline.verifier import Verifier
from aiworker.safety.safety_cage import SafetyCage, SafetyViolation
from aiworker.tools.tool_registry import ToolRegistry, tool_registr
from aiworker.llm.ollama_backend import OllamaBackend

logger = logging.getLogger(__name__)


class TaskAgent:
    """Small, bounded plan-and-execute agent for local automation tasks."""

    def __init__(
        self,
        config: AIWorkerConfig,
        memory: MemoryStore,
        registry: ToolRegistry = tool_registry,
    ) -> None:
        self.config = config
        self.memory = memory
        self.registry = registry
        self.validator = Validator(registry)
        self.executor = Executor(registry, timeout_seconds=config.tool_timeout_seconds)
        self.verifier = Verifier()
        self.decision_engine = DecisionEngine(
            max_retries=3,
            max_replans=2,
            step_limit=config.max_iterations,
        )
        self.evaluator = EvaluationEngine(config.base_path / "runtime" / "metrics.jsonl")
        self.safety_cage = SafetyCage(config)
        self._shutdown_requested = False

    def request_shutdown(self, *_: object) -> None:
        logger.info("shutdown requested")
        self._shutdown_requested = True

    def install_signal_handlers(self) -> None:
        try:
            signal.signal(signal.SIGINT, self.request_shutdown)
            signal.signal(signal.SIGTERM, self.request_shutdown)
        except ValueError:
            logger.debug("signal handlers can only be installed on the main thread")

    def classify(self, raw_input: str) -> TaskIntent:
        text = raw_input.lower().strip()
        if text.startswith(("read ", "cat ", "show file ")):
            return TaskIntent.read_file
        if any(token in text for token in ("list files", "ls", "directory", "tree")):
            return TaskIntent.inspect
        if any(token in text for token in ("system info", "python version", "platform")):
            return TaskIntent.system_info
        if text:
            return TaskIntent.echo
        return TaskIntent.unknown

    def parse(self, raw_input: str) -> AgentTask:
        task = AgentTask(raw_input=raw_input, intent=self.classify(raw_input))
        self.memory.append(task.id, "task", task.model_dump(mode="json"))
        return task

    def plan(self, task: AgentTask) -> AgentPlan:
        if task.intent == TaskIntent.inspect:
            steps = [
                PlanStep(
                    index=1,
                    tool_name="list_files",
                    arguments={"path": ".", "max_results": 100},
                    rationale="Inspect the project root for visible files.",
                )
            ]
        elif task.intent == TaskIntent.read_file:
            requested = self._extract_path(task.raw_input)
            steps = [
                PlanStep(
                    index=1,
                    tool_name="read_file",
                    arguments={"path": requested},
                    rationale="Read the requested file from the configured project root.",
                )
            ]
        elif task.intent == TaskIntent.system_info:
            steps = [
                PlanStep(
                    index=1,
                    tool_name="system_info",
                    arguments={"include_environment": False},
                    rationale="Collect local runtime metadata.",
                )
            ]
        else:
            steps = [
                PlanStep(
                    index=1,
                    tool_name="echo",
                    arguments={"text": task.raw_input},
                    rationale="Return the task text because no specialized intent was detected.",
                )
            ]

        plan = AgentPlan(task_id=task.id, intent=task.intent, steps=steps)
        self.memory.append(task.id, "plan", plan.model_dump(mode="json"))
        return plan

    def execute(self, task: AgentTask, plan: AgentPlan) -> AgentRunResult:
        logger.info("starting task %s intent=%s", task.id, task.intent)
        tool_results: list[ToolResult] = []
        output_parts: list[str] = []
        planned_actions = [
            {"tool_name": step.tool_name, "parameters": step.arguments}
            for step in plan.steps
        ]
        state = AgentState(
            task_id=task.id,
            raw_input=task.raw_input,
            planned_actions=planned_actions,
            steps_planned=len(planned_actions),
        )

        while state.terminal_status == "RUNNING":
            if self._shutdown_requested:
                state.finish("SHUTDOWN")
                break

            raw_action = self._planner_next_action(task, state)
            if raw_action is None:
                state.finish("SUCCEEDED")
                break

            try:
                validated_action = self.validator.validate(raw_action)
                self.safety_cage.check(state)
                execution_result = self.executor.run(validated_action)
                state.steps_taken += 1
                state.total_executions += 1
                verification_result = self.verifier.verify(validated_action, execution_result.output)
                state.outputs.append(execution_result.output)

                tool_result = ToolResult(
                    success=verification_result.status == "SUCCESS",
                    tool_name=validated_action.tool_name,
                    data={
                        "execution": execution_result.model_dump(mode="json"),
                        "verification": verification_result.model_dump(mode="json"),
                    },
                    error=execution_result.stderr if verification_result.status != "SUCCESS" else None,
                    duration_seconds=execution_result.duration_seconds,
                )
                tool_results.append(tool_result)
                self.memory.append(task.id, "tool", tool_result.model_dump(mode="json"))
                self.evaluator.score(state)

                decision = self.decision_engine.decide(verification_result, state)
                logger.info("decision for task %s: %s", task.id, decision.model_dump())

                if decision.action in {"ABORTED", "STEP_LIMIT_REACHED"}:
                    break
                if decision.action == "RETRY":
                    continue
                if decision.action == "REPLAN":
                    state.mark_replan(self._planner_replan_action(task, state, decision.reason))
                    continue
                if decision.action == "CONTINUE":
                    output_parts.append(self._format_output(execution_result.output))
                    continue
            except SafetyViolation as exc:
                logger.exception("safety violation for task %s", task.id)
                state.errors.append(str(exc))
                state.finish("ABORTED")
                break
            except Exception as exc:
                logger.exception("pipeline failure for task %s", task.id)
                state.errors.append(str(exc))
                state.finish("ABORTED")
                break

        metrics = self.evaluator.score(state)
        logger.info("final metrics for task %s: %s", task.id, metrics.model_dump())

        if state.terminal_status == "SUCCEEDED":
            return self._finish(task, TaskStatus.succeeded, output_parts, tool_results, state.steps_taken)
        if state.terminal_status == "STEP_LIMIT_REACHED":
            return self._finish(task, TaskStatus.max_iterations, output_parts, tool_results, state.steps_taken, "step limit reached")
        if state.terminal_status == "SHUTDOWN":
            return self._finish(task, TaskStatus.shutdown, output_parts, tool_results, state.steps_taken, "shutdown requested")
        return self._finish(task, TaskStatus.failed, output_parts, tool_results, state.steps_taken, "; ".join(state.errors) or state.terminal_status)

    def run(self, raw_input: str) -> AgentRunResult:
        try:
            task = self.parse(raw_input)
            plan = self.plan(task)
            return self.execute(task, plan)
        except Exception as exc:  # pragma: no cover - final safety net
            logger.exception("agent run failed")
            return AgentRunResult(
                success=False,
                task_id="unparsed",
                status=TaskStatus.failed,
                output="",
                iterations=0,
                error=str(exc),
            )

    def _finish(
        self,
        task: AgentTask,
        status: TaskStatus,
        output_parts: Iterable[str],
        tool_results: list[ToolResult],
        iterations: int,
        error: str | None = None,
    ) -> AgentRunResult:
        output = "\n".join(part for part in output_parts if part).strip()
        result = AgentRunResult(
            success=status == TaskStatus.succeeded,
            task_id=task.id,
            status=status,
            output=output,
            iterations=iterations,
            tool_results=tool_results,
            error=error,
        )
        self.memory.append(task.id, "agent", result.model_dump(mode="json"))
        logger.info("finished task %s status=%s iterations=%s", task.id, status, iterations)
        return result

    @staticmethod
    def _extract_path(raw_input: str) -> str:
        prefixes = ("show file ", "read ", "cat ")
        lowered = raw_input.lower().strip()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return raw_input.strip()[len(prefix) :].strip().strip("\"'")
        return raw_input.strip().strip("\"'")

    @staticmethod
    def _format_tool_result(result: ToolResult) -> str:
        if "text" in result.data:
            return str(result.data["text"])
        if "content" in result.data:
            return str(result.data["content"])
        if "files" in result.data:
            return "\n".join(item["path"] for item in result.data["files"])
        return str(result.data)

    @staticmethod
    def _format_output(output: object) -> str:
        if isinstance(output, dict):
            if "text" in output:
                return str(output["text"])
            if "content" in output:
                return str(output["content"])
            if "files" in output and isinstance(output["files"], list):
                return "\n".join(str(item.get("path", item)) for item in output["files"])
        return str(output)

    @staticmethod
    def _planner_next_action(task: AgentTask, state: AgentState) -> dict[str, object] | None:
        del task
        return state.current_action()

    @staticmethod
    def _planner_replan_action(task: AgentTask, state: AgentState, reason: str) -> dict[str, object]:
        return {
            "tool_name": "echo",
            "parameters": {
                "text": f"Replanned task {task.id} after {state.current_action_retries} retries: {reason}",
            },
        }
