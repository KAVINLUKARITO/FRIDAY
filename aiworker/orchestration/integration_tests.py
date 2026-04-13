"""Integration tests for the architecture orchestration engine."""

from __future__ import annotations

import json
import unittest
from typing import Optional, Sequence

from aiworker.orchestration.architecture_controller import ArchitectureController, SandboxRunner
from aiworker.orchestration.architecture_models import (
    AtomicTask,
    ControllerConfig,
    ControllerState,
    ModelRole,
    ModelRoleConfig,
    SandboxResult,
)
from aiworker.orchestration.architecture_planner import create_blueprint
from aiworker.orchestration.confidence_engine import compute_confidence
from aiworker.orchestration.patch_interface import PatchGenerator
from aiworker.orchestration.schema_guard import validate_patch_payload
from aiworker.orchestration.task_decomposer import decompose_blueprint
from aiworker.orchestration.topology_guard import evaluate_patch


class _MockPatchGenerator(PatchGenerator):
    def generate(
        self,
        plan: AtomicTask,
        goal: str,
        allowed_files: Sequence[str],
        seed: int,
    ) -> Optional[str]:
        diff = (
            "--- a/{0}\n"
            "+ + + b/{0}\n"
            "@@ -0,0 +1 @@\n"
            "+# generated\n"
        ).replace("+ + +", "+++").format(allowed_files[0])
        payload = {
            "analysis": f"Implement {plan.module} for {goal}",
            "diff": diff,
            "risk_score": 0.1,
        }
        return json.dumps(payload, sort_keys=True)


class _MockSandboxRunner(SandboxRunner):
    def run(self, diff: str, allowed_files: Sequence[str]) -> SandboxResult:
        return SandboxResult(
            success=True,
            exit_code=0,
            stdout="ok",
            stderr="",
            tests_passed=1,
            tests_total=1,
            import_errors=0,
            runtime_exceptions=0,
            missing_files=(),
            timed_out=False,
        )


class OrchestrationIntegrationTests(unittest.TestCase):
    def test_planner_is_deterministic(self) -> None:
        goal = "Build deterministic orchestration"
        first = create_blueprint(goal)
        second = create_blueprint(goal)
        self.assertEqual(first, second)
        self.assertIn("architecture_controller.py", first.modules_to_create)

    def test_task_decomposer_produces_atomic_tasks(self) -> None:
        blueprint = create_blueprint("Build engine")
        tasks = decompose_blueprint(blueprint)
        self.assertGreater(len(tasks), 0)
        for task in tasks:
            self.assertEqual(len(task.allowed_files), 1)

    def test_schema_guard_rejects_invalid_json(self) -> None:
        result = validate_patch_payload("```json\n{}\n```")
        self.assertFalse(result.is_valid)
        self.assertIsNotNone(result.error)

    def test_confidence_is_within_bounds(self) -> None:
        low = compute_confidence(0.0, False, False, 1.0)
        high = compute_confidence(1.0, True, True, 0.0)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(low, 1.0)
        self.assertGreaterEqual(high, 0.0)
        self.assertLessEqual(high, 1.0)

    def test_topology_guard_blocks_illegal_file_edits(self) -> None:
        diff = "--- a/aiworker/safety/validator.py\n+++ b/aiworker/safety/validator.py\n@@ -1 +1 @@\n-x\n+y\n"
        decision = evaluate_patch(
            diff=diff,
            allowed_files=("aiworker/orchestration/schema_guard.py",),
            repo_root=".",
        )
        self.assertFalse(decision.allowed)

    def test_controller_runs_successfully_with_mocks(self) -> None:
        model_config = ModelRoleConfig(
            role_to_model={
                ModelRole.Planner: "planner-small",
                ModelRole.Generator: "generator-small",
                ModelRole.Corrector: "corrector-small",
            }
        )
        controller = ArchitectureController(
            patch_generator=_MockPatchGenerator(),
            sandbox_runner=_MockSandboxRunner(),
            model_config=model_config,
            config=ControllerConfig(
                max_attempts_per_task=2,
                circuit_breaker_threshold=3,
                confidence_threshold=0.5,
                base_seed=7,
                repo_root=".",
            ),
        )

        report = controller.execute("Build orchestration engine")
        self.assertEqual(report.state, ControllerState.COMPLETED)
        self.assertGreater(len(report.completed_tasks), 0)
        self.assertEqual(len(report.failed_tasks), 0)


if __name__ == "__main__":
    unittest.main()
