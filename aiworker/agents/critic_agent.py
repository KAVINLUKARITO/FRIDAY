"""Critic agent."""

from __future__ import annotations

from typing import Any, Mapping


class CriticAgent:
    role = "critic"

    def run(self, coder_payload: Mapping[str, Any]) -> dict[str, Any]:
        actions = tuple(coder_payload.get("actions", ()))
        concerns = []
        if len(actions) > 2:
            concerns.append("broad_change_surface")
        if not coder_payload.get("candidate_files"):
            concerns.append("missing_target_files")
        return {
            "role": self.role,
            "concerns": tuple(concerns),
            "approved": len(concerns) == 0,
        }
