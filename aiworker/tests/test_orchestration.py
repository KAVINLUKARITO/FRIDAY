"""Tests for the task orchestration layer (Milestone 7).

Covers:
- TaskQueue FIFO behaviour
- Task lifecycle (pending → processed)
- process_task integration with planning, simulation, scoring
- Deterministic behaviour
- No workspace modification
"""

from __future__ import annotations

import os
import tempfile

import pytest

from aiworker.memory.database import Database
from aiworker.orchestration.models import Task, TaskReport
from aiworker.orchestration.queue import TaskQueue
from aiworker.orchestration.orchestrator import process_task


# ── TaskQueue: add_task ──────────────────────────────────────

class TestTaskQueueAdd:
    """Verify task creation and enqueueing."""

    def test_add_task_returns_task(self) -> None:
        q = TaskQueue()
        task = q.add_task("add feature")
        assert isinstance(task, Task)

    def test_add_task_sets_pending(self) -> None:
        q = TaskQueue()
        task = q.add_task("fix bug")
        assert task.status == "pending"

    def test_add_task_stores_goal(self) -> None:
        q = TaskQueue()
        task = q.add_task("refactor core")
        assert task.goal == "refactor core"

    def test_add_task_unique_ids(self) -> None:
        q = TaskQueue()
        t1 = q.add_task("a")
        t2 = q.add_task("b")
        assert t1.task_id != t2.task_id


# ── TaskQueue: FIFO retrieval ────────────────────────────────

class TestTaskQueueFIFO:
    """Verify tasks are retrieved in insertion order."""

    def test_get_next_returns_first(self) -> None:
        q = TaskQueue()
        t1 = q.add_task("first")
        q.add_task("second")
        assert q.get_next_task() is t1

    def test_get_next_empty_returns_none(self) -> None:
        q = TaskQueue()
        assert q.get_next_task() is None

    def test_fifo_order_after_mark(self) -> None:
        q = TaskQueue()
        t1 = q.add_task("first")
        t2 = q.add_task("second")
        q.mark_processed(t1.task_id)
        assert q.get_next_task() is t2


# ── TaskQueue: mark_processed ────────────────────────────────

class TestTaskQueueProcessed:
    """Verify marking tasks as processed."""

    def test_mark_processed_reduces_count(self) -> None:
        q = TaskQueue()
        t = q.add_task("goal")
        assert q.pending_count() == 1
        q.mark_processed(t.task_id)
        assert q.pending_count() == 0

    def test_mark_unknown_raises(self) -> None:
        q = TaskQueue()
        with pytest.raises(KeyError):
            q.mark_processed("nonexistent")


# ── TaskQueue: pending_count ─────────────────────────────────

class TestTaskQueueCount:
    """Verify pending count accuracy."""

    def test_empty_queue_count(self) -> None:
        q = TaskQueue()
        assert q.pending_count() == 0

    def test_count_after_adds(self) -> None:
        q = TaskQueue()
        q.add_task("a")
        q.add_task("b")
        q.add_task("c")
        assert q.pending_count() == 3

    def test_count_after_mixed_ops(self) -> None:
        q = TaskQueue()
        t1 = q.add_task("a")
        q.add_task("b")
        q.mark_processed(t1.task_id)
        q.add_task("c")
        assert q.pending_count() == 2


# ── process_task: basic contract ─────────────────────────────

class TestProcessTaskContract:
    """Verify process_task returns correct type and structure."""

    def test_returns_task_report(self) -> None:
        task = Task(task_id="t1", goal="add logging")
        report = process_task(task)
        assert isinstance(report, TaskReport)

    def test_report_task_id_matches(self) -> None:
        task = Task(task_id="t1", goal="fix bug")
        report = process_task(task)
        assert report.task_id == "t1"

    def test_report_frozen(self) -> None:
        task = Task(task_id="t1", goal="add feature")
        report = process_task(task)
        with pytest.raises(AttributeError):
            report.recommendation = "changed"  # type: ignore[misc]


# ── process_task: plan integration ───────────────────────────

class TestPlanIntegration:
    """Verify plan complexity is correctly propagated."""

    def test_complexity_from_add_goal(self) -> None:
        task = Task(task_id="t1", goal="add feature")
        report = process_task(task)
        # "add" produces 4 steps → complexity = 4/10 = 0.4
        assert report.plan_complexity == 0.4

    def test_complexity_from_default_goal(self) -> None:
        task = Task(task_id="t1", goal="improve something")
        report = process_task(task)
        # default produces 3 steps → complexity = 3/10 = 0.3
        assert report.plan_complexity == 0.3


# ── process_task: simulation integration ─────────────────────

class TestSimulationIntegration:
    """Verify simulation results are correctly propagated."""

    def test_success_probability_bounded(self) -> None:
        task = Task(task_id="t1", goal="add feature")
        report = process_task(task)
        assert 0.0 <= report.simulation_success_probability <= 1.0

    def test_high_risk_goal_lower_success(self) -> None:
        safe_task = Task(task_id="t1", goal="add feature")
        risky_task = Task(task_id="t2", goal="refactor core engine")
        safe_report = process_task(safe_task)
        risky_report = process_task(risky_task)
        assert risky_report.simulation_success_probability < safe_report.simulation_success_probability


# ── process_task: decision context integration ───────────────

class TestDecisionContextIntegration:
    """Verify scoring layer integration."""

    def test_confidence_without_db(self) -> None:
        task = Task(task_id="t1", goal="add feature")
        report = process_task(task)
        # Without DB → zero-history defaults: confidence = 0.4
        assert report.confidence_score == 0.4

    def test_recommendation_without_db(self) -> None:
        task = Task(task_id="t1", goal="add feature")
        report = process_task(task)
        assert report.recommendation == "review_carefully"

    def test_confidence_with_db(self) -> None:
        db = Database(":memory:")
        db.initialise()
        task = Task(task_id="t1", goal="add feature")
        report = process_task(task, database=db)
        # Zero-history DB → confidence = 0.4
        assert report.confidence_score == 0.4

    def test_confidence_bounded(self) -> None:
        db = Database(":memory:")
        db.initialise()
        task = Task(task_id="t1", goal="add feature")
        report = process_task(task, database=db)
        assert 0.0 <= report.confidence_score <= 1.0


# ── determinism ──────────────────────────────────────────────

class TestDeterminism:
    """Verify identical input produces identical output."""

    def test_deterministic_100_calls(self) -> None:
        task = Task(task_id="t1", goal="add caching layer")
        reports = [process_task(task) for _ in range(100)]
        first = reports[0]
        for r in reports[1:]:
            assert r.plan_complexity == first.plan_complexity
            assert r.simulation_success_probability == first.simulation_success_probability
            assert r.confidence_score == first.confidence_score
            assert r.recommendation == first.recommendation


# ── no workspace modification ────────────────────────────────

class TestNoWorkspaceModification:
    """Verify process_task does not write to filesystem."""

    def test_workspace_not_modified(self) -> None:
        workspace = tempfile.mkdtemp()
        marker = os.path.join(workspace, "marker.txt")
        with open(marker, "w") as f:
            f.write("original")

        before = os.listdir(workspace)
        with open(marker) as f:
            content_before = f.read()

        task = Task(task_id="t1", goal="add feature")
        process_task(task)

        after = os.listdir(workspace)
        with open(marker) as f:
            content_after = f.read()

        assert before == after
        assert content_before == content_after

        # Cleanup
        os.remove(marker)
        os.rmdir(workspace)
