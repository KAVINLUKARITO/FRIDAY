from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class StepRecord(BaseModel):
    run_id: str
    step_number: int
    tool_name: str
    parameters: dict[str, Any]
    reason: str
    verification_status: str
    output_summary: str
    error: str | None
    duration_seconds: float
    timestamp: datetime


class Storage:
    """Persist and query agent run history in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    output_summary TEXT,
                    error TEXT,
                    duration_seconds REAL NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_id ON steps(run_id);"
            )
            connection.commit()

    def save_step(self, record: StepRecord) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO steps (
                    run_id,
                    step_number,
                    tool_name,
                    parameters,
                    reason,
                    verification_status,
                    output_summary,
                    error,
                    duration_seconds,
                    timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.run_id,
                    record.step_number,
                    record.tool_name,
                    json.dumps(record.parameters, sort_keys=True),
                    record.reason,
                    record.verification_status,
                    record.output_summary[:500],
                    record.error,
                    record.duration_seconds,
                    record.timestamp.isoformat(),
                ),
            )
            connection.commit()

    def get_run(self, run_id: str) -> list[StepRecord]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    run_id,
                    step_number,
                    tool_name,
                    parameters,
                    reason,
                    verification_status,
                    output_summary,
                    error,
                    duration_seconds,
                    timestamp
                FROM steps
                WHERE run_id = ?
                ORDER BY step_number ASC, id ASC;
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_all_runs(self) -> list[str]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT DISTINCT run_id FROM steps ORDER BY run_id ASC;"
            ).fetchall()
        return [row[0] for row in rows]

    def get_summary(self, run_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_steps,
                    SUM(CASE WHEN verification_status = 'SUCCESS' THEN 1 ELSE 0 END) AS success_count,
                    SUM(CASE WHEN verification_status = 'FAILURE' THEN 1 ELSE 0 END) AS failure_count,
                    SUM(CASE WHEN verification_status = 'UNVERIFIED' THEN 1 ELSE 0 END) AS unverified_count,
                    COALESCE(SUM(duration_seconds), 0.0) AS total_duration
                FROM steps
                WHERE run_id = ?;
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return {
                "total_steps": 0,
                "success_count": 0,
                "failure_count": 0,
                "unverified_count": 0,
                "total_duration": 0.0,
            }
        return {
            "total_steps": int(row[0] or 0),
            "success_count": int(row[1] or 0),
            "failure_count": int(row[2] or 0),
            "unverified_count": int(row[3] or 0),
            "total_duration": float(row[4] or 0.0),
        }

    @staticmethod
    def _row_to_record(row: tuple[Any, ...]) -> StepRecord:
        return StepRecord(
            run_id=str(row[0]),
            step_number=int(row[1]),
            tool_name=str(row[2]),
            parameters=json.loads(str(row[3])),
            reason=str(row[4]),
            verification_status=str(row[5]),
            output_summary=str(row[6] or ""),
            error=row[7] if row[7] is None else str(row[7]),
            duration_seconds=float(row[8]),
            timestamp=datetime.fromisoformat(str(row[9])),
        )
