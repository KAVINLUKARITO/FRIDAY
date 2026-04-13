"""Tests for Phase 4 — Meta-Reasoning and Model Selection (unittest)."""
from __future__ import annotations
import unittest

from aiworker.meta.models import TaskComplexity, ModelProfile, SelectionResult
from aiworker.meta.task_classifier import classify
from aiworker.meta.model_selector import ModelSelector, DEFAULT_MODELS


class TestTaskClassifier(unittest.TestCase):
    def test_core_is_critical(self):
        self.assertEqual(classify("refactor core engine"), TaskComplexity.CRITICAL)

    def test_refactor_high_risk_critical(self):
        self.assertEqual(classify("refactor auth", risk_level="high"), TaskComplexity.CRITICAL)

    def test_refactor_low_risk_complex(self):
        self.assertEqual(classify("refactor auth", risk_level="low"), TaskComplexity.COMPLEX)

    def test_add_low_risk_simple_plan(self):
        self.assertEqual(classify("add logging", risk_level="low", plan_complexity=0.2), TaskComplexity.SIMPLE)

    def test_add_high_risk_complex(self):
        self.assertEqual(classify("add auth", risk_level="high", plan_complexity=0.4), TaskComplexity.COMPLEX)

    def test_fix_low_risk_simple(self):
        self.assertEqual(classify("fix login crash", risk_level="low"), TaskComplexity.SIMPLE)

    def test_fix_medium_risk_moderate(self):
        self.assertEqual(classify("fix login bug", risk_level="medium"), TaskComplexity.MODERATE)

    def test_rename_trivial(self):
        self.assertEqual(classify("rename variable"), TaskComplexity.TRIVIAL)

    def test_docstring_trivial(self):
        self.assertEqual(classify("add docstring to functions"), TaskComplexity.TRIVIAL)

    def test_high_plan_complexity_complex(self):
        self.assertEqual(classify("do something", plan_complexity=0.8), TaskComplexity.COMPLEX)

    def test_low_plan_complexity_simple(self):
        self.assertEqual(classify("do something", plan_complexity=0.2), TaskComplexity.SIMPLE)

    def test_many_files_escalates(self):
        self.assertEqual(classify("refactor auth", risk_level="high", num_files=5), TaskComplexity.CRITICAL)


class TestModelSelector(unittest.TestCase):
    def setUp(self):
        self.selector = ModelSelector()

    def test_returns_selection_result(self):
        self.assertIsInstance(self.selector.select("t1", "add logging"), SelectionResult)

    def test_trivial_gets_cheapest(self):
        result = self.selector.select("t1", "rename variable")
        self.assertEqual(result.complexity, TaskComplexity.TRIVIAL)
        cheapest_rank = min(m.cost_rank for m in DEFAULT_MODELS)
        self.assertEqual(result.selected_model.cost_rank, cheapest_rank)

    def test_critical_gets_best_quality(self):
        result = self.selector.select("t1", "refactor core engine pipeline")
        self.assertEqual(result.complexity, TaskComplexity.CRITICAL)
        best_quality = min(m.quality_rank for m in DEFAULT_MODELS)
        self.assertEqual(result.selected_model.quality_rank, best_quality)

    def test_frozen_result(self):
        result = self.selector.select("t1", "add logging")
        with self.assertRaises((AttributeError, TypeError)):
            result.complexity = TaskComplexity.TRIVIAL

    def test_to_dict_structure(self):
        d = self.selector.select("t1", "add feature").to_dict()
        for k in ("complexity","selected_model","reason","confidence"):
            self.assertIn(k, d)

    def test_confidence_bounded(self):
        r = self.selector.select("t1", "add feature")
        self.assertGreaterEqual(r.confidence, 0.0)
        self.assertLessEqual(r.confidence, 1.0)

    def test_deterministic(self):
        results = [self.selector.select("t1", "add logging") for _ in range(100)]
        first_id = results[0].selected_model.model_id
        for r in results[1:]:
            self.assertEqual(r.selected_model.model_id, first_id)

    def test_custom_model_registry(self):
        models = [
            ModelProfile("fast", "Fast", TaskComplexity.SIMPLE, 1, 1, 2),
            ModelProfile("smart", "Smart", TaskComplexity.CRITICAL, 2, 2, 1),
        ]
        sel = ModelSelector(models=models)
        result = sel.select("t1", "add feature")
        self.assertIn(result.selected_model.model_id, ("fast", "smart"))


if __name__ == "__main__":
    unittest.main()
