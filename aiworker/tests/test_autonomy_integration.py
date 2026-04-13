"""Integration tests for the autonomous repair pipeline.

Tests the full execution chain:
  debugger.capture → root_cause → reasoning.planner →
  deepseek_adapter → patch.validator → sandbox_verifier →
  regression_guard → learning.store

Covers:
- Deterministic resolution skips LLM
- JSON enforcement end-to-end
- Multi-pass retry logic
- Regression detection integration
- Confidence scoring integration
- Governance hooks (AI rate limiter, circuit breaker)
- Lesson storage after successful repair
- Full pipeline success and failure paths

Uses unittest only — no pytest dependency.
"""

from __future__ import annotations

import json
import textwrap
import unittest

from aiworker.debugger.capture import (
    FailureReport,
    capture_exception,
    capture_test_failure,
)
from aiworker.debugger.root_cause import (
    RootCauseResult,
    analyze,
)
from aiworker.reasoning.planner import (
    ReasoningPlan,
    create_plan,
)
from aiworker.llm.deepseek_adapter import (
    DeepSeekAdapter,
    DeepSeekResponse,
    StubBackend,
    _validate_response,
)
from aiworker.patch.validator import (
    PatchValidationResult,
    validate as validate_patch,
)
from aiworker.patch.sandbox_verifier import VerificationResult
from aiworker.patch.regression_guard import (
    RegressionDecision,
    check as regression_check,
)
from aiworker.learning.models import Lesson, _new_lesson_id, _utcnow_iso
from aiworker.learning.store import LearningStore
from aiworker.memory.database import Database


# ── Helpers ──────────────────────────────────────────────────


def _make_store() -> LearningStore:
    db = Database(":memory:")
    db.initialise()
    return LearningStore(db)


def _valid_diff() -> str:
    return textwrap.dedent("""\
        --- a/foo.py
        +++ b/foo.py
        @@ -1,2 +1,3 @@
         def foo():
             return 1
        +    # fixed
    """)


def _valid_json(diff: str = "") -> str:
    return json.dumps({
        "analysis": "Found the root cause",
        "diff": diff or _valid_diff(),
        "risk_score": 0.3,
    })


def _compute_confidence(
    pass_rate: float,
    risk_score: float,
    low_diff_bonus: float,
) -> float:
    return (
        pass_rate * 0.5
        + (1 - risk_score) * 0.3
        + low_diff_bonus * 0.2
    )


def _make_repair_lesson(
    failure_type: str = "ImportError",
    hypothesis: str = "Missing module",
    confidence: float = 0.7,
) -> Lesson:
    return Lesson(
        lesson_id=_new_lesson_id(),
        category="success_pattern",
        summary=f"Repaired {failure_type}",
        detail=f"Hypothesis: {hypothesis}",
        confidence=confidence,
        source_attempt_ids=("repair-1",),
        source_goal=f"Fix {failure_type}",
        applicable_goal_keywords=("fix", failure_type.lower()),
        created_at=_utcnow_iso(),
    )


# ── Deterministic resolution ─────────────────────────────────


