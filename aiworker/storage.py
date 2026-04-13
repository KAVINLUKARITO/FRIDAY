from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class StepRecord(BaseModel):
    run_id: str
    agent_name: str
    step_number: int
    tool_name: str
    parameters: dict[str, Any]
    reason: str
    verification_status: str
    output_summary: str
    error: str | None
    duration_seconds: float
    timestamp: datetime


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
    """SQLite persistence for agent steps, trades, and findings."""

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
                    agent_name TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    output_summary TEXT NOT NULL,
                    error TEXT,
                    duration_seconds REAL NOT NULL,
                    timestamp TEXT NOT NULL
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
            connection.execute("CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id);")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_trades_run_id ON trades(run_id);")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_vulnerabilities_run_id ON vulnerabilities(run_id);"
            )
            connection.commit()

    def save_step(self, record: StepRecord) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO steps (
                    run_id, agent_name, step_number, tool_name, parameters, reason,
                    verification_status, output_summary, error, duration_seconds, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.run_id,
                    record.agent_name,
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

    def get_run_steps(self, run_id: str) -> list[StepRecord]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT run_id, agent_name, step_number, tool_name, parameters, reason,
                       verification_status, output_summary, error, duration_seconds, timestamp
                FROM steps
                WHERE run_id = ?
                ORDER BY id ASC;
                """,
                (run_id,),
            ).fetchall()
        return [
            StepRecord(
                run_id=row[0],
                agent_name=row[1],
                step_number=row[2],
                tool_name=row[3],
                parameters=json.loads(row[4]),
                reason=row[5],
                verification_status=row[6],
                output_summary=row[7],
                error=row[8],
                duration_seconds=row[9],
                timestamp=datetime.fromisoformat(row[10]),
            )
            for row in rows
        ]

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
                run_id=row[0],
                order_id=row[1],
                symbol=row[2],
                side=row[3],
                qty=row[4],
                price=row[5],
                fill_price=row[6],
                timestamp=datetime.fromisoformat(row[7]),
                pnl=row[8],
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
                run_id=row[0],
                agent_name=row[1],
                target=row[2],
                vuln_type=row[3],
                severity=row[4],
                evidence=row[5],
                confirmed=bool(row[6]),
                timestamp=datetime.fromisoformat(row[7]),
            )
            for row in rows
        ]

    def get_all_run_ids(self) -> list[str]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT run_id FROM (
                    SELECT run_id FROM steps
                    UNION
                    SELECT run_id FROM trades
                    UNION
                    SELECT run_id FROM vulnerabilities
                )
                ORDER BY run_id ASC;
                """
            ).fetchall()
        return [row[0] for row in rows]

    def get_run_summary(self, run_id: str) -> dict[str, Any]:
        steps = self.get_run_steps(run_id)
        trades = self.get_run_trades(run_id)
        vulnerabilities = self.get_run_vulnerabilities(run_id)
        return {
            "run_id": run_id,
            "step_count": len(steps),
            "trade_count": len(trades),
            "vulnerability_count": len(vulnerabilities),
            "success_steps": sum(1 for step in steps if step.verification_status == "SUCCESS"),
            "failure_steps": sum(1 for step in steps if step.verification_status == "FAILURE"),
            "total_duration": sum(step.duration_seconds for step in steps),
            "agents": sorted({step.agent_name for step in steps}),
        }
