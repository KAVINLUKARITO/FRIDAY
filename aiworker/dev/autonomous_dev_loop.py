"""Deterministic autonomous development loop with strict safety gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from aiworker.dev.diff_safety import validate_diff_safety
from aiworker.dev.failure_classifier import classify_failure
from aiworker.dev.model_router import ModelRole, ModelRouter
from aiworker.dev.patch_validator import validate_patch
from aiworker.dev.safe_applier import SafeApplyResult, SafeApplier
from aiworker.dev.self_corrector import build_correction_plan
from aiworker.dev.static_analyzer import analyze_patch_python
from aiworker.dev.token_budget import enforce_token_budget
from aiworker.orchestration.schema_guard import validate_patch_payload


@dataclass(frozen=True)
class AtomicDevTask:
    goal: str
    target_file: str
    allowed_files: tuple[str, ...]


@dataclass(frozen=True)
class AutonomousDevConfig:
    max_attempts: int = 3
    confidence_threshold: float = 0.80
    risk_threshold: float = 0.70
    circuit_breaker_failures: int = 3
    token_cap: int = 4096
    expected_diff_lines: int = 50
    base_seed: int = 0
    allow_deletions: bool = False


@dataclass(frozen=True)
class AttemptTrace:
    attempt: int
    success: bool
    confidence: float
    failure_type: str
    reason: str


@dataclass(frozen=True)
class AutonomousDevResult:
    success: bool
    confidence: float
    attempts_used: int
    traces: tuple[AttemptTrace, ...]
    final_failure_type: str | None


class PatchGenerator(Protocol):
    def generate(
        self,
        *,
        task: AtomicDevTask,
        goal: str,
        allowed_files: Sequence[str],
        seed: int,
        correction_prompt: str,
        model_name: str,
    ) -> Optional[str]:
        """Return strict JSON payload with analysis, diff, risk_score."""


class AutonomousDevLoop:
    """Deterministic autonomous patch generation, validation, and apply loop."""

    def __init__(
        self,
        *,
        generator: PatchGenerator,
        model_router: ModelRouter,
        safe_applier: SafeApplier,
        config: AutonomousDevConfig = AutonomousDevConfig(),
    ) -> None:
        self._generator = generator
        self._model_router = model_router
        self._safe_applier = safe_applier
        self._config = config

    def _decompose_goal(self, goal: str, allowed_files: Sequence[str]) -> tuple[AtomicDevTask, ...]:
        tasks = [
            AtomicDevTask(goal=goal, target_file=file_path, allowed_files=(file_path,))
            for file_path in allowed_files
        ]
        return tuple(tasks)

    def _compute_confidence(
        self,
        *,
        tests_passed_ratio: float,
        static_analysis_score: float,
        sandbox_stability: float,
        risk_score: float,
        failed_attempts: int,
    ) -> float:
        retry_penalty = max(0.0, 1.0 - (failed_attempts / max(1, self._config.max_attempts)))
        value = (
            0.35 * max(0.0, min(1.0, tests_passed_ratio))
            + 0.20 * max(0.0, min(1.0, static_analysis_score))
            + 0.15 * max(0.0, min(1.0, sandbox_stability))
            + 0.20 * (1.0 - max(0.0, min(1.0, risk_score)))
            + 0.10 * retry_penalty
        )
        return max(0.0, min(1.0, value))

    def run(
        self,
        *,
        goal: str,
        allowed_files: Sequence[str],
        workspace_path: str,
    ) -> AutonomousDevResult:
        planner_model = self._model_router.route(ModelRole.Planner)
        _ = planner_model
        tasks = self._decompose_goal(goal, allowed_files)
        if not tasks:
            return AutonomousDevResult(
                success=False,
                confidence=0.0,
                attempts_used=0,
                traces=(),
                final_failure_type="validation_error",
            )

        traces: list[AttemptTrace] = []
        consecutive_failures = 0
        last_failure = ""
        current_prompt = ""
        failed_attempts = 0

        for task in tasks:
            for attempt in range(1, self._config.max_attempts + 1):
                budget = enforce_token_budget(
                    prompt=f"{goal}\n{current_prompt}\nTarget: {task.target_file}",
                    expected_diff_lines=self._config.expected_diff_lines,
                    hard_cap=self._config.token_cap,
                )
                if not budget.allowed:
                    failure_type = "validation_error"
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type=failure_type,
                            reason=budget.error or "Token budget exceeded",
                        )
                    )
                    return AutonomousDevResult(
                        success=False,
                        confidence=0.0,
                        attempts_used=attempt,
                        traces=tuple(traces),
                        final_failure_type=failure_type,
                    )

                role = ModelRole.Generator if attempt == 1 else ModelRole.Corrector
                model_name = self._model_router.route(role)
                payload = self._generator.generate(
                    task=task,
                    goal=goal,
                    allowed_files=task.allowed_files,
                    seed=self._config.base_seed + attempt,
                    correction_prompt=current_prompt,
                    model_name=model_name,
                )

                if payload is None:
                    failure_type = "unknown"
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type=failure_type,
                            reason="Generator returned no payload",
                        )
                    )
                    consecutive_failures += 1
                    failed_attempts += 1
                    if consecutive_failures >= self._config.circuit_breaker_failures:
                        return AutonomousDevResult(
                            success=False,
                            confidence=0.0,
                            attempts_used=attempt,
                            traces=tuple(traces),
                            final_failure_type="unknown",
                        )
                    continue

                schema_result = validate_patch_payload(payload)
                if not schema_result.is_valid or schema_result.patch is None:
                    failure_type = classify_failure(validation_errors=(schema_result.error or "schema",))
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type=failure_type,
                            reason=schema_result.error or "Schema validation failed",
                        )
                    )
                    consecutive_failures += 1
                    failed_attempts += 1
                    if failure_type == last_failure:
                        return AutonomousDevResult(
                            success=False,
                            confidence=0.0,
                            attempts_used=attempt,
                            traces=tuple(traces),
                            final_failure_type=failure_type,
                        )
                    last_failure = failure_type
                    continue

                patch_result = validate_patch(
                    schema_result.patch.diff,
                    task.allowed_files,
                    allow_deletions=self._config.allow_deletions,
                )
                if not patch_result.valid:
                    failure_type = classify_failure(
                        validation_errors=patch_result.errors,
                        risk_score=patch_result.risk_score,
                        risk_threshold=self._config.risk_threshold,
                    )
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type=failure_type,
                            reason="; ".join(patch_result.errors),
                        )
                    )
                    consecutive_failures += 1
                    failed_attempts += 1
                    if failure_type == last_failure:
                        return AutonomousDevResult(
                            success=False,
                            confidence=0.0,
                            attempts_used=attempt,
                            traces=tuple(traces),
                            final_failure_type=failure_type,
                        )
                    last_failure = failure_type
                    if patch_result.risk_score > self._config.risk_threshold:
                        return AutonomousDevResult(
                            success=False,
                            confidence=0.0,
                            attempts_used=attempt,
                            traces=tuple(traces),
                            final_failure_type="high_risk",
                        )
                    continue

                if schema_result.patch.risk_score > self._config.risk_threshold:
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type="high_risk",
                            reason="Schema risk score above threshold",
                        )
                    )
                    return AutonomousDevResult(
                        success=False,
                        confidence=0.0,
                        attempts_used=attempt,
                        traces=tuple(traces),
                        final_failure_type="high_risk",
                    )

                analysis = analyze_patch_python(schema_result.patch.diff)
                if not analysis.safe:
                    failure_type = "validation_error"
                    reason = "; ".join(issue.message for issue in analysis.issues)
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type=failure_type,
                            reason=reason,
                        )
                    )
                    consecutive_failures += 1
                    failed_attempts += 1
                    correction = build_correction_plan(
                        error_message=reason,
                        failing_file=task.target_file,
                        failing_test_output=reason,
                        validation_errors=(reason,),
                        risk_score=schema_result.patch.risk_score,
                        risk_threshold=self._config.risk_threshold,
                    )
                    current_prompt = correction.corrective_prompt
                    continue

                diff_safety = validate_diff_safety(schema_result.patch.diff, task.allowed_files)
                if not diff_safety.safe:
                    failure_type = "validation_error"
                    reason = "; ".join(diff_safety.errors)
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type=failure_type,
                            reason=reason,
                        )
                    )
                    consecutive_failures += 1
                    failed_attempts += 1
                    correction = build_correction_plan(
                        error_message=reason,
                        failing_file=task.target_file,
                        failing_test_output=reason,
                        validation_errors=diff_safety.errors,
                    )
                    current_prompt = correction.corrective_prompt
                    continue

                apply_result: SafeApplyResult = self._safe_applier.apply_patch(
                    workspace_path=workspace_path,
                    patch_content=schema_result.patch.diff,
                    allow_deletions=self._config.allow_deletions,
                )

                if not apply_result.success:
                    failure_type = classify_failure(
                        error_message=apply_result.error or "",
                        timed_out=apply_result.timed_out,
                        tests_failed=apply_result.tests_failed,
                        risk_score=schema_result.patch.risk_score,
                        risk_threshold=self._config.risk_threshold,
                    )
                    traces.append(
                        AttemptTrace(
                            attempt=attempt,
                            success=False,
                            confidence=0.0,
                            failure_type=failure_type,
                            reason=apply_result.error or "Safe apply failed",
                        )
                    )
                    consecutive_failures += 1
                    failed_attempts += 1
                    if failure_type == last_failure:
                        return AutonomousDevResult(
                            success=False,
                            confidence=0.0,
                            attempts_used=attempt,
                            traces=tuple(traces),
                            final_failure_type=failure_type,
                        )
                    last_failure = failure_type
                    correction = build_correction_plan(
                        error_message=apply_result.error or "",
                        failing_file=task.target_file,
                        failing_test_output=apply_result.error or "",
                        tests_failed=apply_result.tests_failed,
                        timed_out=apply_result.timed_out,
                        risk_score=schema_result.patch.risk_score,
                        risk_threshold=self._config.risk_threshold,
                    )
                    current_prompt = correction.corrective_prompt
                    if consecutive_failures >= self._config.circuit_breaker_failures:
                        return AutonomousDevResult(
                            success=False,
                            confidence=0.0,
                            attempts_used=attempt,
                            traces=tuple(traces),
                            final_failure_type=failure_type,
                        )
                    continue

                total_tests = apply_result.tests_passed + apply_result.tests_failed
                tests_ratio = 1.0 if total_tests == 0 else apply_result.tests_passed / total_tests
                confidence = self._compute_confidence(
                    tests_passed_ratio=tests_ratio,
                    static_analysis_score=analysis.score,
                    sandbox_stability=1.0,
                    risk_score=max(schema_result.patch.risk_score, patch_result.risk_score),
                    failed_attempts=failed_attempts,
                )

                success = confidence >= self._config.confidence_threshold
                traces.append(
                    AttemptTrace(
                        attempt=attempt,
                        success=success,
                        confidence=confidence,
                        failure_type="" if success else "unknown",
                        reason="accepted" if success else "confidence below threshold",
                    )
                )
                if success:
                    return AutonomousDevResult(
                        success=True,
                        confidence=confidence,
                        attempts_used=attempt,
                        traces=tuple(traces),
                        final_failure_type=None,
                    )

                failed_attempts += 1
                consecutive_failures += 1
                if consecutive_failures >= self._config.circuit_breaker_failures:
                    return AutonomousDevResult(
                        success=False,
                        confidence=confidence,
                        attempts_used=attempt,
                        traces=tuple(traces),
                        final_failure_type="unknown",
                    )

            break

        final_failure = traces[-1].failure_type if traces else "unknown"
        return AutonomousDevResult(
            success=False,
            confidence=traces[-1].confidence if traces else 0.0,
            attempts_used=len(traces),
            traces=tuple(traces),
            final_failure_type=final_failure,
        )


__all__ = [
    "AtomicDevTask",
    "AutonomousDevConfig",
    "AutonomousDevLoop",
    "AutonomousDevResult",
    "AttemptTrace",
    "PatchGenerator",
]
