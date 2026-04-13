"""Validated tool registry and execution wrapper."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ValidationError

from aiworker.config import AIWorkerConfig
from aiworker.models import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

ToolCallable = Callable[[BaseModel], ToolResult]


class RegisteredTool:
    def __init__(
        self,
        definition: ToolDefinition,
        input_model: type[BaseModel],
        handler: ToolCallable,
    ) -> None:
        self.definition = definition
        self.input_model = input_model
        self.handler = handler


class ToolRegistry:
    """Stores tool definitions, validates inputs, and records outcomes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tools: dict[str, RegisteredTool] = {}
        self._stats: dict[str, dict[str, Any]] = {}

    def register(
        self,
        definition: ToolDefinition,
        input_model: type[BaseModel],
        handler: ToolCallable,
    ) -> ToolDefinition:
        with self._lock:
            self._tools[definition.name] = RegisteredTool(definition, input_model, handler)
            self._stats.setdefault(
                definition.name,
                {
                    "name": definition.name,
                    "capabilities": definition.capabilities,
                    "usage_count": 0,
                    "success_count": 0,
                },
            )
            logger.debug("registered tool %s", definition.name)
            return definition

    def register_tool(self, name: str, *, capabilities: Iterable[str] = ()) -> dict[str, Any]:
        """Legacy metadata-only registration used by discovery helpers."""

        with self._lock:
            entry = self._stats.setdefault(
                name,
                {
                    "name": name,
                    "capabilities": tuple(sorted(set(capabilities))),
                    "usage_count": 0,
                    "success_count": 0,
                },
            )
            entry["capabilities"] = tuple(sorted(set(entry["capabilities"]) | set(capabilities)))
            return dict(entry)

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        config: AIWorkerConfig | None = None,
    ) -> ToolResult:
        with self._lock:
            registered = self._tools.get(name)

        if registered is None:
            result = ToolResult(success=False, tool_name=name, error=f"Unknown tool: {name}")
            self.record_tool_result(name, success=False)
            return result

        args = arguments or {}
        try:
            validated = registered.input_model.model_validate(args)
        except ValidationError as exc:
            result = ToolResult(
                success=False,
                tool_name=name,
                error=f"Invalid input for {name}: {exc}",
            )
            self.record_tool_result(name, success=False)
            return result

        attempts = registered.definition.retry_attempts
        if config is not None:
            attempts = max(attempts, config.tool_retry_attempts)

        last_error: str | None = None
        for attempt in range(attempts + 1):
            start = time.monotonic()
            try:
                result = registered.handler(validated)
                result.duration_seconds = time.monotonic() - start
                self.record_tool_result(name, success=result.success)
                return result
            except Exception as exc:  # pragma: no cover - defensive wrapper
                last_error = str(exc)
                logger.exception("tool %s failed on attempt %s", name, attempt + 1)

        result = ToolResult(success=False, tool_name=name, error=last_error or "Tool failed")
        self.record_tool_result(name, success=False)
        return result

    def record_tool_result(self, name: str, *, success: bool) -> dict[str, Any]:
        with self._lock:
            entry = self._stats.setdefault(
                name,
                {"name": name, "capabilities": (), "usage_count": 0, "success_count": 0},
            )
            entry["usage_count"] += 1
            if success:
                entry["success_count"] += 1
            return dict(entry)

    def suggest_tools(self, capability: str) -> tuple[str, ...]:
        with self._lock:
            scored = []
            for name, entry in self._stats.items():
                if capability in entry["capabilities"]:
                    usage = max(1, int(entry["usage_count"]))
                    score = entry["success_count"] / usage
                    scored.append((score, name))
            return tuple(name for _, name in sorted(scored, reverse=True))

    def get(self, name: str) -> ToolDefinition | None:
        with self._lock:
            registered = self._tools.get(name)
            return registered.definition if registered else None

    def validate_input(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        with self._lock:
            registered = self._tools.get(name)
        if registered is None:
            raise ValidationError.from_exception_data(
                "ToolInput",
                [{"type": "value_error", "loc": ("tool_name",), "msg": "unknown tool name", "input": name, "ctx": {"error": ValueError("unknown tool name")}}],
            )
        return registered.input_model.model_validate(arguments)

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._tools))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tools": deepcopy(self._stats),
                "tool_count": len(self._tools),
                "callable_tools": self.names(),
            }

    def reset(self) -> None:
        with self._lock:
            self._tools.clear()
            self._stats.clear()


tool_registry = ToolRegistry()
