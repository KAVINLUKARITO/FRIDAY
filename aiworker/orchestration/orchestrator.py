"""Deterministic task orchestrator.

Combines the planning, simulation, and scoring layers to produce a
:class:`TaskReport` for a given :class:`Task`.  No sandbox execution,
no database writes, no workspace modification, no auto-approval.
"""

from __future__ import annotations

from typing import Optional

from aiworker.memory.database import Database
from aiworker.orchestration.models import Task, TaskReport
from aiworker.planning.planner import generate_plan
from aiworker.planning.simulator import simulate_plan
from aiworker.scoring.decision_context import build_decision_context


def _infer_risk_level(goal: str) -> str:
    """Infer a risk level string from *goal* using the same rules as the planner."""
    lower = goal.lower()
    if "core" in lower:
        return "high"
    if len(goal) > 60:
        return "medium"
    return "low"


def process_task(
    task: Task,
    database: Optional[Database] = None,
) -> TaskReport:
    """Process a task through the planning, simulation, and scoring pipeline.

    This function is purely analytical — it does **not** execute any
    sandbox operations, write to any database, modify any workspace,
    or auto-approve anything.

    Args:
        task: The :class:`Task` to process.
        database: Optional :class:`Database` for historical scoring.
            When ``None``, scoring defaults are used (zero-history).

    Returns:
        A :class:`TaskReport` summarising the analysis.
    """
    # 1. Generate plan
    plan = generate_plan(task.goal)

    # 2. Simulate plan
    simulation = simulate_plan(plan)

    # 3. Compute decision context
    risk_level = _infer_risk_level(task.goal)
    if database is not None:
        decision = build_decision_context(database, task.goal, risk_level)
    else:
        decision = {
            "confidence_score": 0.4,
            "recommendation": "review_carefully",
            "historical_attempts": 0,
            "success_rate": 0.0,
            "risk_failure_rate": 0.0,
        }

    return TaskReport(
        task_id=task.task_id,
        plan_complexity=plan.complexity_score,
        simulation_success_probability=simulation.estimated_success_probability,
        confidence_score=decision["confidence_score"],
        recommendation=decision["recommendation"],
    )
