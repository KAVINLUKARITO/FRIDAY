"""Deterministic environment model for outcome prediction."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from aiworker.world_model.world_state import get_world_state


def predict_outcomes(
    planned_actions: Iterable[str] | None = None,
    *,
    world_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate outcome probabilities and blockers for a candidate action set."""

    snapshot = dict(world_snapshot or get_world_state())
    actions = tuple(action.strip() for action in (planned_actions or ()) if action and action.strip())
    constraints = dict(snapshot.get("constraints", {}))
    resources = dict(snapshot.get("resources", {}))
    observations = dict(snapshot.get("observations", {}))

    blockers: list[str] = []
    if constraints.get("read_only"):
        blockers.append("read_only_mode")
    if resources.get("time_budget", 1.0) <= 0:
        blockers.append("no_time_budget")
    if not actions:
        blockers.append("no_actions")

    success_probability = 0.75
    success_probability -= min(len(blockers) * 0.15, 0.45)
    success_probability -= min(max(len(actions) - 3, 0) * 0.05, 0.2)
    if observations.get("recent_failures", 0):
        success_probability -= min(float(observations["recent_failures"]) * 0.05, 0.2)

    risk = min(1.0, max(0.0, 1.0 - success_probability + (0.05 * len(actions))))
    return {
        "predicted_success_probability": round(max(0.0, min(1.0, success_probability)), 4),
        "predicted_risk": round(risk, 4),
        "blockers": tuple(blockers),
        "recommended_actions": actions[:3],
    }
