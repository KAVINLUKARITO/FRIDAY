"""Coding agent."""

from __future__ import annotations

from typing import Any, Mapping


class CoderAgent:
    role = "coder"

    def run(self, plan_payload: Mapping[str, Any]) -> dict[str, Any]:
        steps = tuple(plan_payload.get("steps", ()))
        candidate_files = tuple(plan_payload.get("allowed_files", ()))
        actions = tuple(f"Implement: {step}" for step in steps[:3])
        return {
            "role": self.role,
            "candidate_files": candidate_files,
            "actions": actions,
            "confidence": round(0.55 + min(len(actions), 3) * 0.1, 4),
        }
