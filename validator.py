from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from tools import TOOL_REGISTRY


@dataclass
class Action:
    tool_name: str
    parameters: dict[str, Any]
    reason: str
    step_number: int


@dataclass
class ValidatedAction:
    tool_name: str
    parameters: dict[str, Any]
    reason: str
    step_number: int
    checksum: str


class ValidationError(Exception):
    """Raised when an action fails validation."""


class Validator:
    """Validate planner output before execution."""

    def validate(self, raw: dict[str, Any]) -> ValidatedAction:
        if not isinstance(raw, dict):
            raise ValidationError("action must be a dict")
        try:
            action = Action(
                tool_name=str(raw["tool_name"]),
                parameters=dict(raw["parameters"]),
                reason=str(raw["reason"]),
                step_number=int(raw["step_number"]),
            )
        except Exception as exc:
            raise ValidationError(str(exc)) from exc

        if action.tool_name not in TOOL_REGISTRY:
            raise ValidationError(f"unknown tool: {action.tool_name}")
        if not action.parameters:
            raise ValidationError("parameters must be a non-empty dict")
        if not isinstance(action.reason, str) or not action.reason.strip():
            raise ValidationError("reason must be a non-empty string")
        if action.step_number < 1:
            raise ValidationError("step_number must be >= 1")

        serialized_parameters = json.dumps(
            action.parameters,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        checksum = hashlib.sha256(
            f"{action.tool_name}{serialized_parameters}".encode("utf-8")
        ).hexdigest()

        return ValidatedAction(
            tool_name=action.tool_name,
            parameters=action.parameters,
            reason=action.reason.strip(),
            step_number=action.step_number,
            checksum=checksum,
        )
