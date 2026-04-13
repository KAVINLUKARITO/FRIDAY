"""Control-plane helpers shared by the CLI, dashboard, and voice interface."""

from __future__ import annotations

from typing import Any

from aiworker.monitor.patch_history import patch_history
from aiworker.monitor.telemetry import telemetry
from aiworker.runtime.engine import runtime_engine
from aiworker.world_model.world_state import update_world_state


class ControlPlane:
    """Small in-memory control surface for dashboard and voice commands."""

    def start_learning(self, goal: str = "dashboard-learning-session") -> dict[str, Any]:
        telemetry.set_loop_state("running")
        telemetry.set_current_stage("GOAL")
        telemetry.record("loop_started")
        update_world_state(goal=goal, active_tasks=("goal_received",))
        telemetry.record_debug_stage(
            "SCAN",
            root_cause=f"Goal received: {goal}",
            fix_proposal="Preparing autonomy loop execution",
            validation_result="queued",
            detail="Learning session started",
        )
        return {"started": True, "goal": goal, "loop_state": "running"}

    def stop_loop(self) -> dict[str, Any]:
        telemetry.set_loop_state("paused")
        telemetry.set_current_stage("paused")
        telemetry.record("loop_paused")
        telemetry.record_debug_stage(
            "APPLY",
            root_cause="Operator requested stop",
            fix_proposal="Pause autonomy loop",
            validation_result="stopped",
            detail="Loop paused by operator",
        )
        return {"stopped": True, "loop_state": "paused"}

    def status_report(self) -> dict[str, Any]:
        return {
            "metrics": telemetry.metrics_payload(),
            "system_status": telemetry.system_status_payload(),
            "loop_state": telemetry.loop_state_payload(),
            "runtime": telemetry.runtime_payload(),
        }

    def start_runtime(self, goal: str | None = None) -> dict[str, Any]:
        return runtime_engine.start(goal=goal, background=True)

    def stop_runtime(self) -> dict[str, Any]:
        return runtime_engine.stop()

    def runtime_status(self) -> dict[str, Any]:
        return runtime_engine.status()

    def update_policy(
        self,
        *,
        read_only: bool | None = None,
        admin_mode: bool | None = None,
        auto_apply: bool | None = None,
    ) -> dict[str, bool]:
        return telemetry.update_policy(
            read_only=read_only,
            admin_mode=admin_mode,
            auto_apply=auto_apply,
        )

    def apply_patch(self, *, event_id: str | None = None) -> dict[str, Any]:
        policy = telemetry.policy_state()
        if policy["read_only"]:
            return {"applied": False, "reason": "read-only mode enabled"}
        if not policy["admin_mode"]:
            return {"applied": False, "reason": "admin mode required"}

        source = patch_history.find_event(event_id) if event_id else patch_history.latest_event()
        if source is None:
            return {"applied": False, "reason": "no patch event available"}

        applied = patch_history.record_event(
            "apply",
            confidence=source.confidence,
            validation_status="approved",
            file_changed=source.file_changed,
            diff=source.diff,
            result="Applied through control plane",
            root_cause=source.root_cause,
            fix_proposal=source.fix_proposal,
        )
        telemetry.record("patch_applied", confidence=source.confidence)
        telemetry.record_debug_stage(
            "APPLY",
            root_cause=source.root_cause,
            fix_proposal=source.fix_proposal or "Apply approved patch",
            confidence=source.confidence,
            validation_result="approved",
            detail="Patch approval completed",
        )
        return {"applied": True, "patch_id": applied.id, "source_patch_id": source.id}

    def rollback_patch(self, *, event_id: str | None = None) -> dict[str, Any]:
        policy = telemetry.policy_state()
        if not policy["admin_mode"]:
            return {"rolled_back": False, "reason": "admin mode required"}

        source = patch_history.find_event(event_id) if event_id else patch_history.latest_event()
        if source is None:
            return {"rolled_back": False, "reason": "no patch event available"}

        rollback = patch_history.record_event(
            "rollback",
            confidence=source.confidence,
            validation_status="rolled_back",
            file_changed=source.file_changed,
            diff=source.diff,
            result="Rollback requested through control plane",
            root_cause=source.root_cause,
            fix_proposal="Rollback to prior safe patch state",
        )
        telemetry.record("patch_failed", confidence=source.confidence)
        telemetry.record_debug_stage(
            "APPLY",
            root_cause=source.root_cause,
            fix_proposal="Rollback patch",
            confidence=source.confidence,
            validation_result="rolled_back",
            detail="Patch rollback completed",
        )
        return {"rolled_back": True, "patch_id": rollback.id, "source_patch_id": source.id}


control_plane = ControlPlane()