class TestDeterministicResolution(unittest.TestCase):
    """Verify that deterministically resolved failures skip the LLM."""

    def test_import_error_resolved_without_llm(self) -> None:
        report = FailureReport(
            exception_type="ImportError",
            message="No module named 'missing'",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        root = analyze(report)
        self.assertTrue(root.resolved)
        self.assertEqual(root.category, "structural")
        # No need to create plan or call LLM

    def test_syntax_error_resolved_without_llm(self) -> None:
        report = FailureReport(
            exception_type="SyntaxError",
            message="SyntaxError: unexpected EOF",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        root = analyze(report)
        self.assertTrue(root.resolved)
        self.assertIsNotNone(root.suggested_fix)

    def test_unknown_error_delegates_to_llm(self) -> None:
        report = FailureReport(
            exception_type="RuntimeError",
            message="something bizarre",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        root = analyze(report)
        self.assertFalse(root.resolved)
        self.assertEqual(root.category, "unknown")
        # This would trigger the LLM path


# ── Full pipeline: capture → root_cause → plan → LLM → validate ─


class TestFullPipelineSuccess(unittest.TestCase):
    """Verify the full pipeline produces a valid repair."""

    def test_end_to_end_repair(self) -> None:
        # Step 1: Capture failure
        report = FailureReport(
            exception_type="RuntimeError",
            message="unexpected state",
            traceback='File "aiworker/foo.py", line 10',
            failing_tests=("test_foo::test_bar",),
            affected_files=("aiworker/foo.py",),
        )

        # Step 2: Root cause analysis (unresolved)
        root = analyze(report)
        self.assertFalse(root.resolved)

        # Step 3: Create plan
        plan = create_plan(report, root)
        self.assertGreater(plan.risk_score, 0.0)
        self.assertIn("RuntimeError", plan.hypothesis)

        # Step 4: Generate patch via LLM
        backend = StubBackend(_valid_json())
        adapter = DeepSeekAdapter(backend=backend)
        llm_response = adapter.generate(plan)
        self.assertTrue(llm_response.valid)

        # Step 5: Validate patch
        validation = validate_patch(llm_response.diff)
        self.assertTrue(validation.valid)

        # Step 6: Simulate verification (mock since we can't run real sandbox)
        verification = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
            execution_time=0.5,
        )

        # Step 7: Regression guard
        decision = regression_check(
            verification,
            risk_score=llm_response.risk_score,
        )
        self.assertTrue(decision.accepted)

        # Step 8: Store lesson
        store = _make_store()
        confidence = _compute_confidence(
            pass_rate=1.0,
            risk_score=llm_response.risk_score,
            low_diff_bonus=1.0,
        )
        lesson = _make_repair_lesson(
            failure_type=report.exception_type,
            hypothesis=plan.hypothesis,
            confidence=confidence,
        )
        store.insert_lesson(lesson)
        self.assertEqual(store.lesson_count(), 1)


class TestFullPipelineFailure(unittest.TestCase):
    """Verify failure paths in the pipeline."""

    def test_invalid_json_blocks_pipeline(self) -> None:
        report = FailureReport(
            exception_type="RuntimeError",
            message="unexpected",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        root = analyze(report)
        plan = create_plan(report, root)

        # LLM returns invalid JSON
        backend = StubBackend("I think the problem is...")
        adapter = DeepSeekAdapter(backend=backend)
        response = adapter.generate(plan)
        self.assertFalse(response.valid)
        # Pipeline stops — no validation or verification

    def test_forbidden_import_blocks_pipeline(self) -> None:
        # LLM generates a patch with eval()
        evil_diff = textwrap.dedent("""\
            --- a/foo.py
            +++ b/foo.py
            @@ -1 +1,2 @@
             x = 1
            +result = eval("malicious")
        """)
        response = _validate_response(json.dumps({
            "analysis": "fix",
            "diff": evil_diff,
            "risk_score": 0.2,
        }))
        self.assertTrue(response.valid)  # JSON is valid

        # But patch validation catches it
        validation = validate_patch(response.diff)
        self.assertFalse(validation.valid)
        self.assertTrue(any("eval" in e for e in validation.errors))


# ── Multi-pass retry logic ───────────────────────────────────


class TestMultiPassRetry(unittest.TestCase):
    """Verify multi-attempt repair loop."""

    def test_retry_on_invalid_json(self) -> None:
        backend = StubBackend("not json")
        adapter = DeepSeekAdapter(backend=backend, max_retries=3)
        response = adapter.generate(ReasoningPlan(
            hypothesis="test",
            affected_modules=(),
            risk_score=0.3,
            strategy="test",
        ))
        self.assertFalse(response.valid)
        self.assertEqual(adapter.total_calls, 3)

    def test_simulated_repair_loop(self) -> None:
        """Simulate the 3-attempt repair loop from the spec."""
        plan = ReasoningPlan(
            hypothesis="test bug",
            affected_modules=(),
            risk_score=0.4,
            strategy="fix it",
        )

        # Simulate: first 2 attempts fail validation, 3rd succeeds
        responses = [
            "invalid json",
            json.dumps({"analysis": "x"}),  # missing keys
            _valid_json(),
        ]
        attempt_idx = [0]

        class SequentialBackend:
            def generate(self, prompt: str) -> str:
                idx = attempt_idx[0]
                attempt_idx[0] += 1
                return responses[min(idx, len(responses) - 1)]

        adapter = DeepSeekAdapter(
            backend=SequentialBackend(),
            max_retries=3,
        )

        # First call gets invalid, retries, eventually gets valid
        # But our adapter retries within a single generate() call
        # with the same prompt, so let's test the outer loop
        success = False
        for attempt in range(3):
            response = adapter.generate(plan)
            if response.valid:
                validation = validate_patch(response.diff)
                if validation.valid:
                    success = True
                    break

        # Third attempt should succeed
        self.assertTrue(success)


# ── Regression detection ─────────────────────────────────────


class TestRegressionDetection(unittest.TestCase):
    """Verify regression detection through the pipeline."""

    def test_regression_blocks_acceptance(self) -> None:
        verification = VerificationResult(
            success=False,
            passed_tests=7,
            failed_tests=3,
            regression_detected=True,
        )
        decision = regression_check(verification, risk_score=0.3)
        self.assertFalse(decision.accepted)

    def test_no_regression_passes(self) -> None:
        verification = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        decision = regression_check(verification, risk_score=0.3)
        self.assertTrue(decision.accepted)

    def test_repeated_failure_type_blocked(self) -> None:
        verification = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        history = ["TypeError", "TypeError", "TypeError"]
        decision = regression_check(
            verification,
            risk_score=0.3,
            failure_history=history,
            current_failure_type="TypeError",
            max_repeat_failures=3,
        )
        self.assertFalse(decision.accepted)


# ── Governance hooks ─────────────────────────────────────────


class TestGovernanceHooks(unittest.TestCase):
    """Verify AI rate limiter and circuit breaker integration."""

    def test_ai_rate_limiter(self) -> None:
        """Simulate max 5 LLM calls per loop."""
        backend = StubBackend(_valid_json())
        adapter = DeepSeekAdapter(backend=backend)
        max_ai_calls = 5

        for _ in range(max_ai_calls):
            plan = ReasoningPlan(
                hypothesis="test",
                affected_modules=(),
                risk_score=0.3,
                strategy="fix",
            )
            adapter.generate(plan)

        self.assertEqual(adapter.total_calls, max_ai_calls)
        # In production, the loop would check total_calls < max_ai_calls
        # before making another call

    def test_circuit_breaker_integration(self) -> None:
        """Verify circuit breaker pattern with repeated failures."""
        from aiworker.governance.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)

        # Simulate 3 consecutive failures
        for _ in range(3):
            cb.record_failure()

        self.assertEqual(cb.state, "open")
        self.assertFalse(cb.can_proceed)

    def test_patch_frequency_limiting(self) -> None:
        """Verify rate limiter prevents excessive patching."""
        from aiworker.governance.rate_limiter import RateLimiter

        t = [0.0]
        rl = RateLimiter(
            max_attempts=3,
            window_seconds=60.0,
            clock=lambda: t[0],
        )

        for _ in range(3):
            rl.acquire()

        status = rl.check()
        self.assertFalse(status.allowed)


# ── Learning store integration ───────────────────────────────


class TestLearningStoreIntegration(unittest.TestCase):
    """Verify lessons are stored after successful repairs."""

    def test_lesson_stored_after_repair(self) -> None:
        store = _make_store()

        # Simulate successful repair
        lesson = _make_repair_lesson(
            failure_type="ImportError",
            hypothesis="Missing module dependency",
            confidence=0.85,
        )
        store.insert_lesson(lesson)

        # Verify retrieval
        retrieved = store.get_lesson_by_id(lesson.lesson_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.category, "success_pattern")
        self.assertAlmostEqual(retrieved.confidence, 0.85)

    def test_confidence_formula(self) -> None:
        """Verify confidence matches the spec formula."""
        pass_rate = 0.9
        risk_score = 0.3
        low_diff_bonus = 0.8

        confidence = _compute_confidence(pass_rate, risk_score, low_diff_bonus)
        expected = 0.9 * 0.5 + 0.7 * 0.3 + 0.8 * 0.2
        self.assertAlmostEqual(confidence, expected)

    def test_lesson_keyword_search(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_repair_lesson(
            failure_type="ImportError",
        ))
        results = store.get_lessons_for_keywords(["importerror"])
        self.assertEqual(len(results), 1)

    def test_multiple_repairs_accumulate(self) -> None:
        store = _make_store()
        for i in range(5):
            store.insert_lesson(_make_repair_lesson(
                failure_type=f"Error{i}",
                confidence=0.5 + i * 0.1,
            ))
        self.assertEqual(store.lesson_count(), 5)


# ── No side effects ──────────────────────────────────────────


class TestNoSideEffects(unittest.TestCase):
    """Verify no filesystem or network side effects."""

    def test_pipeline_no_file_writes(self) -> None:
        import os
        import tempfile

        workspace = tempfile.mkdtemp()
        try:
            before = os.listdir(workspace)

            # Run through the pipeline
            report = FailureReport(
                exception_type="RuntimeError",
                message="test",
                traceback="",
                failing_tests=(),
                affected_files=(),
            )
            root = analyze(report)
            plan = create_plan(report, root)
            backend = StubBackend(_valid_json())
            adapter = DeepSeekAdapter(backend=backend)
            adapter.generate(plan)

            store = _make_store()
            store.insert_lesson(_make_repair_lesson())

            after = os.listdir(workspace)
            self.assertEqual(before, after)
        finally:
            os.rmdir(workspace)


if __name__ == "__main__":
    unittest.main()
