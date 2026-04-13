"""Tests for voice command routing."""

from __future__ import annotations

import unittest

from aiworker.monitor.patch_history import patch_history
from aiworker.monitor.telemetry import telemetry
from aiworker.voice.interface import execute_voice_command


class VoiceInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        telemetry.reset()
        patch_history.reset()

    def test_status_report_command_is_recognized(self) -> None:
        response = execute_voice_command("status report")
        self.assertTrue(response["recognized"])
        self.assertIn("metrics", response["result"])

    def test_apply_patch_command_uses_control_plane(self) -> None:
        event = patch_history.record_event(
            "proposal",
            confidence=0.7,
            validation_status="passed",
            file_changed=["app.py"],
            diff="diff --git a/app.py b/app.py",
            result="ready",
        )
        del event
        response = execute_voice_command("apply patch", admin=True)
        self.assertTrue(response["recognized"])
        self.assertTrue(response["result"]["applied"])

    def test_unknown_command_returns_error(self) -> None:
        response = execute_voice_command("launch satellites")
        self.assertFalse(response["recognized"])
        self.assertIn("error", response)


if __name__ == "__main__":
    unittest.main()
