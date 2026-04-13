from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ValidationError as PydanticValidationError

from tools import TOOL_REGISTRY


class Action(BaseModel):
    tool_name: str
    parameters: dict[str, Any]
    reason: str
    step_number: int
    agent_name: str


class ValidatedAction(Action):
    checksum: str


class ValidationError(Exception):
    """Raised when an action fails validation."""


class Validator:
    """Validate structured agent actions before execution."""

    def validate(self, raw: dict[str, Any]) -> ValidatedAction:
        try:
            action = Action.model_validate(raw)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc

        if action.tool_name not in TOOL_REGISTRY:
            raise ValidationError(f"unknown tool: {action.tool_name}")
        if not action.parameters:
            raise ValidationError("parameters must be a non-empty dict")
        if not action.reason.strip():
            raise ValidationError("reason must be a non-empty string")
        if action.step_number < 1:
            raise ValidationError("step_number must be >= 1")
        if not action.agent_name.strip():
            raise ValidationError("agent_name must be a non-empty string")

        serialized_parameters = json.dumps(
            action.parameters,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        checksum = hashlib.sha256(
            f"{action.agent_name}{action.tool_name}{serialized_parameters}".encode("utf-8")
        ).hexdigest()

        return ValidatedAction(
            **action.model_dump(),
            checksum=checksum,
        )
