"""Deterministic failure classification for autonomous dev loop."""

from __future__ import annotations

from typing import Sequence


def classify_failure(
    *,
    error_message: str = "",
    stderr: str = "",
    timed_out: bool = False,
    validation_errors: Sequence[str] = (),
    tests_failed: int = 0,
    risk_score: float = 0.0,
    risk_threshold: float = 1.0,
) -> str:
    """Classify failure into deterministic enum-like string."""
    if risk_score > risk_threshold:
        return "high_risk"
    if validation_errors:
        return "validation_error"
    if timed_out:
        return "sandbox_timeout"

    merged = f"{error_message}\n{stderr}".lower()
    if "syntaxerror" in merged or "syntax error" in merged:
        return "syntax_error"
    if "importerror" in merged or "modulenotfounderror" in merged:
        return "import_error"

    if tests_failed > 0:
        return "test_failure"

    return "unknown"


__all__ = ["classify_failure"]
