"""Experiment tracker — manages A/B experiments — Phase 5."""
from __future__ import annotations
import json
import sqlite3
import uuid
from typing import List, Optional

from aiworker.experiment.models import BenchmarkResult, Experiment, ExperimentStatus, Variant


class ExperimentDatabase:
    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._conn: Optional[sqlite3.Connection] = None
        if path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.row_factory = sqlite3.Row

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self._get_conn().execute(sql, params)
        self._get_conn().commit()
        return cur

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        return self._get_conn().execute(sql, params).fetchall()

    def initialise(self) -> None:
        self.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                variant_a TEXT NOT NULL,
                variant_b TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                winner TEXT
            )
        """)
        self.execute("""
            CREATE TABLE IF NOT EXISTS experiment_results (
                result_id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                benchmark_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                score REAL NOT NULL,
                passed INTEGER NOT NULL,
                notes TEXT NOT NULL,
                duration_seconds REAL NOT NULL
            )
        """)


class ExperimentTracker:
    def __init__(self, db: ExperimentDatabase) -> None:
        self._db = db

    def create_experiment(self, name: str, hypothesis: str, variant_a: Variant, variant_b: Variant) -> Experiment:
        exp_id = str(uuid.uuid4())
        self._db.execute(
            "INSERT INTO experiments (experiment_id, name, hypothesis, variant_a, variant_b) VALUES (?,?,?,?,?)",
            (exp_id, name, hypothesis,
             json.dumps({"id": variant_a.variant_id, "name": variant_a.name}),
             json.dumps({"id": variant_b.variant_id, "name": variant_b.name})),
        )
        return Experiment(experiment_id=exp_id, name=name, hypothesis=hypothesis,
                          variant_a=variant_a, variant_b=variant_b)

    def record_result(self, experiment_id: str, variant: str, result: BenchmarkResult) -> None:
        self._db.execute(
            "INSERT INTO experiment_results "
            "(result_id, experiment_id, variant, benchmark_id, attempt_id, score, passed, notes, duration_seconds) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), experiment_id, variant,
             result.benchmark_id, result.attempt_id,
             result.score, int(result.passed), result.notes, result.duration_seconds),
        )

    def get_results(self, experiment_id: str, variant: str) -> List[BenchmarkResult]:
        rows = self._db.fetchall(
            "SELECT * FROM experiment_results WHERE experiment_id=? AND variant=?",
            (experiment_id, variant),
        )
        return [BenchmarkResult(
            benchmark_id=r["benchmark_id"], attempt_id=r["attempt_id"],
            score=r["score"], passed=bool(r["passed"]),
            notes=r["notes"], duration_seconds=r["duration_seconds"],
        ) for r in rows]

    def conclude(self, experiment: Experiment) -> str:
        experiment.results_a = self.get_results(experiment.experiment_id, "a")
        experiment.results_b = self.get_results(experiment.experiment_id, "b")
        winner = experiment.conclude()
        self._db.execute(
            "UPDATE experiments SET status=?, winner=? WHERE experiment_id=?",
            (ExperimentStatus.COMPLETED.value, winner, experiment.experiment_id),
        )
        return winner
