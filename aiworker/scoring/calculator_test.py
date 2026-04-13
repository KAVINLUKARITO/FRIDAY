"""Confidence score calculation from historical metrics.

The calculator is **deterministic** — given the same database state it
always produces the same score.  No randomness, no machine learning,
no external calls.

The scoring layer is **read-only**: it never writes to the database.
"""

from __future__ import annotations

from aiworker.memory.database import Database
from aiworker.scoring.metrics import (
    average_execution_time,
    failure_rate_by_risk,
    success_rate,
    total_attempts,
)

# Maximum expected execution time (seconds) used to normalise T.
_MAX_EXECUTION_TIME: float = 120.0


def calculate_confidence(
    database: Database,
    goal: str,
    risk_level: str,
) -> float:
    """Compute a confidence score in the range ``[0.0, 1.0]``.

    The formula is a weighted combination of four signals:

    .. code-block:: text

        S = success_rate(goal)                     — historical success
        F = failure_rate_by_risk(risk_level)       — risk-level failures
        T = avg_execution_time(goal) / MAX_TIME    — time normalised
        N = min(total_attempts(goal) / 10, 1.0)    — experience factor

        confidence = 0.5 * S
                   + 0.2 * (1 - F)
                   + 0.2 * (1 - T)
                   + 0.1 * N

    The result is clamped to ``[0.0, 1.0]``.

    When there is no history the score defaults to ``0.3`` (low but not
    zero) because the ``(1 - F)`` and ``(1 - T)`` terms contribute
    positively even with no data.

    Args:
        database: An initialised :class:`Database`.
        goal: Goal text to match against historical attempts.
        risk_level: Risk level string (``"low"``, ``"medium"``, ``"high"``).

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    s = success_rate(database, goal)
    f = failure_rate_by_risk(database, risk_level)
    raw_t = average_execution_time(database, goal)
    n_raw = total_attempts(database, goal)

    # Normalise execution time to [0, 1] with a ceiling.
    t = min(raw_t / _MAX_EXECUTION_TIME, 1.0) if _MAX_EXECUTION_TIME > 0 else 0.0

    # Experience factor: saturates at 10 attempts.
    n = min(n_raw / 10.0, 1.0)

    confidence = (
        0.5 * s
        + 0.2 * (1.0 - f)
        + 0.2 * (1.0 - t)
        + 0.1 * n
    )

    # Clamp to [0, 1].
    return max(0.0, min(1.0, confidence))
