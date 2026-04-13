"""Deterministic model role strategy for autonomous dev loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModelRole(Enum):
    Planner = "planner"
    Generator = "generator"
    Corrector = "corrector"
    Validator = "validator"


@dataclass(frozen=True)
class ModelRouteConfig:
    planner_model: str
    generator_model: str
    corrector_model: str
    validator_model: str = "deterministic-python"


class ModelRouter:
    """Maps roles to models while enforcing role separation constraints."""

    def __init__(self, config: ModelRouteConfig) -> None:
        self._config = config
        self._validate_config()

    def _validate_config(self) -> None:
        models = {
            self._config.planner_model,
            self._config.generator_model,
            self._config.corrector_model,
            self._config.validator_model,
        }
        if len(models) == 1:
            raise ValueError("Single model cannot control the entire loop")
        if self._config.planner_model == self._config.generator_model == self._config.corrector_model:
            raise ValueError("Planner must be separated from generation/correction roles")

    def route(self, role: ModelRole) -> str:
        if role is ModelRole.Planner:
            return self._config.planner_model
        if role is ModelRole.Generator:
            return self._config.generator_model
        if role is ModelRole.Corrector:
            return self._config.corrector_model
        return self._config.validator_model


__all__ = ["ModelRole", "ModelRouteConfig", "ModelRouter"]
