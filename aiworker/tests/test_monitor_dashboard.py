"""Tests for the monitoring dashboard backend helpers."""

from __future__ import annotations

import unittest

from aiworker.dashboard.server import (
    get_debug_stream_payload,
    get_loop_state_payload,
    get_metrics_payload,
    get_patches_payload,
    get_policy_payload,
    get_runtime_payload,
    get_skills_payload,
    get_system_status_payload,
)
from aiworker.learning.models import Skill
from aiworker.learning.skill_store import SkillDatabase, SkillRepository
from aiworker.agents.manager import agent_manager
from aiworker.knowledge.knowledge_graph import knowledge_graph
from aiworker.meta_learning.meta_optimizer import meta_optimizer
from aiworker.monitor.control import control_plane
from aiworker.monitor.patch_history import patch_history
from aiworker.monitor.telemetry import telemetry
from aiworker.reflection.self_reflection import self_reflection_engine
from aiworker.research.progress import research_progress
from aiworker.self_modify.self_upgrade_engine import self_upgrade_engine
from aiworker.tools.tool_registry import tool_registry
from aiworker.runtime.state import reset_runtime_state
from aiworker.world_model.world_state import world_state_store


class MonitoringDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        telemetry.reset()
        patch_history.reset()
        research_progress.reset()
        agent_manager.reset()
        knowledge_graph.reset()
        meta_optimizer.reset()
        self_reflection_engine.reset()
        self_upgrade_engine.reset()
        tool_registry.reset()
        reset_runtime_state()
        world_state_store.reset()

    def test_metrics_payload_contains_required_dashboard_fields(self) -> None:
        payload = get_metrics_payload()
        for key in (
            "cpu",
            "memory",
            "ai_confidence",
            "requests_per_min",
            "errors_24h",
            "patch_success_rate",
            "loop_state",
            "skills",
            "learning_progress",
            "research_progress",
            "loop_iterations",
            "tasks_completed",
            "tasks_failed",
            "agent_activity",
            "current_stage",
            "loop_pipeline",
            "patch_lifecycle",
            "runtime_status",
            "runtime_iteration",
            "active_goal",
            "last_action",
        ):
            self.assertIn(key, payload)

    def test_metrics_payload_exposes_skill_summary_and_learning_progress(self) -> None:
        db = SkillDatabase(":memory:")
        db.initialise()
        repo = SkillRepository(db)
        repo.upsert_skill(Skill(name="Python", skill_id="python", mastery_score=0.82))
        repo.upsert_skill(Skill(name="Testing", skill_id="testing", mastery_score=0.58))
        telemetry.attach_skill_repository(repo)

        payload = get_metrics_payload()
        skills_payload = get_skills_payload()

        self.assertEqual(payload["skills"]["Python"], 0.82)
        self.assertEqual(skills_payload["skills"]["Testing"], 0.58)
        self.assertAlmostEqual(payload["learning_progress"], 0.7)

    def test_metrics_payload_exposes_research_progress(self) -> None:
        research_progress.start_run(4)
        research_progress.record_completed(1)
        research_progress.record_completed(1)

        payload = get_metrics_payload()

        self.assertEqual(payload["research_tasks_total"], 4)
        self.assertEqual(payload["research_tasks_completed"], 2)
        self.assertAlmostEqual(payload["research_progress"], 0.5)

    def test_patch_history_and_control_plane_apply_flow(self) -> None:
        event = patch_history.record_event(
            "proposal",
            confidence=0.82,
            validation_status="passed",
            file_changed=["app.py"],
            diff="diff --git a/app.py b/app.py",
            result="Patch proposed",
        )
        control_plane.update_policy(read_only=False, admin_mode=True, auto_apply=False)
        applied = control_plane.apply_patch(event_id=event.id)
        self.assertTrue(applied["applied"])
        patches = get_patches_payload()
        self.assertEqual(patches[0]["patch_type"], "apply")

    def test_status_and_debug_stream_reflect_start_learning(self) -> None:
        result = control_plane.start_learning(goal="monitor the worker")
        self.assertTrue(result["started"])
        loop_state = get_loop_state_payload()
        system_status = get_system_status_payload()
        debug_stream = get_debug_stream_payload()
        self.assertEqual(loop_state["loop_state"], "running")
        self.assertTrue(system_status["autonomy_loop_active"])
        self.assertEqual(system_status["current_stage"], "GOAL")
        self.assertGreaterEqual(len(debug_stream), 1)

    def test_policy_payload_defaults_to_read_only(self) -> None:
        payload = get_policy_payload()
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["admin_mode"])

    def test_runtime_payload_defaults_to_idle(self) -> None:
        payload = get_runtime_payload()
        self.assertIn("running", payload)
        self.assertIn("iteration", payload)
        self.assertFalse(payload["running"])


if __name__ == "__main__":
    unittest.main()
