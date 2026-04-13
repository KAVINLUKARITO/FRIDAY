from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import settings


@dataclass
class MetricsSnapshot:
    timestamp: float
    task_success_rate: float
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    retry_count: int
    avg_execution_time: float
    failure_types: dict[str, int]
    memory_size_bytes: int
    active_tasks: int


class Monitor:
    """Monitoring and metrics collection system."""

    def __init__(self, db_path: str | None = None) -> None:
        default_db = settings.db_path.parent / "metrics.db"
        self.db_path = db_path or str(default_db)
        self._lock = threading.RLock()
        self._metrics: dict[str, Any] = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "retry_count": 0,
            "execution_times": [],
            "failure_types": {},
            "memory_size_bytes": 0,
        }
        self._active_tasks = 0
        self._connection: sqlite3.Connection | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if self._connection is None:
                self._connection = sqlite3.connect(":memory:", check_same_thread=False)
            return self._connection
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(path, check_same_thread=False)

    def _init_db(self) -> None:
        with self._managed_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    task_success_rate REAL,
                    total_tasks INTEGER,
                    successful_tasks INTEGER,
                    failed_tasks INTEGER,
                    retry_count INTEGER,
                    avg_execution_time REAL,
                    failure_types TEXT,
                    memory_size_bytes INTEGER,
                    active_tasks INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    event_type TEXT,
                    severity TEXT,
                    message TEXT,
                    context TEXT
                )
                """
            )
            conn.commit()

    def record_task_start(self) -> None:
        with self._lock:
            self._active_tasks += 1

    def record_task_success(self, execution_time: float) -> None:
        with self._lock:
            self._metrics["total_tasks"] += 1
            self._metrics["successful_tasks"] += 1
            self._metrics["execution_times"].append(execution_time)
            self._active_tasks = max(0, self._active_tasks - 1)
            self._persist_metrics_locked()

    def record_task_failure(self, failure_type: str) -> None:
        with self._lock:
            self._metrics["total_tasks"] += 1
            self._metrics["failed_tasks"] += 1
            failure_types = self._metrics["failure_types"]
            failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
            self._active_tasks = max(0, self._active_tasks - 1)
            self._persist_metrics_locked()

    def record_retry(self) -> None:
        with self._lock:
            self._metrics["retry_count"] += 1

    def record_memory_size(self, size_bytes: int) -> None:
        with self._lock:
            self._metrics["memory_size_bytes"] = size_bytes

    def log_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        with self._managed_connection() as conn:
            conn.execute(
                "INSERT INTO events (timestamp, event_type, severity, message, context) VALUES (?, ?, ?, ?, ?)",
                (time.time(), event_type, severity, message, json.dumps(context or {})),
            )
            conn.commit()

    def get_snapshot(self) -> MetricsSnapshot:
        with self._lock:
            total = self._metrics["total_tasks"]
            success_rate = (
                (self._metrics["successful_tasks"] / total) * 100.0
                if total > 0
                else 0.0
            )
            execution_times = self._metrics["execution_times"]
            average_time = sum(execution_times) / len(execution_times) if execution_times else 0.0
            return MetricsSnapshot(
                timestamp=time.time(),
                task_success_rate=round(success_rate, 2),
                total_tasks=total,
                successful_tasks=self._metrics["successful_tasks"],
                failed_tasks=self._metrics["failed_tasks"],
                retry_count=self._metrics["retry_count"],
                avg_execution_time=round(average_time, 3),
                failure_types=dict(self._metrics["failure_types"]),
                memory_size_bytes=self._metrics["memory_size_bytes"],
                active_tasks=self._active_tasks,
            )

    def get_health_status(self) -> dict[str, Any]:
        snapshot = self.get_snapshot()
        health = "healthy"
        if snapshot.task_success_rate < 50.0 and snapshot.total_tasks > 0:
            health = "critical"
        elif snapshot.task_success_rate < 80.0 and snapshot.total_tasks > 0:
            health = "warning"
        return {
            "status": health,
            "metrics": asdict(snapshot),
            "timestamp": datetime.now().isoformat(),
        }

    def query_metrics(
        self,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM metrics WHERE 1=1"
        params: list[Any] = []
        if start_time is not None:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND timestamp <= ?"
            params.append(end_time)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._managed_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _persist_metrics_locked(self) -> None:
        snapshot = self.get_snapshot()
        with self._managed_connection() as conn:
            conn.execute(
                """
                INSERT INTO metrics (
                    timestamp,
                    task_success_rate,
                    total_tasks,
                    successful_tasks,
                    failed_tasks,
                    retry_count,
                    avg_execution_time,
                    failure_types,
                    memory_size_bytes,
                    active_tasks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.timestamp,
                    snapshot.task_success_rate,
                    snapshot.total_tasks,
                    snapshot.successful_tasks,
                    snapshot.failed_tasks,
                    snapshot.retry_count,
                    snapshot.avg_execution_time,
                    json.dumps(snapshot.failure_types),
                    snapshot.memory_size_bytes,
                    snapshot.active_tasks,
                ),
            )
            conn.commit()

    class _ManagedConnection:
        def __init__(self, monitor: "Monitor") -> None:
            self.monitor = monitor
            self.connection: sqlite3.Connection | None = None

        def __enter__(self) -> sqlite3.Connection:
            self.connection = self.monitor._connect()
            return self.connection

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            if self.monitor.db_path != ":memory:" and self.connection is not None:
                self.connection.close()

    def _managed_connection(self) -> "Monitor._ManagedConnection":
        return Monitor._ManagedConnection(self)
