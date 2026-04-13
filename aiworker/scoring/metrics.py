"""Historical metrics computed from the experience memory database.

All functions are **read-only** — they never insert, update, or delete
records.  They query the memory layer via parameterised SQL through
:class:`~aiworker.memory.database.Database` and return simple numeric
values.  Zero-history cases always return safe defaults.
"""

from __future__ import annotations

from aiworker.memory.database import Database


def success_rate(database: Database, goal: str) -> float:
    """Fraction of past sandbox runs for *goal* that succeeded.

    Returns ``0.0`` when there is no history.
    """
    with database.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*), "
            "       SUM(CASE WHEN sr.success = 1 THEN 1 ELSE 0 END) "
            "FROM change_attempts ca "
            "JOIN sandbox_results sr ON sr.attempt_id = ca.id "
            "WHERE ca.goal LIKE ?",
            (f"%{goal}%",),
        ).fetchone()

    total = row[0] if row[0] else 0
    successes = row[1] if row[1] else 0
    if total == 0:
        return 0.0
    return successes / total


def failure_rate_by_risk(database: Database, risk_level: str) -> float:
    """Fraction of past sandbox runs at *risk_level* that failed.

    Returns ``0.0`` when there is no history.
    """
    with database.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*), "
            "       SUM(CASE WHEN sr.success = 0 THEN 1 ELSE 0 END) "
            "FROM change_attempts ca "
            "JOIN sandbox_results sr ON sr.attempt_id = ca.id "
            "WHERE ca.risk_level = ?",
            (risk_level,),
        ).fetchone()

    total = row[0] if row[0] else 0
    failures = row[1] if row[1] else 0
    if total == 0:
        return 0.0
    return failures / total


def average_execution_time(database: Database, goal: str) -> float:
    """Average sandbox execution time (seconds) for *goal*.

    Returns ``0.0`` when there is no history.
    """
    with database.connect() as conn:
        row = conn.execute(
            "SELECT AVG(sr.execution_time) "
            "FROM change_attempts ca "
            "JOIN sandbox_results sr ON sr.attempt_id = ca.id "
            "WHERE ca.goal LIKE ?",
            (f"%{goal}%",),
        ).fetchone()

    avg = row[0] if row and row[0] is not None else 0.0
    return float(avg)


def total_attempts(database: Database, goal: str) -> int:
    """Total number of change attempts whose goal matches *goal*.

    Returns ``0`` when there is no history.
    """
    with database.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) "
            "FROM change_attempts "
            "WHERE goal LIKE ?",
            (f"%{goal}%",),
        ).fetchone()

    return int(row[0]) if row and row[0] else 0
