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
    agent_name: str | None = None


class TradeRecord(BaseModel):
    run_id: str
    order_id: str
    symbol: str
    side: str
    qty: float
    price: float
    fill_price: float
    timestamp: datetime
    pnl: float | None


class VulnerabilityRecord(BaseModel):
    run_id: str
    agent_name: str
    target: str
    vuln_type: str
    severity: str
    evidence: str
    confirmed: bool
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
                    timestamp TEXT NOT NULL,
                    agent_name TEXT
                );
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    pnl REAL
                );
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vulnerabilities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    target TEXT NOT NULL,
                    vuln_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    confirmed INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_run_id ON steps(run_id);")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_trades_run_id ON trades(run_id);")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_vulnerabilities_run_id ON vulnerabilities(run_id);"
            )
            self._ensure_step_columns(connection)
            connection.commit()

    @staticmethod
    def _ensure_step_columns(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(steps);").fetchall()
        }
        if "agent_name" not in columns:
            connection.execute(
                "ALTER TABLE steps ADD COLUMN agent_name TEXT DEFAULT '';"
            )

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
                    timestamp,
                    agent_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                    record.agent_name,
                ),
            )
            connection.commit()

    def save_trade(self, record: TradeRecord) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO trades (
                    run_id, order_id, symbol, side, qty, price, fill_price, timestamp, pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.run_id,
                    record.order_id,
                    record.symbol,
                    record.side,
                    record.qty,
                    record.price,
                    record.fill_price,
                    record.timestamp.isoformat(),
                    record.pnl,
                ),
            )
            connection.commit()

    def save_vulnerability(self, record: VulnerabilityRecord) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO vulnerabilities (
                    run_id, agent_name, target, vuln_type, severity, evidence, confirmed, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.run_id,
                    record.agent_name,
                    record.target,
                    record.vuln_type,
                    record.severity,
                    record.evidence,
                    1 if record.confirmed else 0,
                    record.timestamp.isoformat(),
                ),
            )
            connection.commit()

    def get_run(self, run_id: str) -> list[StepRecord]:
        return self.get_run_steps(run_id)

    def get_run_steps(self, run_id: str) -> list[StepRecord]:
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
                    timestamp,
                    agent_name
                FROM steps
                WHERE run_id = ?
                ORDER BY step_number ASC, id ASC;
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_step_record(row) for row in rows]

    def get_run_trades(self, run_id: str) -> list[TradeRecord]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT run_id, order_id, symbol, side, qty, price, fill_price, timestamp, pnl
                FROM trades
                WHERE run_id = ?
                ORDER BY id ASC;
                """,
                (run_id,),
            ).fetchall()
        return [
            TradeRecord(
                run_id=str(row[0]),
                order_id=str(row[1]),
                symbol=str(row[2]),
                side=str(row[3]),
                qty=float(row[4]),
                price=float(row[5]),
                fill_price=float(row[6]),
                timestamp=datetime.fromisoformat(str(row[7])),
                pnl=None if row[8] is None else float(row[8]),
            )
            for row in rows
        ]

    def get_run_vulnerabilities(self, run_id: str) -> list[VulnerabilityRecord]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT run_id, agent_name, target, vuln_type, severity, evidence, confirmed, timestamp
                FROM vulnerabilities
                WHERE run_id = ?
                ORDER BY id ASC;
                """,
                (run_id,),
            ).fetchall()
        return [
            VulnerabilityRecord(
                run_id=str(row[0]),
                agent_name=str(row[1]),
                target=str(row[2]),
                vuln_type=str(row[3]),
                severity=str(row[4]),
                evidence=str(row[5]),
                confirmed=bool(row[6]),
                timestamp=datetime.fromisoformat(str(row[7])),
            )
            for row in rows
        ]

    def get_all_runs(self) -> list[str]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT DISTINCT run_id FROM steps ORDER BY run_id ASC;"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def get_all_run_ids(self) -> list[str]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT run_id FROM (
                    SELECT run_id FROM steps
                    UNION
                    SELECT run_id FROM trades
                    UNION
                    SELECT run_id FROM vulnerabilities
                ) ORDER BY run_id ASC;
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

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

    def get_run_summary(self, run_id: str) -> dict[str, Any]:
        return {
            "step_count": len(self.get_run_steps(run_id)),
            "trade_count": len(self.get_run_trades(run_id)),
            "vulnerability_count": len(self.get_run_vulnerabilities(run_id)),
        }

    @staticmethod
    def _row_to_step_record(row: tuple[Any, ...]) -> StepRecord:
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
            agent_name=None if row[10] is None else str(row[10]),
        )
