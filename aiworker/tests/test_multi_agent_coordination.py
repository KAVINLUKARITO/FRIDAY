"""Tests for the multi-agent coordination layer."""

from __future__ import annotations

import unittest

from aiworker.agents.manager import agent_manager


class MultiAgentCoordinationTests(unittest.TestCase):
    def setUp(self) -> None:
        agent_manager.reset()

    def test_manager_coordinates_roles_and_tracks_activity(self) -> None:
        result = agent_manager.coordinate(
            goal="improve telemetry dashboard",
            allowed_files=("aiworker/monitor/telemetry.py",),
        )
        snapshot = agent_manager.snapshot()
        self.assertIn("research", result)
        self.assertIn("plan", result)
        self.assertIn("code", result)
        self.assertIn("critique", result)
        self.assertEqual(snapshot["agents"]["planner"]["status"], "completed")
        self.assertEqual(snapshot["agents"]["research"]["status"], "completed")
        self.assertEqual(snapshot["active_role"], "idle")


if __name__ == "__main__":
    unittest.main()
