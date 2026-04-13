"""Tests for Phase 5 — Self-Evaluation and Experiment Tracking (unittest)."""
from __future__ import annotations
import unittest

from aiworker.experiment.models import (
    BenchmarkResult, Experiment, ExperimentStatus, Variant
)
from aiworker.experiment.benchmark import (
    BenchmarkRegistry, STANDARD_BENCHMARKS, _default_evaluator
)
from aiworker.experiment.tracker import ExperimentDatabase, ExperimentTracker
from aiworker.experiment.evaluator import SelfEvaluator


def _make_variants():
    return Variant("va","Strategy A","refactor-first"), Variant("vb","Strategy B","test-first")

def _result(score=0.9, passed=True):
    return BenchmarkResult("bm-type-hints","at-1",score,passed,"notes",0.1)


class TestBenchmarkRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = BenchmarkRegistry()

    def test_all_standard_registered(self):
        self.assertEqual(len(self.reg.all_benchmarks()), len(STANDARD_BENCHMARKS))

    def test_get_known(self):
        bm = self.reg.get("bm-type-hints")
        self.assertIsNotNone(bm)
        self.assertEqual(bm.skill_area, "typing")

    def test_get_unknown_none(self):
        self.assertIsNone(self.reg.get("nope"))

    def test_evaluate_returns_result(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n" * 3
        result = self.reg.evaluate("bm-type-hints", code)
        self.assertIsInstance(result, BenchmarkResult)

    def test_unknown_benchmark_score_zero(self):
        r = self.reg.evaluate("fake", "code")
        self.assertEqual(r.score, 0.0)
        self.assertFalse(r.passed)

    def test_custom_evaluator_used(self):
        called = {"n": 0}
        def my_eval(task, code): called["n"] += 1; return 1.0, "perfect"
        self.reg.register_evaluator("bm-type-hints", my_eval)
        self.reg.evaluate("bm-type-hints", "x")
        self.assertEqual(called["n"], 1)

    def test_type_hints_code_passes(self):
        code = "def f(x: int) -> int:\n    return x\n" * 4
        r = self.reg.evaluate("bm-type-hints", code)
        self.assertTrue(r.passed)

    def test_empty_code_fails(self):
        r = self.reg.evaluate("bm-type-hints", "")
        self.assertFalse(r.passed)


class TestDefaultEvaluator(unittest.TestCase):
    def _bm(self, skill_area):
        for b in STANDARD_BENCHMARKS:
            if b.skill_area == skill_area:
                return b
        return STANDARD_BENCHMARKS[0]

    def test_typing_with_hints_high_score(self):
        score, _ = _default_evaluator(self._bm("typing"), "def f(a: int) -> str: return str(a)" * 3)
        self.assertGreaterEqual(score, 0.5)

    def test_testing_with_tests_high_score(self):
        score, _ = _default_evaluator(self._bm("testing"), "def test_add():\n    assert 1+1==2\n" * 3)
        self.assertGreaterEqual(score, 0.5)

    def test_error_handling_high_score(self):
        code = "try:\n    pass\nexcept ValueError:\n    raise\n" * 3
        score, _ = _default_evaluator(self._bm("error_handling"), code)
        self.assertGreaterEqual(score, 0.5)

    def test_score_clamped_0_1(self):
        for bm in STANDARD_BENCHMARKS:
            score, _ = _default_evaluator(bm, "def f(a:int)->int: return a\n" * 5)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class TestExperimentTracker(unittest.TestCase):
    def setUp(self):
        db = ExperimentDatabase(":memory:")
        db.initialise()
        self.tracker = ExperimentTracker(db)

    def test_create_experiment(self):
        va, vb = _make_variants()
        exp = self.tracker.create_experiment("E","H",va,vb)
        self.assertIsNotNone(exp.experiment_id)
        self.assertEqual(exp.status, ExperimentStatus.PENDING)

    def test_record_and_retrieve_result(self):
        va, vb = _make_variants()
        exp = self.tracker.create_experiment("E","H",va,vb)
        self.tracker.record_result(exp.experiment_id, "a", _result(0.9))
        results = self.tracker.get_results(exp.experiment_id, "a")
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0].score, 0.9)

    def test_conclude_picks_winner(self):
        va, vb = _make_variants()
        exp = self.tracker.create_experiment("E","H",va,vb)
        for _ in range(3):
            self.tracker.record_result(exp.experiment_id, "a", _result(0.9, True))
            self.tracker.record_result(exp.experiment_id, "b", _result(0.3, False))
        winner = self.tracker.conclude(exp)
        self.assertEqual(winner, "a")

    def test_conclude_tie(self):
        va, vb = _make_variants()
        exp = self.tracker.create_experiment("E","H",va,vb)
        for _ in range(2):
            self.tracker.record_result(exp.experiment_id, "a", _result(0.8, True))
            self.tracker.record_result(exp.experiment_id, "b", _result(0.8, True))
        winner = self.tracker.conclude(exp)
        self.assertEqual(winner, "tie")

    def test_mean_score_empty_is_zero(self):
        va, vb = _make_variants()
        exp = self.tracker.create_experiment("E","H",va,vb)
        self.assertEqual(exp.mean_score([]), 0.0)

    def test_to_dict_structure(self):
        va, vb = _make_variants()
        exp = self.tracker.create_experiment("E","H",va,vb)
        d = exp.to_dict()
        for k in ("experiment_id","status","winner"):
            self.assertIn(k, d)


class TestSelfEvaluator(unittest.TestCase):
    def setUp(self):
        self.evaluator = SelfEvaluator()

    def test_evaluate_all_has_all_benchmarks(self):
        code = "def f(a: int) -> int:\n    return a\n" * 3
        results = self.evaluator.evaluate_all(code)
        self.assertEqual(len(results), len(STANDARD_BENCHMARKS))

    def test_evaluate_one_returns_result(self):
        r = self.evaluator.evaluate_one("bm-type-hints", "def f(x:int)->int: return x\n" * 3)
        self.assertIsInstance(r, BenchmarkResult)

    def test_skill_summary_has_all_skills(self):
        summary = self.evaluator.skill_summary()
        self.assertGreater(len(summary), 0)
        for v in summary.values():
            self.assertIsInstance(v, float)

    def test_overall_mastery_bounded(self):
        m = self.evaluator.overall_mastery()
        self.assertGreaterEqual(m, 0.0)
        self.assertLessEqual(m, 1.0)

    def test_mastery_improves_with_good_code(self):
        before = self.evaluator.overall_mastery()
        good = (
            "def f(a: int, b: int) -> int:\n"
            "    try:\n        return a + b\n    except Exception:\n        raise\n"
            "\ndef test_f():\n    assert f(1,2)==3\n"
        ) * 5
        for _ in range(5):
            self.evaluator.evaluate_all(good)
        after = self.evaluator.overall_mastery()
        self.assertGreaterEqual(after, before)

    def test_deterministic_evaluation(self):
        code = "def f(x: int) -> int: return x\n" * 3
        r1 = self.evaluator.evaluate_one("bm-type-hints", code)
        r2 = self.evaluator.evaluate_one("bm-type-hints", code)
        self.assertEqual(r1.score, r2.score)


if __name__ == "__main__":
    unittest.main()
