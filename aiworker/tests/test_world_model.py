"""Tests for the world model subsystem."""

from __future__ import annotations

import unittest

from aiworker.world_model.environment_model import predict_outcomes
from aiworker.world_model.world_state import get_world_state, update_world_state, world_state_store


class WorldModelTests(unittest.TestCase):
    def setUp(self) -> None:
        world_state_store.reset()

    def test_update_world_state_merges_observations(self) -> None:
        update_world_state(goal="improve planner", observations={"recent_failures": 1})
        snapshot = update_world_state(resources={"time_budget": 3})
        self.assertEqual(snapshot["goal"], "improve planner")
        self.assertEqual(snapshot["observations"]["recent_failures"], 1)
        self.assertEqual(snapshot["resources"]["time_budget"], 3)
        self.assertEqual(get_world_state()["version"], 2)

    def test_predict_outcomes_reports_blockers(self) -> None:
        update_world_state(
            constraints={"read_only": True},
            observations={"recent_failures": 2},
            resources={"time_budget": 1},
        )
        prediction = predict_outcomes(("plan", "research", "code", "test"))
        self.assertIn("read_only_mode", prediction["blockers"])
        self.assertLess(prediction["predicted_success_probability"], 0.75)


if __name__ == "__main__":
    unittest.main()
