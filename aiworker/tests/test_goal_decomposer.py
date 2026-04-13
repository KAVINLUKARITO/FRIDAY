"""Unit tests for goal decomposition."""

from __future__ import annotations

import unittest

from aiworker.agent.goal_decomposer import GoalDecomposer


class _Backend:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        del prompt
        return self.response


class _Controller:
    def __init__(self, success: bool) -> None:
        self._success = success

    def run(self):
        return type("Result", (), {"success": self._success})()


class GoalDecomposerTests(unittest.TestCase):
    def test_uses_llm_json_when_valid(self) -> None:
        decomposer = GoalDecomposer(_Backend('["step one", "step two"]'))
        result = decomposer.decompose("fix auth", ("auth.py",))
        self.assertEqual(result, ["step one", "step two"])

    def test_falls_back_on_invalid_json(self) -> None:
        decomposer = GoalDecomposer(_Backend("not json"))
        result = decomposer.decompose("fix auth", ("auth.py",))
        self.assertEqual(
            result,
            ["reproduce auth", "identify root cause", "apply fix", "verify tests pass"],
        )

    def test_default_fallback_returns_single_goal(self) -> None:
        decomposer = GoalDecomposer(None)
        self.assertEqual(decomposer.decompose("investigate auth", ("auth.py",)), ["investigate auth"])

    def test_execute_sequence_stops_on_failure(self) -> None:
        decomposer = GoalDecomposer(None)
        results = decomposer.execute_sequence(
            ["one", "two", "three"],
            controller_factory=lambda goal: _Controller(success=goal == "one"),
            stop_on_failure=True,
        )
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
