"""Data models for the task orchestration layer.

Provides immutable dataclasses for tasks and task reports.
No execution logic, no database access, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TaskStatus = Literal["pending", "processed"]


@dataclass(frozen=True)
class Task:
    """A unit of work to be processed by the orchestrator.

    Attributes:
        task_id: Unique identifier for this task.
        goal: Human-readable goal description.
        status: Current processing status.
    """

    task_id: str
    goal: str
    status: TaskStatus = "pending"


@dataclass(frozen=True)
class TaskReport:
    """Structured report produced after processing a task.

    Attributes:
        task_id: Identifier of the processed task.
        plan_complexity: Complexity score from the generated plan ``[0, 1]``.
        simulation_success_probability: Estimated success ``[0, 1]``.
        confidence_score: Historical confidence from scoring layer ``[0, 1]``.
        recommendation: Decision recommendation string.
    """

    task_id: str
    plan_complexity: float
    simulation_success_probability: float
    confidence_score: float
    recommendation: str
