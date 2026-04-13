"""Master deterministic architecture orchestration state machine."""

from __future__ import annotations

from typing import Protocol, Sequence

from aiworker.orchestration.architecture_models import (
    AttemptRecord,
    ControllerConfig,
    ControllerRunReport,
    ControllerState,
    FailureType,
    ModelRole,
    ModelRoleConfig,
    SandboxResult,
)
from aiworker.orchestration.architecture_planner import create_blueprint
from aiworker.orchestration.confidence_engine import compute_confidence_from_sandbox
from aiworker.orchestration.failure_classifier import classify_failure
from aiworker.orchestration.patch_interface import PatchGenerator
from aiworker.orchestration.retry_policy import get_retry_instruction
from aiworker.orchestration.schema_guard import validate_patch_payload
from aiworker.orchestration.task_decomposer import decompose_blueprint
from aiworker.orchestration.topology_guard import evaluate_patch


class SandboxRunner(Protocol):
    """Sandbox execution interface used by architecture controller."""

    def run(self, diff: str, allowed_files: Sequence[str]) -> SandboxResult:
        """Run patch diff in sandbox and return deterministic execution result."""


class ArchitectureController:
    """Deterministic architecture controller with retry and guardrails."""

    def __init__(
        self,
        patch_generator: PatchGenerator,
        sandbox_runner: SandboxRunner,
        model_config: ModelRoleConfig,
        config: ControllerConfig = ControllerConfig(),
    ) -> None:
        self._patch_generator = patch_generator
        self._sandbox_runner = sandbox_runner
        self._model_config = model_config
        self._config = config

    def execute(self, goal: str) -> ControllerRunReport:
        """Execute full architecture orchestration for the given goal."""
        state = ControllerState.PLANNING
        completed_tasks: list[str] = []
        failed_tasks: list[str] = []
        attempts: list[AttemptRecord] = []
        consecutive_failures = 0

        # Role validation is deterministic and ensures strict separation is configured.
        _ = self._model_config.model_for(ModelRole.Planner)
        _ = self._model_config.model_for(ModelRole.Generator)
        _ = self._model_config.model_for(ModelRole.Corrector)

        blueprint = create_blueprint(goal)
        state = ControllerState.DECOMPOSING
        tasks = decompose_blueprint(blueprint)

        for task in tasks:
            state = ControllerState.EXECUTING_TASK
            accepted = False

            for attempt_idx in range(self._config.max_attempts_per_task):
                if consecutive_failures >= self._config.circuit_breaker_threshold:
                    return ControllerRunReport(
                        state=ControllerState.CIRCUIT_OPEN,
                        completed_tasks=tuple(completed_tasks),
                        failed_tasks=tuple(failed_tasks),
                        attempts=tuple(attempts),
                    )

                payload = self._patch_generator.generate(
                    plan=task,
                    goal=goal,
                    allowed_files=task.allowed_files,
                    seed=self._config.base_seed + attempt_idx,
                )

                if payload is None:
                    failure_type = FailureType.Unknown
                    instruction = get_retry_instruction(failure_type)
                    attempts.append(
                        AttemptRecord(
                            task_module=task.module,
                            attempt_number=attempt_idx + 1,
                            accepted=False,
                            failure_type=failure_type,
                            failure_instruction=instruction,
                            confidence=0.0,
                        )
                    )
                    consecutive_failures += 1
                    continue

                validation = validate_patch_payload(payload)
                if not validation.is_valid or validation.patch is None:
                    failure_type = FailureType.Unknown
                    instruction = get_retry_instruction(failure_type)
                    attempts.append(
                        AttemptRecord(
                            task_module=task.module,
                            attempt_number=attempt_idx + 1,
                            accepted=False,
                            failure_type=failure_type,
                            failure_instruction=instruction,
                            confidence=0.0,
                        )
                    )
                    consecutive_failures += 1
                    continue

                guard_decision = evaluate_patch(
                    diff=validation.patch.diff,
                    allowed_files=task.allowed_files,
                    repo_root=self._config.repo_root,
                )
                if not guard_decision.allowed:
                    failure_type = FailureType.Unknown
                    instruction = get_retry_instruction(failure_type)
                    attempts.append(
                        AttemptRecord(
                            task_module=task.module,
                            attempt_number=attempt_idx + 1,
                            accepted=False,
                            failure_type=failure_type,
                            failure_instruction=instruction,
                            confidence=0.0,
                        )
                    )
                    consecutive_failures += 1
                    continue

                sandbox_result = self._sandbox_runner.run(
                    diff=validation.patch.diff,
                    allowed_files=task.allowed_files,
                )

                if not sandbox_result.success:
                    failure_type = classify_failure(sandbox_result)
                    instruction = get_retry_instruction(failure_type)
                    attempts.append(
                        AttemptRecord(
                            task_module=task.module,
                            attempt_number=attempt_idx + 1,
                            accepted=False,
                            failure_type=failure_type,
                            failure_instruction=instruction,
                            confidence=0.0,
                        )
                    )
                    consecutive_failures += 1
                    continue

                confidence = compute_confidence_from_sandbox(
                    sandbox_result=sandbox_result,
                    risk_score=validation.patch.risk_score,
                )
                if confidence < self._config.confidence_threshold:
                    failure_type = FailureType.Unknown
                    instruction = get_retry_instruction(failure_type)
                    attempts.append(
                        AttemptRecord(
                            task_module=task.module,
                            attempt_number=attempt_idx + 1,
                            accepted=False,
                            failure_type=failure_type,
                            failure_instruction=instruction,
                            confidence=confidence,
                        )
                    )
                    consecutive_failures += 1
                    continue

                attempts.append(
                    AttemptRecord(
                        task_module=task.module,
                        attempt_number=attempt_idx + 1,
                        accepted=True,
                        failure_type=None,
                        failure_instruction="",
                        confidence=confidence,
                    )
                )
                completed_tasks.append(task.module)
                accepted = True
                consecutive_failures = 0
                break

            if not accepted:
                failed_tasks.append(task.module)
                return ControllerRunReport(
                    state=ControllerState.MAX_ATTEMPTS_REACHED,
                    completed_tasks=tuple(completed_tasks),
                    failed_tasks=tuple(failed_tasks),
                    attempts=tuple(attempts),
                )

        return ControllerRunReport(
            state=ControllerState.COMPLETED,
            completed_tasks=tuple(completed_tasks),
            failed_tasks=tuple(failed_tasks),
            attempts=tuple(attempts),
        )
