from __future__ import annotations

import inspect
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from aiworker.config import settings
from aiworker.executor import ExecutionResult, Executor
from aiworker.logger import get_logger
from aiworker.message_bus import Event, EventType, MessageBus
from aiworker.storage import StepRecord, Storage
from aiworker.validator import ValidatedAction, ValidationError, Validator
from aiworker.verifier import VerificationResult, VerificationStatus, Verifier


class AgentState(BaseModel):
    run_id: str
    agent_name: str
    task: str
    step_number: int = 1
    retries: int = 0
    replans: int = 0
    status: str = "running"
    context: dict[str, Any] = Field(default_factory=dict)


class BaseAgent:
    """Shared PLAN -> VALIDATE -> EXECUTE -> VERIFY -> STORE agent loop."""

    def __init__(
        self,
        name: str,
        bus: MessageBus,
        validator: Validator,
        executor: Executor,
        verifier: Verifier,
        storage: Storage,
    ) -> None:
        self.name = name
        self.bus = bus
        self.validator = validator
        self.executor = executor
        self.verifier = verifier
        self.storage = storage
        self.logger = get_logger(name)
        self._queued_context: dict[str, Any] = {}

    def queue_context(self, context: dict[str, Any]) -> None:
        self._queued_context = dict(context)

    def plan(self, state: AgentState) -> dict[str, Any]:
        raise RuntimeError("Subclasses must implement plan()")

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        raise RuntimeError("Subclasses must implement replan()")

    def total_steps(self, state: AgentState) -> int:
        return 1

    def on_step_verified(
        self,
        state: AgentState,
        action: ValidatedAction,
        execution_result: ExecutionResult,
        verification_result: VerificationResult,
    ) -> None:
        state.context["last_output"] = execution_result.output

    def on_complete(self, state: AgentState) -> None:
        state.status = "completed"

    def _publish_agent_error(self, run_id: str, message: str) -> None:
        self.bus.publish(
            Event(
                event_type=EventType.AGENT_ERROR,
                source_agent=self.name,
                payload={"message": message},
                run_id=run_id,
            )
        )

    def run_step(
        self,
        state: AgentState,
        raw_action: dict[str, Any] | None = None,
    ) -> VerificationResult:
        try:
            planned_action = raw_action if raw_action is not None else self.plan(state)
            validated_action = self.validator.validate(planned_action)
        except ValidationError as exc:
            self.logger.error("validation failed at step %s: %s", state.step_number, exc)
            state.status = "aborted"
            self._publish_agent_error(state.run_id, str(exc))
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                reason=str(exc),
                verified_at=datetime.now(timezone.utc),
                agent_name=self.name,
                tool_name=planned_action["tool_name"] if raw_action else "validation",
            )
        except Exception as exc:
            self.logger.exception("planning failed at step %s: %s", state.step_number, exc)
            state.status = "aborted"
            self._publish_agent_error(state.run_id, str(exc))
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                reason=str(exc) or "planning failed",
                verified_at=datetime.now(timezone.utc),
                agent_name=self.name,
                tool_name="planning",
            )

        run_signature = inspect.signature(self.executor.run)
        if "timeout" in run_signature.parameters:
            execution_result = self.executor.run(validated_action, timeout=settings.step_timeout)
        else:
            execution_result = self.executor.run(validated_action)
        verification_result = self.verifier.verify(validated_action, execution_result)

        record = StepRecord(
            run_id=state.run_id,
            agent_name=self.name,
            step_number=state.step_number,
            tool_name=validated_action.tool_name,
            parameters=validated_action.parameters,
            reason=validated_action.reason,
            verification_status=verification_result.status.value,
            output_summary=str(execution_result.output)[:500],
            error=execution_result.error,
            duration_seconds=execution_result.duration_seconds,
            timestamp=verification_result.verified_at,
        )
        self.storage.save_step(record)

        try:
            self.on_step_verified(state, validated_action, execution_result, verification_result)
        except Exception as exc:
            self.logger.exception("step post-processing failed: %s", exc)
            state.status = "aborted"
            self._publish_agent_error(state.run_id, str(exc))
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                reason=str(exc) or "step post-processing failed",
                verified_at=datetime.now(timezone.utc),
                agent_name=self.name,
                tool_name=validated_action.tool_name,
            )

        return verification_result

    def execute_loop(self, task: str, run_id: str) -> AgentState:
        state = AgentState(
            run_id=run_id,
            agent_name=self.name,
            task=task,
            context=dict(self._queued_context),
        )
        self._queued_context = {}
        pending_action: dict[str, Any] | None = None

        while state.step_number <= settings.max_steps and state.status == "running":
            verification_result = self.run_step(state, pending_action)
            pending_action = None

            if state.status != "running":
                break

            if verification_result.status.value == VerificationStatus.SUCCESS.value:
                if state.step_number >= self.total_steps(state):
                    self.on_complete(state)
                    if state.status == "running":
                        state.status = "completed"
                    break
                state.step_number += 1
                state.retries = 0
                continue

            if state.retries < settings.max_retries:
                state.retries += 1
                sleep_seconds = settings.retry_backoff_base * (2 ** (state.retries - 1))
                time.sleep(sleep_seconds)
                continue

            if state.replans < settings.max_replans:
                state.replans += 1
                state.retries = 0
                pending_action = self.replan(state, verification_result.reason)
                continue

            state.status = "aborted"
            self._publish_agent_error(state.run_id, verification_result.reason)
            break

        if state.step_number > settings.max_steps:
            state.status = "step_limit_reached"

        return state
