"""Pydantic models for the maintained AIWorker task-agent runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    max_iterations = "max_iterations"
    shutdown = "shutdown"


class TaskIntent(str, Enum):
    echo = "echo"
    inspect = "inspect"
    read_file = "read_file"
    system_info = "system_info"
    unknown = "unknown"


class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    raw_input: str = Field(min_length=1)
    intent: TaskIntent = TaskIntent.unknown
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw_input")
    @classmethod
    def normalize_input(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("task input cannot be empty")
        return normalized


class PlanStep(BaseModel):
    index: int = Field(ge=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    status: Literal["pending", "running", "succeeded", "failed"] = "pending"


class AgentPlan(BaseModel):
    task_id: str
    intent: TaskIntent
    steps: list[PlanStep] = Field(default_factory=list)


class ToolResult(BaseModel):
    success: bool
    tool_name: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)


class ToolDefinition(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    capabilities: tuple[str, ...] = Field(default_factory=tuple)
    timeout_seconds: float = Field(default=20.0, gt=0.0)
    retry_attempts: int = Field(default=0, ge=0)


class MemoryRecord(BaseModel):
    task_id: str
    role: Literal["task", "plan", "tool", "agent"]
    content: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRunResult(BaseModel):
    success: bool
    task_id: str
    status: TaskStatus
    output: str
    iterations: int = Field(ge=0)
    tool_results: list[ToolResult] = Field(default_factory=list)
    error: str | None = None
