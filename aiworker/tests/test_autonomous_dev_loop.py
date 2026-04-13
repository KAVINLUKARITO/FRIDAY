"""Integration tests for deterministic autonomous development loop."""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from aiworker.dev.autonomous_dev_loop import AutonomousDevConfig, AutonomousDevLoop
from aiworker.dev.model_router import ModelRouteConfig, ModelRouter
from aiworker.dev.safe_applier import SafeApplyResult


@dataclass(frozen=True)
class _Scenario:
    name: str


class _MockGenerator:
    def __init__(self, scenario: _Scenario) -> None:
        self._scenario = scenario
        self._calls = 0

    def generate(self, *, task, goal, allowed_files, seed, correction_prompt, model_name):
        self._calls += 1
        path = allowed_files[0]

        if self._scenario.name == "success":
            return json.dumps(
                {
                    "analysis": "safe patch",
                    "diff": self._diff(path, "+def ok():\n+    return 1\n"),
                    "risk_score": 0.10,
                },
                sort_keys=True,
            )

        if self._scenario.name == "syntax_then_fix":
            if self._calls == 1:
                return json.dumps(
                    {
                        "analysis": "broken syntax",
                        "diff": self._diff(path, "+def broken(\n"),
                        "risk_score": 0.10,
                    },
                    sort_keys=True,
                )
            return json.dumps(
                {
                    "analysis": "fix syntax",
                    "diff": self._diff(path, "+def fixed():\n+    return 1\n"),
                    "risk_score": 0.10,
                },
                sort_keys=True,
            )

        if self._scenario.name == "import_then_fix":
            if self._calls == 1:
                return json.dumps(
                    {
                        "analysis": "import failure",
                        "diff": self._diff(path, "+import missing_pkg\n"),
                        "risk_score": 0.10,
                    },
                    sort_keys=True,
                )
            return json.dumps(
                {
                    "analysis": "import fixed",
                    "diff": self._diff(path, "+x = 1\n"),
                    "risk_score": 0.10,
                },
                sort_keys=True,
            )

        if self._scenario.name == "high_risk":
            return json.dumps(
                {
                    "analysis": "dangerous",
                    "diff": self._diff(path, "+x = 1\n"),
                    "risk_score": 0.99,
                },
                sort_keys=True,
            )

        if self._scenario.name == "retry_exhaustion":
            return None

        return json.dumps(
            {
                "analysis": "default",
                "diff": self._diff(path, "+x = 1\n"),
                "risk_score": 0.10,
            },
            sort_keys=True,
        )

    @staticmethod
    def _diff(path: str, additions: str) -> str:
        return (
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -0,0 +1,2 @@\n"
            f"{additions}"
        )


class _MockSafeApplier:
    def apply_patch(self, *, workspace_path: str, patch_content: str, allow_deletions: bool = False):
        if "import missing_pkg" in patch_content:
            return SafeApplyResult(
                success=False,
                committed=False,
                rolled_back=True,
                touched_files=("aiworker/orchestration/tmp_target.py",),
                tests_passed=0,
                tests_failed=1,
                timed_out=False,
                error="ImportError: No module named missing_pkg",
            )

        return SafeApplyResult(
            success=True,
            committed=True,
            rolled_back=False,
            touched_files=("aiworker/orchestration/tmp_target.py",),
            tests_passed=4,
            tests_failed=0,
            timed_out=False,
            error=None,
        )


class TestAutonomousDevLoop(unittest.TestCase):
    def _make_loop(self, scenario_name: str, config: AutonomousDevConfig | None = None) -> AutonomousDevLoop:
        router = ModelRouter(
            ModelRouteConfig(
                planner_model="planner-large",
                generator_model="local-coder",
                corrector_model="local-coder",
                validator_model="deterministic-python",
            )
        )
        return AutonomousDevLoop(
            generator=_MockGenerator(_Scenario(name=scenario_name)),
            model_router=router,
            safe_applier=_MockSafeApplier(),
            config=config or AutonomousDevConfig(max_attempts=3, circuit_breaker_failures=3),
        )

    def test_successful_patch_flow(self) -> None:
        loop = self._make_loop("success")
        result = loop.run(
            goal="Add safe helper",
            allowed_files=("aiworker/orchestration/tmp_target.py",),
            workspace_path=".",
        )
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_syntax_failure_correction(self) -> None:
        loop = self._make_loop("syntax_then_fix")
        result = loop.run(
            goal="Fix syntax",
            allowed_files=("aiworker/orchestration/tmp_target.py",),
            workspace_path=".",
        )
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.attempts_used, 2)

    def test_import_error_correction(self) -> None:
        loop = self._make_loop("import_then_fix")
        result = loop.run(
            goal="Fix import issue",
            allowed_files=("aiworker/orchestration/tmp_target.py",),
            workspace_path=".",
        )
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.attempts_used, 2)

    def test_risk_rejection(self) -> None:
        loop = self._make_loop("high_risk")
        result = loop.run(
            goal="Apply risky patch",
            allowed_files=("aiworker/orchestration/tmp_target.py",),
            workspace_path=".",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.final_failure_type, "high_risk")

    def test_retry_exhaustion(self) -> None:
        loop = self._make_loop(
            "retry_exhaustion",
            config=AutonomousDevConfig(max_attempts=3, circuit_breaker_failures=10),
        )
        result = loop.run(
            goal="Generator unavailable",
            allowed_files=("aiworker/orchestration/tmp_target.py",),
            workspace_path=".",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.attempts_used, 3)

    def test_deterministic_repeatability(self) -> None:
        loop1 = self._make_loop("success")
        loop2 = self._make_loop("success")

        res1 = loop1.run(
            goal="Deterministic",
            allowed_files=("aiworker/orchestration/tmp_target.py",),
            workspace_path=".",
        )
        res2 = loop2.run(
            goal="Deterministic",
            allowed_files=("aiworker/orchestration/tmp_target.py",),
            workspace_path=".",
        )

        self.assertEqual(res1, res2)


if __name__ == "__main__":
    unittest.main()
