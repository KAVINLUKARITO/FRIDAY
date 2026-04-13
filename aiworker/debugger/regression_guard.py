"""Regression guard for the autonomous repair pipeline.

Deterministic rejection rules for patches:

1. Failed tests increased compared to baseline.
2. Same failure repeated 3+ times in history.
3. Risk score exceeds safety threshold (default 0.7).

No network, no randomness, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from aiworker.patch.sandbox_verifier import VerificationResult


@dataclass(frozen=True)
class RegressionDecision:
    """Immutable regression guard decision.

    Attributes:
        accepted: Whether the patch is accepted.
        reasons: Rejection reasons (empty if accepted).
    """

    accepted: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "accepted": self.accepted,
            "reasons": list(self.reasons),
        }


def check(
    verification: VerificationResult,
    risk_score: float,
    failure_history: Sequence[str] = (),
    current_failure_type: str = "",
    max_risk_score: float = 0.7,
    max_repeat_failures: int = 3,
) -> RegressionDecision:
    """Evaluate a patch for regression risks.

    Args:
        verification: Sandbox verification result.
        risk_score: LLM or plan risk score.
        failure_history: Previous failure type strings for repeat detection.
        current_failure_type: The failure type being repaired.
        max_risk_score: Risk score threshold (default 0.7).
        max_repeat_failures: Max times same failure is tolerated (default 3).

    Returns:
        A :class:`RegressionDecision`.
    """
    reasons: list[str] = []

    # Rule 1: Regression detected by verifier
    if verification.regression_detected:
        reasons.append(
            f"Regression detected: failed tests increased "
            f"(passed={verification.passed_tests}, "
            f"failed={verification.failed_tests})"
        )

    # Rule 2: Verification failed
    if not verification.success:
        reasons.append(
            f"Verification failed: {verification.error or 'tests did not pass'}"
        )

    # Rule 3: Repeated failure
    if current_failure_type and failure_history:
        repeat_count = sum(
            1 for ft in failure_history
            if ft == current_failure_type
        )
        if repeat_count >= max_repeat_failures:
            reasons.append(
                f"Same failure '{current_failure_type}' has occurred "
                f"{repeat_count} times (limit: {max_repeat_failures})"
            )

    # Rule 4: Risk score too high
    if risk_score > max_risk_score:
        reasons.append(
            f"Risk score {risk_score:.3f} exceeds threshold "
            f"{max_risk_score:.3f}"
        )

    return RegressionDecision(
        accepted=len(reasons) == 0,
        reasons=tuple(reasons),
    )
