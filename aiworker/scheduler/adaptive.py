"""Adaptive scheduler for bounded local task execution."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from aiworker.config import AIWorkerConfig

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    created_at: float = field(default_factory=time.time)


class AdaptiveScheduler:
    """Small priority scheduler used by legacy dashboards and tests."""

    def __init__(self, config: AIWorkerConfig | None = None) -> None:
        self.config = config or AIWorkerConfig.from_env()
        self._queue: list[ScheduledTask] = []

    def schedule(self, name: str, payload: dict[str, Any] | None = None, priority: int = 0) -> ScheduledTask:
        task = ScheduledTask(name=name, payload=payload or {}, priority=priority)
        self._queue.append(task)
        self._queue.sort(key=lambda item: (-item.priority, item.created_at))
        logger.debug("scheduled task %s priority=%s", name, priority)
        return task

    def next_task(self) -> ScheduledTask | None:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def snapshot(self) -> dict[str, Any]:
        return {
            "queued": len(self._queue),
            "tasks": [
                {
                    "name": task.name,
                    "priority": task.priority,
                    "created_at": task.created_at,
                }
                for task in self._queue
            ],
        }

    def reset(self) -> None:
        self._queue.clear()


def create_adaptive_scheduler(config: AIWorkerConfig | None = None) -> AdaptiveScheduler:
    return AdaptiveScheduler(config)
