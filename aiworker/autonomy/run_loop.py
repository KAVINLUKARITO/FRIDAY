"""# FILE: aiworker/autonomy/run_loop.py — Autonomous execution loop for EvolutionController."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from aiworker.autonomy.models import (
    AttemptRecord,
    EvolutionResult,
    _new_attempt_id,
    _utcnow_iso,
)
from aiworker.learning.analyzer import analyze_result
from aiworker.learning.context_builder import build_context
from aiworker.llm.response import DeepSeekResponse
from aiworker.learning.store import LearningStore
from aiworker.planning.planner import generate_plan
from aiworker.planning.simulator import simulate_plan
from aiworker.planning.validator import validate_plan
from aiworker.monitor.patch_history import patch_history
from aiworker.monitor.telemetry import telemetry
from aiworker.agents.manager import agent_manager
from aiworker.knowledge.knowledge_graph import knowledge_graph
from aiworker.meta_learning.meta_optimizer import meta_optimizer
from aiworker.reflection.self_reflection import self_reflection_engine
from aiworker.research.experiment_runner import ExperimentRunner
from aiworker.research.web_researcher import WebResearcher
from aiworker.scoring.calculator import calculate_confidence
from aiworker.self_modify.change_request import ChangeRequest
from aiworker.self_modify.engine import process_change_request
from aiworker.self_modify.patch_validator import validate_patch
from aiworker.self_modify.self_upgrade_engine import self_upgrade_engine
from aiworker.tools.tool_discovery import tool_discovery
from aiworker.tools.tool_registry import tool_registry
from aiworker.world_model.environment_model import predict_outcomes
from aiworker.world_model.world_state import update_world_state

if TYPE_CHECKING:
    from aiworker.autonomy.controller import EvolutionController
    from aiworker.learning.models import LearningContext


_RATE_LIMIT_TOKEN = "Rate limit exceeded"
_WEB_RESEARCHER = WebResearcher()
_EXPERIMENT_RUNNER = ExperimentRunner()


def _build_change_request(controller: "EvolutionController") -> ChangeRequest:
    config = controller.config
    return ChangeRequest(
        goal=config.goal,
        allowed_files=list(config.allowed_files),
        forbidden_files=list(config.forbidden_files),
        max_lines_changed=config.max_lines_changed,
        tests_required=config.tests_required,
        risk_level=config.risk_level,
    )


def _augment_goal(goal: str, context: "LearningContext") -> str:
    if not context.has_prior_knowledge:
        return goal

    parts = [goal, "", "Prior learning:"]
    if context.suggested_strategy:
        parts.append(f"Suggested strategy: {context.suggested_strategy}")
    if context.common_failure_modes:
        failure_modes = ", ".join(context.common_failure_modes)
        parts.append(f"Common failure modes: {failure_modes}")
    return "\n".join(parts)


def _record_attempt(
    attempts: list[AttemptRecord],
    record: AttemptRecord,
) -> AttemptRecord:
    attempts.append(record)
    return record


def _build_result(
    controller: "EvolutionController",
    attempts: list[AttemptRecord],
    termination_reason: str,
    final_confidence: float,
    detail: str,
) -> EvolutionResult:
    successful_attempts = sum(1 for attempt in attempts if attempt.outcome == "success")
    failed_attempts = sum(
        1 for attempt in attempts if attempt.outcome not in ("success", "dry_run_skip")
    )
    return EvolutionResult(
        config=controller.config,
        success=termination_reason == "success",
        termination_reason=termination_reason,
        total_attempts=len(attempts),
        successful_attempts=successful_attempts,
        failed_attempts=failed_attempts,
        attempts=tuple(attempts),
        final_confidence=final_confidence,
        detail=detail,
    )


def _store_lessons(
    controller: "EvolutionController",
    learning_store: Optional[LearningStore],
    result: EvolutionResult,
) -> None:
    lessons = analyze_result(result)
    if learning_store is None:
        return

    for lesson in lessons:
        learning_store.insert_lesson(lesson)

    controller.audit_log.emit(
        category="lifecycle",
        severity="info",
        action="lessons_stored",
        detail=f"Stored {len(lessons)} lessons from this run",
        metadata={"count": len(lessons)},
    )


def _is_rate_limited(reasons: tuple[str, ...]) -> bool:
    return any(_RATE_LIMIT_TOKEN in reason for reason in reasons)


def _emit_stage(
    controller: "EvolutionController",
    attempt_id: str,
    stage: str,
    detail: str,
) -> None:
    controller.audit_log.emit(
        category="lifecycle",
        severity="info",
        action=stage.lower(),
        detail=detail,
        metadata={"stage": stage},
        attempt_id=attempt_id,
    )


def _normalize_patch_output(
    generated_patch: object,
) -> tuple[Optional[str], Optional[str]]:
    if isinstance(generated_patch, DeepSeekResponse):
        if generated_patch.valid and generated_patch.diff.strip():
            return generated_patch.diff, None
        error_text = "; ".join(generated_patch.errors) or "Patch generation failed"
        return None, error_text
    if isinstance(generated_patch, str):
        cleaned = generated_patch.strip()
        if cleaned:
            return cleaned, None
        return None, "Patch generation failed"
    if generated_patch is None:
        return None, "Patch generation failed"
    return None, f"Unsupported patch generator output: {type(generated_patch).__name__}"


def _record_patch_event(
    patch_type: str,
    *,
    confidence: float = 0.0,
    validation_status: str = "pending",
    file_changed: tuple[str, ...] | list[str] = (),
    diff: str = "",
    result: str = "",
    root_cause: str = "",
    fix_proposal: str = "",
) -> None:
    patch_history.record_event(
        patch_type,
        confidence=confidence,
        validation_status=validation_status,
        file_changed=list(file_changed),
        diff=diff,
        result=result,
        root_cause=root_cause,
        fix_proposal=fix_proposal,
    )


def run_loop(controller: "EvolutionController") -> EvolutionResult:
    """Execute the governed autonomous evolution loop."""
    config = controller.config
    learning_store = LearningStore(controller.database) if controller.database else None
    attempts: list[AttemptRecord] = []
    consecutive_failures = 0
    final_confidence = 0.0
    telemetry.record("loop_started")
    telemetry.set_loop_state("running")
    telemetry.set_current_stage("GOAL")
    update_world_state(
        goal=config.goal,
        active_tasks=("goal_received",),
        constraints={"read_only": telemetry.policy_state()["read_only"]},
        resources={"time_budget": config.max_attempts},
    )
    knowledge_graph.add_concept(config.goal, kind="goal")
    tool_discovery.discover(("generate_plan", "validate_patch", "sandbox_runner"))

    controller.audit_log.emit(
        category="lifecycle",
        severity="info",
        action="evolution_started",
        detail=(
            f"Starting goal '{config.goal}' with up to {config.max_attempts} attempts"
        ),
    )

    try:
        for attempt_number in range(1, config.max_attempts + 1):
            if consecutive_failures >= config.max_failures:
                break

            attempt_id = _new_attempt_id()
            timestamp = _utcnow_iso()
            telemetry.record("loop_iteration", loop_state="running")
            telemetry.set_current_stage("GOAL")
            telemetry.record_debug_stage(
                "SCAN",
                root_cause=f"Goal: {config.goal}",
                fix_proposal=f"Scan allowed files: {', '.join(config.allowed_files)}",
                validation_result="in_progress",
                detail=f"Attempt {attempt_number} started",
            )
            _record_patch_event(
                "scan",
                file_changed=config.allowed_files,
                result=f"Attempt {attempt_number} started",
                root_cause=config.goal,
                fix_proposal="Scan workspace for eligible patch targets",
            )
            controller.audit_log.emit(
                category="lifecycle",
                severity="info",
                action="attempt_started",
                detail=f"Attempt {attempt_number} started",
                metadata={"attempt_number": attempt_number},
                attempt_id=attempt_id,
            )

            decision = controller.policy_engine.evaluate(attempt_id=attempt_id)
            if not decision.allowed:
                denied_record = _record_attempt(
                    attempts,
                    AttemptRecord(
                        attempt_number=attempt_number,
                        attempt_id=attempt_id,
                        timestamp=timestamp,
                        outcome="policy_denied",
                        detail="; ".join(decision.reasons) or "Policy denied execution",
                    ),
                )

                if decision.circuit_state != "closed":
                    result = _build_result(
                        controller,
                        attempts,
                        "circuit_breaker_open",
                        final_confidence,
                        denied_record.detail or "Circuit breaker open",
                    )
                    _store_lessons(controller, learning_store, result)
                    telemetry.record("task_failed", confidence=final_confidence)
                    return result

                if _is_rate_limited(decision.reasons):
                    consecutive_failures += 1
                    if consecutive_failures >= config.max_failures:
                        break
                    continue

                controller.policy_engine.record_outcome(False, attempt_id=attempt_id)
                consecutive_failures += 1
                if consecutive_failures >= config.max_failures:
                    break
                continue

            augmented_goal = config.goal
            if learning_store is not None:
                try:
                    context = build_context(config.goal, learning_store)
                except Exception:
                    context = None
                if context is not None and context.has_prior_knowledge:
                    augmented_goal = _augment_goal(config.goal, context)
                    controller.audit_log.emit(
                        category="lifecycle",
                        severity="info",
                        action="context_loaded",
                        detail="Loaded relevant lessons for this goal",
                        metadata={"lesson_count": context.lesson_count},
                        attempt_id=attempt_id,
                    )

            telemetry.set_current_stage("PLAN")
            try:
                telemetry.record_debug_stage(
                    "ANALYZE",
                    root_cause=config.goal,
                    fix_proposal="Generate and validate execution plan",
                    validation_result="in_progress",
                    detail="Planning autonomous fix",
                )
                _record_patch_event(
                    "analysis",
                    file_changed=config.allowed_files,
                    result="Plan analysis started",
                    root_cause=config.goal,
                    fix_proposal="Generate execution plan",
                )
                _emit_stage(controller, attempt_id, "PLAN", "Generating plan")
                plan = generate_plan(config.goal)
                if not validate_plan(plan):
                    record = _record_attempt(
                        attempts,
                        AttemptRecord(
                            attempt_number=attempt_number,
                            attempt_id=attempt_id,
                            timestamp=timestamp,
                            outcome="plan_failed",
                            policy_allowed=True,
                            detail="Generated plan failed validation",
                        ),
                    )
                    telemetry.record("patch_failed")
                    _record_patch_event(
                        "analysis",
                        file_changed=config.allowed_files,
                        validation_status="failed",
                        result="Generated plan failed validation",
                        root_cause=config.goal,
                        fix_proposal="Revise plan before patch proposal",
                    )
                    controller.policy_engine.record_outcome(False, attempt_id=attempt_id)
                    consecutive_failures += 1
                    if consecutive_failures >= config.max_failures:
                        break
                    continue
            except Exception as exc:
                record = _record_attempt(
                    attempts,
                    AttemptRecord(
                        attempt_number=attempt_number,
                        attempt_id=attempt_id,
                        timestamp=timestamp,
                        outcome="plan_failed",
                        policy_allowed=True,
                        detail="Plan generation failed",
                        error=str(exc),
                    ),
                )
                telemetry.record("patch_failed")
                telemetry.record_error(str(exc))
                controller.policy_engine.record_outcome(False, attempt_id=attempt_id)
                consecutive_failures += 1
                if consecutive_failures >= config.max_failures:
                    break
                continue

            telemetry.set_current_stage("RESEARCH")
            agent_summary = agent_manager.coordinate(
                goal=config.goal,
                allowed_files=config.allowed_files,
            )
            research_bundle = _WEB_RESEARCHER.collect_knowledge(
                config.goal,
                max_queries=max(1, min(3, len(config.allowed_files))),
            )
            experiment_bundle = _EXPERIMENT_RUNNER.run_experiments(research_bundle["hypotheses"])
            knowledge_graph.add_experience_pattern(
                f"goal:{config.goal}",
                hypotheses=research_bundle["hypotheses"],
                experiments=experiment_bundle["experiments_run"],
            )
            update_world_state(
                active_tasks=("research_complete",),
                observations={
                    "research_queries": len(research_bundle["queries"]),
                    "agent_cycles": 1,
                },
            )

            try:
                telemetry.set_current_stage("CODE")
                _emit_stage(controller, attempt_id, "CODE", "Generating patch")
                generated_patch = controller.patch_generator.generate(
                    plan=plan,
                    goal=augmented_goal,
                    allowed_files=config.allowed_files,
                    seed=config.seed,
                )
            except Exception as exc:
                patch_text = None
                patch_error = str(exc)
            else:
                patch_text, patch_error = _normalize_patch_output(generated_patch)

            if patch_text is None:
                telemetry.record("patch_failed")
                telemetry.record_error(patch_error or "Patch generation failed")
                _record_attempt(
                    attempts,
                    AttemptRecord(
                        attempt_number=attempt_number,
                        attempt_id=attempt_id,
                        timestamp=timestamp,
                        outcome="patch_generation_failed",
                        policy_allowed=True,
                        plan_generated=True,
                        detail="Patch generation failed",
                        error=patch_error,
                    ),
                )
                controller.audit_log.emit(
                    category="lifecycle",
                    severity="warning",
                    action="patch_gen_failed",
                    detail="Patch generation failed",
                    attempt_id=attempt_id,
                )
                controller.policy_engine.record_outcome(False, attempt_id=attempt_id)
                consecutive_failures += 1
                if consecutive_failures >= config.max_failures:
                    break
                continue

            change_request = _build_change_request(controller)
            proposal_confidence = simulate_plan(plan).estimated_success_probability
            predictions = predict_outcomes(
                tuple(step.description for step in plan.steps),
            )
            update_world_state(
                active_plan=tuple(step.description for step in plan.steps),
                predictions=predictions,
            )
            telemetry.record("patch_proposed", confidence=proposal_confidence)
            telemetry.record_debug_stage(
                "PROPOSE",
                root_cause=config.goal,
                fix_proposal="Generated candidate patch",
                confidence=proposal_confidence,
                validation_result="proposed",
                detail="Patch proposal ready for validation",
            )
            _record_patch_event(
                "proposal",
                confidence=proposal_confidence,
                file_changed=config.allowed_files,
                diff=patch_text,
                result="Patch proposed",
                root_cause=config.goal,
                fix_proposal="Review generated diff",
            )
            _emit_stage(controller, attempt_id, "TEST", "Validating generated patch")
            validation = validate_patch(patch_text, change_request)
            telemetry.record_debug_stage(
                "VALIDATE",
                root_cause=config.goal,
                fix_proposal="Validate unified diff against policy",
                confidence=proposal_confidence,
                validation_result="passed" if validation.valid else "failed",
                detail="Patch validation completed",
            )
            _record_patch_event(
                "validation",
                confidence=proposal_confidence,
                validation_status="passed" if validation.valid else "failed",
                file_changed=config.allowed_files,
                diff=patch_text,
                result="Patch validation completed",
                root_cause=config.goal,
                fix_proposal="Proceed to sandbox execution" if validation.valid else "Reject invalid diff",
            )
            if not validation.valid:
                telemetry.record("patch_failed", confidence=proposal_confidence)
                _record_attempt(
                    attempts,
                    AttemptRecord(
                        attempt_number=attempt_number,
                        attempt_id=attempt_id,
                        timestamp=timestamp,
                        outcome="validation_failed",
                        policy_allowed=True,
                        plan_generated=True,
                        patch_generated=True,
                        patch_text=patch_text,
                        detail="; ".join(validation.errors),
                    ),
                )
                controller.audit_log.emit(
                    category="validation",
                    severity="warning",
                    action="validation_failed",
                    detail="Patch failed validation",
                    metadata=validation.to_dict(),
                    attempt_id=attempt_id,
                )
                controller.policy_engine.record_outcome(False, attempt_id=attempt_id)
                consecutive_failures += 1
                if consecutive_failures >= config.max_failures:
                    break
                continue

            if config.dry_run:
                tool_registry.record_tool_result("sandbox_runner", success=True)
                _record_attempt(
                    attempts,
                    AttemptRecord(
                        attempt_number=attempt_number,
                        attempt_id=attempt_id,
                        timestamp=timestamp,
                        outcome="dry_run_skip",
                        policy_allowed=True,
                        plan_generated=True,
                        patch_generated=True,
                        validation_passed=True,
                        patch_text=patch_text,
                        detail="Dry run enabled; sandbox execution skipped",
                    ),
                )
                _record_patch_event(
                    "approval",
                    confidence=proposal_confidence,
                    validation_status="dry_run",
                    file_changed=config.allowed_files,
                    diff=patch_text,
                    result="Dry run skipped sandbox execution",
                    root_cause=config.goal,
                    fix_proposal="Manual review required before apply",
                )
                continue

            telemetry.set_current_stage("TEST")
            engine_result = process_change_request(
                change_request=change_request,
                patch_text=patch_text,
                workspace_path=controller.workspace_path,
                timeout=config.sandbox_timeout,
                explicit_approval=True,
                database=controller.database,
            )

            sandbox_success = bool(
                engine_result.sandbox_result and engine_result.sandbox_result.success
            )
            tool_registry.record_tool_result("sandbox_runner", success=sandbox_success)
            _record_patch_event(
                "sandbox execution",
                confidence=proposal_confidence,
                validation_status="passed" if sandbox_success else "failed",
                file_changed=config.allowed_files,
                diff=patch_text,
                result=engine_result.reason or "Sandbox execution completed",
                root_cause=config.goal,
                fix_proposal="Advance to approval" if sandbox_success else "Investigate sandbox failure",
            )
            _emit_stage(controller, attempt_id, "TEST", "Collected sandbox execution result")
            if not (engine_result.validation_passed and sandbox_success and engine_result.approved):
                telemetry.record(
                    "sandbox_failure",
                    confidence=proposal_confidence,
                    detail=engine_result.reason or "Sandbox execution failed",
                )
                telemetry.record_debug_stage(
                    "APPLY",
                    root_cause=config.goal,
                    fix_proposal="Reject patch after sandbox failure",
                    confidence=proposal_confidence,
                    validation_result="sandbox_failed",
                    detail=engine_result.reason or "Sandbox execution failed",
                )
                _record_attempt(
                    attempts,
                    AttemptRecord(
                        attempt_number=attempt_number,
                        attempt_id=attempt_id,
                        timestamp=timestamp,
                        outcome="sandbox_failed",
                        policy_allowed=True,
                        plan_generated=True,
                        patch_generated=True,
                        validation_passed=engine_result.validation_passed,
                        sandbox_success=sandbox_success,
                        patch_text=patch_text,
                        detail=engine_result.reason or "Sandbox execution failed",
                    ),
                )
                controller.audit_log.emit(
                    category="sandbox",
                    severity="warning",
                    action="sandbox_failed",
                    detail=engine_result.reason or "Sandbox execution failed",
                    attempt_id=attempt_id,
                )
                controller.policy_engine.record_outcome(False, attempt_id=attempt_id)
                consecutive_failures += 1
                if consecutive_failures >= config.max_failures:
                    break
                continue

            telemetry.set_current_stage("EVALUATE")
            if controller.database is not None:
                confidence = calculate_confidence(
                    controller.database,
                    config.goal,
                    config.risk_level,
                )
            else:
                confidence = simulate_plan(plan).estimated_success_probability

                _emit_stage(controller, attempt_id, "EVALUATE", "Scoring execution result")
            final_confidence = confidence
            if confidence < config.confidence_threshold:
                _record_patch_event(
                    "approval",
                    confidence=confidence,
                    validation_status="rejected",
                    file_changed=config.allowed_files,
                    diff=patch_text,
                    result="Patch confidence below threshold",
                    root_cause=config.goal,
                    fix_proposal="Do not apply low-confidence patch",
                )
                telemetry.record("patch_failed", confidence=confidence)
                _record_attempt(
                    attempts,
                    AttemptRecord(
                        attempt_number=attempt_number,
                        attempt_id=attempt_id,
                        timestamp=timestamp,
                        outcome="scoring_below_threshold",
                        policy_allowed=True,
                        plan_generated=True,
                        patch_generated=True,
                        validation_passed=True,
                        sandbox_success=True,
                        confidence_score=confidence,
                        patch_text=patch_text,
                        detail=(
                            f"Confidence {confidence:.3f} below threshold "
                            f"{config.confidence_threshold:.3f}"
                        ),
                    ),
                )
                controller.policy_engine.record_outcome(False, attempt_id=attempt_id)
                consecutive_failures += 1
                if consecutive_failures >= config.max_failures:
                    break
                continue

            success_record = _record_attempt(
                attempts,
                AttemptRecord(
                    attempt_number=attempt_number,
                    attempt_id=attempt_id,
                    timestamp=timestamp,
                    outcome="success",
                    policy_allowed=True,
                    plan_generated=True,
                    patch_generated=True,
                    validation_passed=True,
                    sandbox_success=True,
                    confidence_score=confidence,
                    patch_text=patch_text,
                    detail=engine_result.reason or "Patch applied and tests passed",
                ),
            )
            controller.policy_engine.record_outcome(True, attempt_id=attempt_id)
            _record_patch_event(
                "approval",
                confidence=confidence,
                validation_status="approved",
                file_changed=config.allowed_files,
                diff=patch_text,
                result="Patch approved",
                root_cause=config.goal,
                fix_proposal="Apply validated patch",
            )
            _record_patch_event(
                "apply",
                confidence=confidence,
                validation_status="applied",
                file_changed=config.allowed_files,
                diff=patch_text,
                result=success_record.detail or "Patch applied and tests passed",
                root_cause=config.goal,
                fix_proposal="Patch applied successfully",
            )
            telemetry.record("patch_applied", confidence=confidence)
            telemetry.record_debug_stage(
                "APPLY",
                root_cause=config.goal,
                fix_proposal="Patch applied successfully",
                confidence=confidence,
                validation_result="applied",
                detail=success_record.detail or "Patch applied and tests passed",
            )
            controller.audit_log.emit(
                category="lifecycle",
                severity="info",
                action="attempt_succeeded",
                detail=success_record.detail or "Attempt succeeded",
                attempt_id=attempt_id,
            )
            result = _build_result(
                controller,
                attempts,
                "success",
                confidence,
                success_record.detail or "Goal completed successfully",
            )
            telemetry.set_current_stage("LEARN")
            _emit_stage(controller, attempt_id, "LEARN", "Persisting lessons from successful run")
            _store_lessons(controller, learning_store, result)
            meta_optimizer.optimize(result.attempts)
            reflection_payload = self_reflection_engine.reflect(
                attempts=result.attempts,
                skill_summary=telemetry.metrics_payload().get("skills", {}),
                current_policy=telemetry.policy_state(),
            )
            update_world_state(
                observations={"recent_failures": 0, "reflection": reflection_payload},
                active_tasks=("learning_complete",),
            )
            knowledge_graph.record_experience(
                concept=config.goal,
                skill="autonomous_repair",
                relationship="improved_by",
                pattern="successful_run",
                confidence=confidence,
            )
            telemetry.set_current_stage("IMPROVE SYSTEM")
            self_upgrade_engine.run(
                {
                    "ai_confidence": confidence,
                    "learning_progress": telemetry.metrics_payload().get("learning_progress", 0.0),
                    "research_progress": telemetry.metrics_payload().get("research_progress", 0.0),
                }
            )
            telemetry.record("task_completed", confidence=confidence)
            telemetry.record("loop_completed", loop_state="completed")
            telemetry.set_loop_state("completed")
            telemetry.set_current_stage("completed")
            return result

        if consecutive_failures >= config.max_failures:
            termination_reason = "max_failures_reached"
        elif len(attempts) >= config.max_attempts:
            if attempts and all(record.outcome == "policy_denied" for record in attempts):
                termination_reason = "all_attempts_exhausted"
            else:
                termination_reason = "max_attempts_reached"
        else:
            termination_reason = "all_attempts_exhausted"

        result = _build_result(
            controller,
            attempts,
            termination_reason,
            final_confidence,
            f"Loop terminated with {termination_reason}",
        )
        if attempts:
            telemetry.set_current_stage("LEARN")
            _emit_stage(
                controller,
                attempts[-1].attempt_id,
                "LEARN",
                "Persisting lessons from completed run",
            )
        _store_lessons(controller, learning_store, result)
        meta_optimizer.optimize(result.attempts)
        reflection_payload = self_reflection_engine.reflect(
            attempts=result.attempts,
            skill_summary=telemetry.metrics_payload().get("skills", {}),
            current_policy=telemetry.policy_state(),
        )
        update_world_state(
            observations={
                "recent_failures": result.failed_attempts,
                "reflection": reflection_payload,
            },
            active_tasks=("learning_complete",),
        )
        telemetry.set_current_stage("IMPROVE SYSTEM")
        self_upgrade_engine.run(
            {
                "ai_confidence": final_confidence,
                "learning_progress": telemetry.metrics_payload().get("learning_progress", 0.0),
                "research_progress": telemetry.metrics_payload().get("research_progress", 0.0),
            }
        )
        telemetry.record("task_failed", confidence=final_confidence)
        telemetry.record("loop_completed", loop_state="idle")
        telemetry.set_loop_state("idle")
        telemetry.set_current_stage("idle")
        return result
    except Exception as exc:
        telemetry.record_error(str(exc))
        telemetry.record("task_failed", confidence=final_confidence)
        telemetry.record("loop_completed", loop_state="error")
        telemetry.set_loop_state("error")
        telemetry.set_current_stage("error")
        error_result = _build_result(
            controller,
            attempts,
            "error",
            final_confidence,
            f"Execution failed: {exc}",
        )
        _store_lessons(controller, learning_store, error_result)
        return error_result
