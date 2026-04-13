"""Decision context builder for the engine reporting layer.

Combines the confidence score with human-readable recommendation
thresholds.  The output is purely informational — it never modifies
the approval gate or auto-approves patches.

The scoring layer is **read-only**: it never writes to the database.
"""

from __future__ import annotations

from typing import Any

from aiworker.memory.database import Database
from aiworker.scoring.calculator import calculate_confidence
from aiworker.scoring.metrics import (
    failure_rate_by_risk,
    success_rate,
    total_attempts,
)


def build_decision_context(
    database: Database,
    goal: str,
    risk_level: str,
) -> dict[str, Any]:
    """Build a structured decision context for reporting.

    The returned dictionary is intended to be included in the engine
    result JSON so that humans (or future agents) can make informed
    decisions.  It **never** influences the approval gate directly.

    Recommendation thresholds:

    * ``confidence >= 0.75`` → ``"proceed"``
    * ``0.4 <= confidence < 0.75`` → ``"review_carefully"``
    * ``confidence < 0.4`` → ``"high_risk"``

    Args:
        database: An initialised :class:`Database`.
        goal: Goal text to match against historical attempts.
        risk_level: Risk level string.

    Returns:
        A JSON-serialisable dictionary with scoring details.
    """
    confidence = calculate_confidence(database, goal, risk_level)
    s = success_rate(database, goal)
    f = failure_rate_by_risk(database, risk_level)
    n = total_attempts(database, goal)

    if confidence >= 0.75:
        recommendation = "proceed"
    elif confidence >= 0.4:
        recommendation = "review_carefully"
    else:
        recommendation = "high_risk"

    return {
        "confidence_score": confidence,
        "recommendation": recommendation,
        "historical_attempts": n,
        "success_rate": s,
        "risk_failure_rate": f,
    }
