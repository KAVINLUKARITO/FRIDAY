"""Tests for the continuous runtime engine."""

from __future__ import annotations

import tempfile
import unittest

from aiworker.config import AIWorkerConfig
from aiworker.monitor.patch_history import patch_history
from aiworker.monitor.telemetry import telemetry
from aiworker.runtime.engine import AIWorkerRuntime
from aiworker.runtime.state import read_runtime_status, reset_runtime_state


class RuntimeLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        telemetry.reset()
        patch_history.reset()
        reset_runtime_state()

    def test_run_loop_executes_single_cycle_and_updates_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = AIWorkerRuntime(
                config=AIWorkerConfig(
                    db_path=f"{tmpdir}/runtime.db",
                    workspace_path=tmpdir,
                ),
                sleep_interval=0.0,
                max_iterations_per_hour=10,
                max_token_usage=10000,
                loop_timeout_seconds=30.0,
            )
            runtime.start(goal="research new techniques", background=False, max_cycles=1)

            status = runtime.status()
            metrics = telemetry.metrics_payload()
            self.assertEqual(status["iteration"], 1)
            self.assertEqual(status["goal"], "research new techniques")
            self.assertIn(status["last_action"], ("executed research cycle", "executed autonomous coordination cycle", "runtime idle"))
            self.assertEqual(metrics["runtime_iteration"], 1)
            self.assertEqual(read_runtime_status()["iteration"], 1)

    def test_stop_sets_runtime_status(self) -> None:
        runtime = AIWorkerRuntime(sleep_interval=0.0)
        status = runtime.stop()
        self.assertFalse(status["running"])
        self.assertEqual(status["last_action"], "runtime stop requested")


if __name__ == "__main__":
    unittest.main()
