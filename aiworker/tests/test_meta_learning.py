"""Tests for the meta-learning engine."""

from __future__ import annotations

import unittest

from aiworker.autonomy.models import AttemptRecord
from aiworker.meta_learning.meta_optimizer import meta_optimizer


class MetaLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        meta_optimizer.reset()

    def test_optimizer_adapts_strategy_from_failures(self) -> None:
        attempts = (
            AttemptRecord(1, "a1", "2026-03-18T00:00:00+00:00", "sandbox_failed"),
            AttemptRecord(2, "a2", "2026-03-18T00:00:01+00:00", "sandbox_failed"),
            AttemptRecord(3, "a3", "2026-03-18T00:00:02+00:00", "success"),
        )
        report = meta_optimizer.optimize(attempts)
        self.assertEqual(report["dominant_failure_mode"], "sandbox_failed")
        self.assertEqual(report["recommended_strategy"], "collect_more_evidence")
        self.assertGreater(report["exploration_rate"], report["exploitation_rate"])


if __name__ == "__main__":
    unittest.main()
