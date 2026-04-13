"""Minimal persistent sequential engine used by legacy orchestration modules."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "IDLE"
    PLAN = "PLAN"
    RESEARCH = "RESEARCH"
    CODE = "CODE"
    VALIDATE = "VALIDATE"
    APPLY = "APPLY"
    LEARN = "LEARN"
    ERROR = "ERROR"
    PAUSED = "PAUSED"


@dataclass
class IterationContext:
    iteration_id: str
    goal: str
    state: State = State.PLAN
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error_count: int = 0
    data: dict = field(default_factory=dict)

    def to_record(self) -> dict:
        return {
            "iteration_id": self.iteration_id,
            "state": self.state.value,
            "goal": self.goal,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "success": self.state == State.IDLE,
            "error_count": self.error_count,
            "data": json.dumps(self.data, default=str),
        }


Handler = Callable[[IterationContext], State]


class SequentialEngine:
    """State-machine runner with SQLite checkpointing and max-iteration guard."""

    def __init__(self, db_path: str = "aiworker.db", max_iterations: int = 8) -> None:
        self.db_path = Path(db_path)
        self.max_iterations = max(1, max_iterations)
        self._handlers: dict[State, Handler] = {}
        self._context: IterationContext | None = None
        self._step_count = 0
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS iterations (
                    iteration_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    success BOOLEAN,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    data TEXT
                )
                """
            )
            conn.commit()

    def register_handler(self, state: State, handler: Handler) -> None:
        self._handlers[state] = handler

    def start_iteration(self, goal: str) -> IterationContext:
        self._context = IterationContext(iteration_id=uuid4().hex, goal=goal)
        self._step_count = 0
        self._save_context()
        return self._context

    def step(self) -> IterationContext:
        if self._context is None:
            raise RuntimeError("No active iteration")
        if self._context.state in {State.IDLE, State.ERROR, State.PAUSED}:
            return self._context
        if self._step_count >= self.max_iterations:
            self._context.state = State.ERROR
            self._context.data["error"] = "max_iterations_reached"
            self._context.completed_at = time.time()
            self._save_context()
            return self._context

        handler = self._handlers.get(self._context.state)
        if handler is None:
            self._context.state = State.ERROR
            self._context.data["error"] = f"no handler for {self._context.state.value}"
        else:
            try:
                self._context.state = handler(self._context)
            except Exception as exc:
                logger.exception("state handler failed")
                self._context.error_count += 1
                self._context.state = State.ERROR
                self._context.data["error"] = str(exc)

        self._step_count += 1
        if self._context.state in {State.IDLE, State.ERROR}:
            self._context.completed_at = time.time()
        self._save_context()
        return self._context

    def pause_iteration(self) -> None:
        if self._context is not None:
            self._context.state = State.PAUSED
            self._save_context()

    def get_current_iteration(self) -> dict | None:
        if self._context is not None:
            return self._context.to_record()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM iterations WHERE completed_at IS NULL ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def get_incomplete_iterations(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT iteration_id FROM iterations WHERE completed_at IS NULL ORDER BY started_at DESC"
            ).fetchall()
            return [row[0] for row in rows]

    def get_recent_iterations(self, limit: int = 5) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM iterations ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def heartbeat(self, state: str | None = None) -> None:
        if self._context is not None:
            self._context.data["last_heartbeat"] = time.time()
            if state:
                self._context.data["heartbeat_state"] = state
            self._save_context()

    def _save_context(self) -> None:
        if self._context is None:
            return
        record = self._context.to_record()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO iterations (
                    iteration_id, state, goal, started_at, completed_at, success, error_count, data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(iteration_id) DO UPDATE SET
                    state=excluded.state,
                    goal=excluded.goal,
                    completed_at=excluded.completed_at,
                    success=excluded.success,
                    error_count=excluded.error_count,
                    data=excluded.data
                """,
                (
                    record["iteration_id"],
                    record["state"],
                    record["goal"],
                    record["started_at"],
                    record["completed_at"],
                    record["success"],
                    record["error_count"],
                    record["data"],
                ),
            )
            conn.commit()
