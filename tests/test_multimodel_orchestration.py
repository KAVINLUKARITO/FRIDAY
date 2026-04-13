from __future__ import annotations

import json
import unittest

from aiworker.autonomy.orchestrated_loop import OrchestratedLoop, estimate_tokens
from aiworker.execution.sandbox_runner import SandboxApplyResult
from aiworker.llm.coder_adapter import CoderAdapter
from aiworker.llm.model_router import ModelRole, ModelRouter
from aiworker.llm.planner_adapter import PlannerAdapter, TaskSpec
from aiworker.safety.patch_validator import validate_patch


class _StubBackend:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if not self._responses:
            raise RuntimeError("No more stub responses")
        return self._responses.pop(0)


class _FakeSandboxRunner:
    def __init__(self) -> None:
        self.calls = 0

    def apply_patch(self, *, workspace_path: str, patch_content: str) -> SandboxApplyResult:
        self.calls += 1
        return SandboxApplyResult(
            success=True,
            touched_files=("aiworker/llm/model_router.py",),
            tests_passed=1,
            tests_failed=0,
            error=None,
        )


def _task_json() -> str:
    return json.dumps(
        {
            "tasks": [
                {
                    "file": "aiworker/llm/model_router.py",
                    "type": "modify",
                    "description": "Improve routing behavior",
                    "max_lines": 20,
                }
            ]
        },
        sort_keys=True,
    )


def _valid_diff() -> str:
    return (
        "diff --git a/aiworker/llm/model_router.py b/aiworker/llm/model_router.py\n"
        "--- a/aiworker/llm/model_router.py\n"
        "+++ b/aiworker/llm/model_router.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+generated = True\n"
        "+new\n"
    )


class TestMultiModelOrchestration(unittest.TestCase):
    def test_planner_json_validation(self) -> None:
        planner = PlannerAdapter(_StubBackend(["```json\n{}\n```"]))
        with self.assertRaises(ValueError):
            planner.generate("x")

        bad_schema = json.dumps({"tasks": [{"file": "outside.py", "type": "modify", "description": "x", "max_lines": 10}]})
        planner2 = PlannerAdapter(_StubBackend([bad_schema]))
        with self.assertRaises(ValueError):
            planner2.generate("x")

    def test_coder_json_validation(self) -> None:
        coder = CoderAdapter(_StubBackend(['{"analysis":"ok","diff":"not-a-diff","risk_score":0.2}']))
        task = TaskSpec(file="aiworker/llm/model_router.py", type="modify", description="x", max_lines=10)
        with self.assertRaises(ValueError):
            coder.generate(task, "goal")

    def test_router_switches_models_correctly(self) -> None:
        planner_backend = _StubBackend(["planner"])
        coder_backend = _StubBackend(["coder"])
        router = ModelRouter(planner_backend=planner_backend, coder_backend=coder_backend)

        self.assertEqual(router.generate(ModelRole.PLANNER, "p"), "planner")
        self.assertEqual(router.generate(ModelRole.CODER, "c"), "coder")
        self.assertEqual(planner_backend.calls, 1)
        self.assertEqual(coder_backend.calls, 1)
        with self.assertRaises(ValueError):
            router.generate("bad-role", "x")  # type: ignore[arg-type]

    def test_loop_retries_on_invalid_diff(self) -> None:
        planner = PlannerAdapter(_StubBackend([_task_json()]))
        coder = CoderAdapter(
            _StubBackend(
                [
                    '{"analysis":"x","diff":"nope","risk_score":0.1}',
                    json.dumps({"analysis": "ok", "diff": _valid_diff(), "risk_score": 0.1}),
                ]
            )
        )
        loop = OrchestratedLoop(
            planner=planner,
            coder=coder,
            sandbox_runner=_FakeSandboxRunner(),
            max_retries=2,
        )
        result = loop.run(goal="goal", workspace_path=".")
        self.assertTrue(result["success"])
        self.assertEqual(result["completed_tasks"], 1)
        self.assertEqual(result["failed_tasks"], 0)

    def test_high_risk_aborts(self) -> None:
        planner = PlannerAdapter(_StubBackend([_task_json()]))
        coder = CoderAdapter(
            _StubBackend([json.dumps({"analysis": "x", "diff": _valid_diff(), "risk_score": 0.95})])
        )
        loop = OrchestratedLoop(
            planner=planner,
            coder=coder,
            sandbox_runner=_FakeSandboxRunner(),
            max_retries=2,
        )
        result = loop.run(goal="goal", workspace_path=".")
        self.assertFalse(result["success"])
        self.assertEqual(result["completed_tasks"], 0)
        self.assertEqual(result["failed_tasks"], 1)

    def test_deterministic_validation_logic(self) -> None:
        diff = _valid_diff()
        first = validate_patch(diff, allowed_file="aiworker/llm/model_router.py", max_lines=20)
        second = validate_patch(diff, allowed_file="aiworker/llm/model_router.py", max_lines=20)
        self.assertEqual(first, second)
        self.assertGreater(estimate_tokens("abc"), 0)


if __name__ == "__main__":
    unittest.main()
