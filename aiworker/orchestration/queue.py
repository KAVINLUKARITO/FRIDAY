"""Simple in-memory FIFO task queue.

No persistence, no threading, no async.  Deterministic behaviour.
"""

from __future__ import annotations

import uuid
from collections import deque

from aiworker.orchestration.models import Task


class TaskQueue:
    """In-memory FIFO queue of :class:`Task` objects.

    Tasks are added via :meth:`add_task`, retrieved in insertion order
    via :meth:`get_next_task`, and marked as processed via
    :meth:`mark_processed`.
    """

    def __init__(self) -> None:
        self._pending: deque[Task] = deque()
        self._all: dict[str, Task] = {}

    def add_task(self, goal: str) -> Task:
        """Create a new pending task and enqueue it.

        Args:
            goal: Human-readable goal description.

        Returns:
            The newly created :class:`Task`.
        """
        task = Task(task_id=uuid.uuid4().hex, goal=goal)
        self._pending.append(task)
        self._all[task.task_id] = task
        return task

    def get_next_task(self) -> Task | None:
        """Return the next pending task without removing it, or ``None``."""
        if not self._pending:
            return None
        return self._pending[0]

    def mark_processed(self, task_id: str) -> None:
        """Mark a task as processed and remove it from the pending queue.

        Args:
            task_id: Identifier of the task to mark.

        Raises:
            KeyError: If *task_id* is not known.
        """
        if task_id not in self._all:
            raise KeyError(f"Unknown task: {task_id}")

        processed = Task(
            task_id=task_id,
            goal=self._all[task_id].goal,
            status="processed",
        )
        self._all[task_id] = processed

        self._pending = deque(t for t in self._pending if t.task_id != task_id)

    def pending_count(self) -> int:
        """Return the number of pending tasks."""
        return len(self._pending)
