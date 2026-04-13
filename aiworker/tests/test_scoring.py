"""Tests for the confidence scoring & decision weighting system (Milestone 4).

Covers metric calculations, confidence formula, recommendation
thresholds, zero-history defaults, engine integration, and the
guarantee that scoring never influences approval.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import textwrap

import pytest

from aiworker.memory.database import Database
from aiworker.memory.repository import MemoryRepository
from aiworker.scoring.calculator import calculate_confidence
from aiworker.scoring.decision_context import build_decision_context
from aiworker.scoring.metrics import (
    average_execution_time,
    failure_rate_by_risk,
    success_rate,
    total_attempts,
)
from aiworker.self_modify.change_request import ChangeRequest
from aiworker.self_modify.engine import process_change_request


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _seeded_db() -> tuple[Database, MemoryRepository]:
    """Return an in-memory DB with a known set of historical records."""
    db = Database(":memory:")
    db.initialise()
    repo = MemoryRepository(db)

    # Attempt 1: goal="Add multiply", low risk, sandbox success, 2.0s
    a1 = repo.insert_change_attempt("Add multiply", "low", ["math.py"])
    repo.insert_validation_result(a1.id, True, "OK")
    repo.insert_sandbox_result(a1.id, True, 5, 0, 2.0)
    repo.insert_approval_result(a1.id, False, True, "needs review")

    # Attempt 2: goal="Add multiply", low risk, sandbox success, 4.0s
    a2 = repo.insert_change_attempt("Add multiply", "low", ["math.py"])
    repo.insert_validation_result(a2.id, True, "OK")
    repo.insert_sandbox_result(a2.id, True, 3, 0, 4.0)
    repo.insert_approval_result(a2.id, True, True, "approved")

    # Attempt 3: goal="Add multiply", low risk, sandbox FAILURE, 1.0s
    a3 = repo.insert_change_attempt("Add multiply", "low", ["math.py"])
    repo.insert_validation_result(a3.id, True, "OK")
    repo.insert_sandbox_result(a3.id, False, 0, 3, 1.0)
    repo.insert_approval_result(a3.id, False, True, "sandbox failed")

    # Attempt 4: goal="Fix division", high risk, sandbox FAILURE, 10.0s
    a4 = repo.insert_change_attempt("Fix division", "high", ["math.py"])
    repo.insert_validation_result(a4.id, True, "OK")
    repo.insert_sandbox_result(a4.id, False, 1, 2, 10.0)
    repo.insert_approval_result(a4.id, False, True, "high risk + failure")

    # Attempt 5: goal="Fix division", high risk, sandbox success, 5.0s
    a5 = repo.insert_change_attempt("Fix division", "high", ["math.py"])
    repo.insert_validation_result(a5.id, True, "OK")
    repo.insert_sandbox_result(a5.id, True, 4, 0, 5.0)
    repo.insert_approval_result(a5.id, False, True, "high risk")

    return db, repo


# ---------------------------------------------------------------
# 1. Metrics: success_rate
# ---------------------------------------------------------------


class TestSuccessRate:
    """Verify success_rate calculation."""

    def test_success_rate_with_history(self) -> None:
        """success_rate must count only successful sandbox runs."""
        db, _ = _seeded_db()
        # "Add multiply": 3 sandbox runs, 2 success → 2/3
        rate = success_rate(db, "Add multiply")
        assert abs(rate - 2.0 / 3.0) < 0.001

    def test_success_rate_zero_history(self) -> None:
        """success_rate with no history must return 0.0."""
        db = Database(":memory:")
        db.initialise()
        assert success_rate(db, "nonexistent") == 0.0

    def test_success_rate_all_failures(self) -> None:
        """success_rate when every sandbox run failed must return 0.0."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)
        a = repo.insert_change_attempt("fail goal", "low", ["a.py"])
        repo.insert_sandbox_result(a.id, False, 0, 1, 1.0)
        assert success_rate(db, "fail goal") == 0.0

    def test_success_rate_all_pass(self) -> None:
        """success_rate when every sandbox run succeeded must return 1.0."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)
        for _ in range(3):
            a = repo.insert_change_attempt("pass goal", "low", ["a.py"])
            repo.insert_sandbox_result(a.id, True, 5, 0, 1.0)
        assert success_rate(db, "pass goal") == 1.0


# ---------------------------------------------------------------
# 2. Metrics: failure_rate_by_risk
# ---------------------------------------------------------------


class TestFailureRateByRisk:
    """Verify failure_rate_by_risk calculation."""

    def test_failure_rate_high_risk(self) -> None:
        """High risk: 2 sandbox runs, 1 failure → 0.5."""
        db, _ = _seeded_db()
        rate = failure_rate_by_risk(db, "high")
        assert abs(rate - 0.5) < 0.001

    def test_failure_rate_low_risk(self) -> None:
        """Low risk: 3 sandbox runs, 1 failure → 1/3."""
        db, _ = _seeded_db()
        rate = failure_rate_by_risk(db, "low")
        assert abs(rate - 1.0 / 3.0) < 0.001

    def test_failure_rate_zero_history(self) -> None:
        """failure_rate with no history must return 0.0."""
        db = Database(":memory:")
        db.initialise()
        assert failure_rate_by_risk(db, "medium") == 0.0


# ---------------------------------------------------------------
# 3. Metrics: average_execution_time
# ---------------------------------------------------------------


class TestAverageExecutionTime:
    """Verify average_execution_time calculation."""

    def test_avg_time_with_history(self) -> None:
        """Average of 2.0, 4.0, 1.0 = 2.333..."""
        db, _ = _seeded_db()
        avg = average_execution_time(db, "Add multiply")
        assert abs(avg - 7.0 / 3.0) < 0.01

    def test_avg_time_zero_history(self) -> None:
        """No history → 0.0."""
        db = Database(":memory:")
        db.initialise()
        assert average_execution_time(db, "nonexistent") == 0.0


# ---------------------------------------------------------------
# 4. Metrics: total_attempts
# ---------------------------------------------------------------


class TestTotalAttempts:
    """Verify total_attempts count."""

    def test_total_attempts_with_history(self) -> None:
        """'Add multiply' has 3 attempts."""
        db, _ = _seeded_db()
        assert total_attempts(db, "Add multiply") == 3

    def test_total_attempts_zero_history(self) -> None:
        """No matching history → 0."""
        db = Database(":memory:")
        db.initialise()
        assert total_attempts(db, "nonexistent") == 0


# ---------------------------------------------------------------
# 5. Calculator: confidence score
# ---------------------------------------------------------------


class TestConfidenceCalculator:
    """Verify confidence formula and bounds."""

    def test_confidence_zero_history(self) -> None:
        """With no history, confidence must be in [0, 1] and safe."""
        db = Database(":memory:")
        db.initialise()
        c = calculate_confidence(db, "new goal", "low")
        assert 0.0 <= c <= 1.0
        # S=0, F=0, T=0, N=0 → 0.5*0 + 0.2*(1-0) + 0.2*(1-0) + 0.1*0 = 0.4
        assert abs(c - 0.4) < 0.001

    def test_confidence_bounded_upper(self) -> None:
        """Confidence must never exceed 1.0."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)
        # Create 20 all-success attempts at 0s execution time
        for i in range(20):
            a = repo.insert_change_attempt("perfect goal", "low", ["a.py"])
            repo.insert_sandbox_result(a.id, True, 5, 0, 0.0)
        c = calculate_confidence(db, "perfect goal", "low")
        assert c <= 1.0

    def test_confidence_bounded_lower(self) -> None:
        """Confidence must never go below 0.0."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)
        # All failures at max time
        for i in range(20):
            a = repo.insert_change_attempt("bad goal", "high", ["a.py"])
            repo.insert_sandbox_result(a.id, False, 0, 5, 120.0)
        c = calculate_confidence(db, "bad goal", "high")
        assert c >= 0.0

    def test_confidence_deterministic(self) -> None:
        """Same database state must produce same confidence score."""
        db, _ = _seeded_db()
        c1 = calculate_confidence(db, "Add multiply", "low")
        c2 = calculate_confidence(db, "Add multiply", "low")
        assert c1 == c2

    def test_confidence_increases_with_success(self) -> None:
        """Adding successful history must increase or maintain confidence."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)

        c_before = calculate_confidence(db, "grow goal", "low")

        for _ in range(5):
            a = repo.insert_change_attempt("grow goal", "low", ["a.py"])
            repo.insert_sandbox_result(a.id, True, 5, 0, 1.0)

        c_after = calculate_confidence(db, "grow goal", "low")
        assert c_after >= c_before

    def test_confidence_formula_manual(self) -> None:
        """Verify the formula with known inputs."""
        db, _ = _seeded_db()
        # "Add multiply", "low" risk:
        # S = 2/3 ≈ 0.6667
        # F = failure_rate_by_risk("low") = 1/3 ≈ 0.3333
        # T = avg(2,4,1)/120 = 7/3/120 ≈ 0.01944
        # N = min(3/10, 1) = 0.3
        #
        # confidence = 0.5*0.6667 + 0.2*(1-0.3333) + 0.2*(1-0.01944) + 0.1*0.3
        #            = 0.33335 + 0.13334 + 0.196112 + 0.03
        #            = 0.692802
        c = calculate_confidence(db, "Add multiply", "low")
        assert abs(c - 0.6928) < 0.01


