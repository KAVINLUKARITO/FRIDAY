from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    raw_input: str
    planned_actions: list[dict[str, Any]]
    current_step_index: int = 0
    steps_completed: int = 0
    steps_planned: int
    steps_taken: int = 0
    retries: int = 0
    current_action_retries: int = 0
    replans: int = 0
    total_executions: int = 0
    verified_successes: int = 0
    terminal_status: str = "RUNNING"
    outputs: list[Any] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def current_action(self) -> dict[str, Any] | None:
        if self.current_step_index >= len(self.planned_actions):
            return None
        return self.planned_actions[self.current_step_index]

    def mark_completed(self) -> None:
        self.steps_completed += 1
        self.current_step_index += 1
        self.current_action_retries = 0
        if self.current_step_index >= len(self.planned_actions):
            self.terminal_status = "SUCCEEDED"
            self.completed_at = datetime.now(timezone.utc)

    def mark_retry(self) -> None:
        self.retries += 1
        self.current_action_retries += 1

    def mark_replan(self, action: dict[str, Any]) -> None:
        self.replans += 1
        self.current_action_retries = 0
        self.planned_actions[self.current_step_index] = action

    def finish(self, status: str) -> None:
        self.terminal_status = status
        self.completed_at = datetime.now(timezone.utc)
