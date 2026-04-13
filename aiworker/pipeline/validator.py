from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from aiworker.tools.tool_registry import ToolRegistry, tool_registry


class ValidatedAction(BaseModel):
    tool_name: str
    parameters: dict[str, Any]
    validated_at: datetime
    checksum: str


class RawAction(BaseModel):
    tool_name: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(min_length=1)

    @field_validator("parameters")
    @classmethod
    def parameters_not_null(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value is None or not value:
            raise ValueError("parameters must be a non-empty object")
        return value


class Validator:
    def __init__(self, registry: ToolRegistry = tool_registry) -> None:
        self.registry = registry

    def validate(self, raw_action: dict) -> ValidatedAction:
        if not raw_action:
            raise ValidationError.from_exception_data(
                "RawAction",
                [{"type": "value_error", "loc": ("raw_action",), "msg": "action payload cannot be empty", "input": raw_action, "ctx": {"error": ValueError("action payload cannot be empty")}}],
            )

        action = RawAction.model_validate(raw_action)
        if self.registry.get(action.tool_name) is None:
            raise ValidationError.from_exception_data(
                "RawAction",
                [{"type": "value_error", "loc": ("tool_name",), "msg": "unknown tool name", "input": action.tool_name, "ctx": {"error": ValueError("unknown tool name")}}],
            )

        self.registry.validate_input(action.tool_name, action.parameters)
        checksum = self._checksum(action.tool_name, action.parameters)
        return ValidatedAction(
            tool_name=action.tool_name,
            parameters=action.parameters,
            validated_at=datetime.now(timezone.utc),
            checksum=checksum,
        )

    @staticmethod
    def _checksum(tool_name: str, parameters: dict[str, Any]) -> str:
        payload = tool_name + json.dumps(parameters, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
