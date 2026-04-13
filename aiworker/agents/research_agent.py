"""Research agent."""

from __future__ import annotations

from typing import Any, Sequence


class ResearchAgent:
    role = "research"

    def run(self, *, goal: str, allowed_files: Sequence[str]) -> dict[str, Any]:
        hypotheses = (
            f"Focus on files: {', '.join(allowed_files) if allowed_files else 'no file targets provided'}",
            f"Goal keywords: {goal.lower()}",
        )
        findings = (
            "Reuse prior successful patterns before broad edits.",
            "Prefer small validated patches for high-confidence improvement.",
        )
        return {
            "role": self.role,
            "hypotheses": hypotheses,
            "findings": findings,
        }
