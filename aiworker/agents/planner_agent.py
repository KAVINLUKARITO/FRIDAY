"""Planning agent."""

from __future__ import annotations

from typing import Any, Sequence

from aiworker.planning.planner import generate_plan


class PlannerAgent:
    role = "planner"

    def run(self, *, goal: str, allowed_files: Sequence[str], research_notes: Sequence[str] = ()) -> dict[str, Any]:
        plan = generate_plan(goal)
        return {
            "role": self.role,
            "goal": goal,
            "allowed_files": tuple(allowed_files),
            "steps": tuple(step.description for step in plan.steps),
            "complexity": plan.complexity_score,
            "research_notes": tuple(research_notes),
        }
