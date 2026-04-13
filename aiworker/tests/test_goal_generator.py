"""Tests for automatic runtime goal generation."""

from __future__ import annotations

import unittest

from aiworker.goals.generator import GoalGenerator


class GoalGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = GoalGenerator()

    def test_returns_user_goal_when_provided(self) -> None:
        goal = self.generator.next_goal(user_goal="fix parser regression")
        self.assertEqual(goal, "fix parser regression")

    def test_prioritizes_error_recovery(self) -> None:
        goal = self.generator.next_goal(
            telemetry_snapshot={"errors_24h": 2, "research_progress": 1.0},
        )
        self.assertEqual(goal, "fix detected errors")

    def test_prioritizes_research_when_progress_low(self) -> None:
        goal = self.generator.next_goal(
            telemetry_snapshot={"errors_24h": 0, "research_progress": 0.2, "learning_progress": 0.9},
        )
        self.assertEqual(goal, "research new techniques")

    def test_round_robin_when_system_is_stable(self) -> None:
        goals = [
            self.generator.next_goal(
                telemetry_snapshot={
                    "errors_24h": 0,
                    "research_progress": 0.9,
                    "learning_progress": 0.9,
                    "patch_success_rate": 90.0,
                    "cpu": 10.0,
                    "memory": 10.0,
                },
            )
            for _ in range(3)
        ]
        self.assertEqual(
            goals,
            ["improve system code", "optimize performance", "research new techniques"],
        )


if __name__ == "__main__":
    unittest.main()
