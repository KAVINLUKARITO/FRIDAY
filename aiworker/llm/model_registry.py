"""Deterministic model registry for planner/executor selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal


Role = Literal["planner", "executor"]


@dataclass(frozen=True)
class ModelProfile:
    name: str
    role: Role
    max_context: int
    avg_latency_ms: int
    cost_weight: float
    reliability_score: float


class ModelRegistry:
    """Instance-scoped registry for model profiles."""

    def __init__(self) -> None:
        self._profiles_by_role: Dict[Role, ModelProfile] = {}
        self._profiles_in_order: List[ModelProfile] = []

    def register(self, profile: ModelProfile) -> None:
        if profile.role in self._profiles_by_role:
            existing = self._profiles_by_role[profile.role]
            if existing == profile:
                return
            self._profiles_in_order = [
                item for item in self._profiles_in_order if item.role != profile.role
            ]
        self._profiles_by_role[profile.role] = profile
        self._profiles_in_order.append(profile)

    def get_by_role(self, role: str) -> ModelProfile:
        if role == "planner":
            if role not in self._profiles_by_role:
                raise KeyError(f"Unknown model role: {role}")
            return self._profiles_by_role[role]
        if role == "executor":
            if role not in self._profiles_by_role:
                raise KeyError(f"Unknown model role: {role}")
            return self._profiles_by_role[role]
        raise KeyError(f"Unknown model role: {role}")

    def list_all(self) -> List[ModelProfile]:
        return list(self._profiles_in_order)