# ---------------------------------------------------------------
# 6. Decision context
# ---------------------------------------------------------------


class TestDecisionContext:
    """Verify build_decision_context output structure and thresholds."""

    def test_context_structure(self) -> None:
        """Returned dict must contain all required keys."""
        db, _ = _seeded_db()
        ctx = build_decision_context(db, "Add multiply", "low")
        assert "confidence_score" in ctx
        assert "recommendation" in ctx
        assert "historical_attempts" in ctx
        assert "success_rate" in ctx
        assert "risk_failure_rate" in ctx

    def test_recommendation_proceed(self) -> None:
        """High confidence → proceed."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)
        for _ in range(15):
            a = repo.insert_change_attempt("stable goal", "low", ["a.py"])
            repo.insert_sandbox_result(a.id, True, 5, 0, 0.5)
        ctx = build_decision_context(db, "stable goal", "low")
        assert ctx["confidence_score"] >= 0.75
        assert ctx["recommendation"] == "proceed"

    def test_recommendation_review_carefully(self) -> None:
        """Medium confidence → review_carefully."""
        db = Database(":memory:")
        db.initialise()
        # No history: confidence = 0.4 (exactly at boundary)
        ctx = build_decision_context(db, "new goal", "low")
        assert 0.4 <= ctx["confidence_score"] < 0.75
        assert ctx["recommendation"] == "review_carefully"

    def test_recommendation_high_risk(self) -> None:
        """Low confidence → high_risk."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)
        # All failures, high risk, max execution time
        for _ in range(10):
            a = repo.insert_change_attempt("failing goal", "high", ["a.py"])
            repo.insert_sandbox_result(a.id, False, 0, 5, 120.0)
        ctx = build_decision_context(db, "failing goal", "high")
        assert ctx["confidence_score"] < 0.4
        assert ctx["recommendation"] == "high_risk"

    def test_context_zero_history(self) -> None:
        """Zero history must return safe defaults."""
        db = Database(":memory:")
        db.initialise()
        ctx = build_decision_context(db, "brand new", "medium")
        assert ctx["historical_attempts"] == 0
        assert ctx["success_rate"] == 0.0
        assert ctx["risk_failure_rate"] == 0.0
        assert 0.0 <= ctx["confidence_score"] <= 1.0

    def test_historical_changes_influence_score(self) -> None:
        """Adding history must change the confidence score."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)

        ctx_before = build_decision_context(db, "evolving goal", "low")

        for _ in range(5):
            a = repo.insert_change_attempt("evolving goal", "low", ["a.py"])
            repo.insert_sandbox_result(a.id, True, 5, 0, 1.0)

        ctx_after = build_decision_context(db, "evolving goal", "low")
        assert ctx_after["confidence_score"] != ctx_before["confidence_score"]
        assert ctx_after["historical_attempts"] > ctx_before["historical_attempts"]


# ---------------------------------------------------------------
# 7. Engine integration
# ---------------------------------------------------------------


class TestEngineIntegration:
    """Verify engine includes decision_context and approval is unchanged."""

    @staticmethod
    def _make_workspace() -> str:
        d = tempfile.mkdtemp(prefix="score_ws_")
        ws = os.path.join(d, "workspace")
        os.makedirs(ws)
        with open(os.path.join(ws, "math_utils.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        with open(os.path.join(ws, "test_math_utils.py"), "w") as f:
            f.write(textwrap.dedent("""\
                from math_utils import add
                def test_add():
                    assert add(1, 2) == 3
            """))
        return ws

    VALID_PATCH = textwrap.dedent("""\
        --- a/math_utils.py
        +++ b/math_utils.py
        @@ -1,2 +1,6 @@
         def add(a, b):
             return a + b
        +
        +
        +def multiply(a, b):
        +    return a * b
    """)

    def test_engine_includes_decision_context(self) -> None:
        """Engine result must include decision_context when database is provided."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        cr = ChangeRequest(
            goal="Add multiply",
            allowed_files=["math_utils.py", "test_math_utils.py"],
            max_lines_changed=50,
            tests_required=False,
            risk_level="low",
        )
        try:
            result = process_change_request(
                cr, self.VALID_PATCH, ws, timeout=60, database=db,
            )
            assert result.decision_context is not None
            assert "confidence_score" in result.decision_context
            assert "recommendation" in result.decision_context
            assert "historical_attempts" in result.decision_context
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_engine_no_context_without_database(self) -> None:
        """Engine result must have no decision_context when no database."""
        ws = self._make_workspace()
        cr = ChangeRequest(
            goal="No DB",
            allowed_files=["math_utils.py"],
            max_lines_changed=50,
            tests_required=False,
            risk_level="low",
        )
        try:
            result = process_change_request(cr, self.VALID_PATCH, ws, timeout=60)
            assert result.decision_context is None
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_decision_context_in_to_dict(self) -> None:
        """to_dict() must include decision_context key."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        cr = ChangeRequest(
            goal="Dict test",
            allowed_files=["math_utils.py", "test_math_utils.py"],
            max_lines_changed=50,
            tests_required=False,
            risk_level="low",
        )
        try:
            result = process_change_request(
                cr, self.VALID_PATCH, ws, timeout=60, database=db,
            )
            d = result.to_dict()
            assert "decision_context" in d
            assert d["decision_context"] is not None
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_approval_unchanged_by_confidence(self) -> None:
        """High confidence must NOT auto-approve without explicit_approval."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)

        # Seed with strong history so confidence is high
        for _ in range(15):
            a = repo.insert_change_attempt("Add multiply", "low", ["math.py"])
            repo.insert_sandbox_result(a.id, True, 5, 0, 0.5)

        cr = ChangeRequest(
            goal="Add multiply",
            allowed_files=["math_utils.py", "test_math_utils.py"],
            max_lines_changed=50,
            tests_required=False,
            risk_level="low",
        )
        try:
            result = process_change_request(
                cr, self.VALID_PATCH, ws, timeout=60, database=db,
            )
            # Confidence should be high
            assert result.decision_context is not None
            assert result.decision_context["confidence_score"] >= 0.75
            # But still NOT auto-approved (no explicit_approval)
            assert result.approved is False
            assert result.approval_required is True
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_confidence_does_not_auto_approve(self) -> None:
        """Even perfect confidence must never auto-approve."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)

        # Create extremely strong history
        for _ in range(20):
            a = repo.insert_change_attempt("Add multiply", "low", ["math.py"])
            repo.insert_sandbox_result(a.id, True, 10, 0, 0.1)

        cr = ChangeRequest(
            goal="Add multiply",
            allowed_files=["math_utils.py", "test_math_utils.py"],
            max_lines_changed=50,
            tests_required=False,
            risk_level="low",
        )
        try:
            result = process_change_request(
                cr, self.VALID_PATCH, ws, timeout=60, database=db,
            )
            assert result.approved is False
            assert result.approval_required is True
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_validation_failure_includes_context(self) -> None:
        """Even validation failures should include decision_context."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        cr = ChangeRequest(
            goal="Bad patch",
            allowed_files=["math_utils.py"],
            max_lines_changed=5,
            risk_level="low",
        )
        bad_patch = "--- a/../../etc/passwd\n+++ b/../../etc/passwd\n@@ -0,0 +1 @@\n+hacked\n"
        try:
            result = process_change_request(
                cr, bad_patch, ws, timeout=60, database=db,
            )
            assert result.decision_context is not None
            assert result.approved is False
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)


# ---------------------------------------------------------------
# 8. Scoring is read-only
# ---------------------------------------------------------------


class TestScoringReadOnly:
    """Verify scoring layer does not write to the database."""

    def test_metrics_do_not_write(self) -> None:
        """Calling all metric functions must not insert any records."""
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)

        # Seed one record
        a = repo.insert_change_attempt("test goal", "low", ["a.py"])
        repo.insert_sandbox_result(a.id, True, 5, 0, 1.0)

        # Call all metrics
        success_rate(db, "test goal")
        failure_rate_by_risk(db, "low")
        average_execution_time(db, "test goal")
        total_attempts(db, "test goal")
        calculate_confidence(db, "test goal", "low")
        build_decision_context(db, "test goal", "low")

        # Verify record count unchanged
        assert len(repo.get_last_n_attempts(100)) == 1
