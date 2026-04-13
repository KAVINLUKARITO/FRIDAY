"""Deterministic root cause analysis via layered rule engine.

Analyses a :class:`FailureReport` through three layers of rules:

1. **Structural** — import errors, attribute errors, syntax errors.
2. **State** — circuit breaker, rate limits, missing DB tables.
3. **Behavioral** — infinite loops, repeated regressions, timeouts.

If the root cause is resolved deterministically, the result includes
a ``suggested_fix`` and ``resolved=True``, allowing the pipeline to
skip the LLM entirely.

No network calls, no randomness, no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from aiworker.debugger.capture import FailureReport


@dataclass(frozen=True)
class RootCauseResult:
    """Immutable outcome of root cause analysis.

    Attributes:
        resolved: Whether the root cause was identified deterministically.
        category: Classification label (structural, state, behavioral, unknown).
        explanation: Human-readable description of the cause.
        suggested_fix: Actionable fix if resolved, else ``None``.
    """

    resolved: bool
    category: str
    explanation: str
    suggested_fix: Optional[str] = None

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.category or not self.category.strip():
            errors.append("category must be a non-empty string")
        if not self.explanation or not self.explanation.strip():
            errors.append("explanation must be a non-empty string")
        if errors:
            raise ValueError(
                "Invalid RootCauseResult: " + "; ".join(errors)
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "resolved": self.resolved,
            "category": self.category,
            "explanation": self.explanation,
            "suggested_fix": self.suggested_fix,
        }


# -------------------------------------------------------------------
# Layer 1: Structural rules
# -------------------------------------------------------------------

_IMPORT_ERROR_RE = re.compile(
    r"No module named ['\"]?(\S+)['\"]?", re.IGNORECASE
)
_ATTRIBUTE_ERROR_RE = re.compile(
    r"(?:module|type|object)\s+['\"]?(\S+?)['\"]?\s+has no attribute\s+['\"]?(\S+)['\"]?",
    re.IGNORECASE,
)
_SYNTAX_ERROR_RE = re.compile(
    r"SyntaxError:\s+(.+)", re.IGNORECASE
)


def _check_structural(report: FailureReport) -> Optional[RootCauseResult]:
    """Check for structural errors (import, attribute, syntax)."""
    exc = report.exception_type.lower()
    msg = report.message
    tb = report.traceback

    # ImportError / ModuleNotFoundError
    if "importerror" in exc or "modulenotfounderror" in exc:
        match = _IMPORT_ERROR_RE.search(msg) or _IMPORT_ERROR_RE.search(tb)
        module_name = match.group(1) if match else "unknown"
        return RootCauseResult(
            resolved=True,
            category="structural",
            explanation=f"Missing module: {module_name}",
            suggested_fix=f"Install or create module '{module_name}', "
                          f"or fix the import statement.",
        )

    # AttributeError
    if "attributeerror" in exc:
        match = _ATTRIBUTE_ERROR_RE.search(msg) or _ATTRIBUTE_ERROR_RE.search(tb)
        if match:
            obj, attr = match.group(1), match.group(2)
            return RootCauseResult(
                resolved=True,
                category="structural",
                explanation=f"Missing attribute '{attr}' on '{obj}'",
                suggested_fix=f"Add attribute '{attr}' to '{obj}' or "
                              f"fix the reference.",
            )
        return RootCauseResult(
            resolved=True,
            category="structural",
            explanation=f"AttributeError: {msg}",
            suggested_fix="Review the attribute access in the traceback.",
        )

    # SyntaxError
    if "syntaxerror" in exc:
        match = _SYNTAX_ERROR_RE.search(msg) or _SYNTAX_ERROR_RE.search(tb)
        detail = match.group(1) if match else msg
        return RootCauseResult(
            resolved=True,
            category="structural",
            explanation=f"Syntax error: {detail}",
            suggested_fix="Fix the syntax error at the indicated location.",
        )

    return None


# -------------------------------------------------------------------
# Layer 2: State rules
# -------------------------------------------------------------------

_CIRCUIT_BREAKER_PATTERNS = (
    "circuit breaker",
    "circuit_breaker",
    "breaker is open",
)

_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "rate_limit",
    "too many attempts",
)

_MISSING_TABLE_RE = re.compile(
    r"no such table:\s*(\S+)", re.IGNORECASE
)


def _check_state(report: FailureReport) -> Optional[RootCauseResult]:
    """Check for state-related failures."""
    combined = (report.message + " " + report.traceback).lower()

    # Circuit breaker open
    for pattern in _CIRCUIT_BREAKER_PATTERNS:
        if pattern in combined:
            return RootCauseResult(
                resolved=True,
                category="state",
                explanation="Circuit breaker is open due to consecutive failures",
                suggested_fix="Wait for recovery window or reset the circuit "
                              "breaker after investigating root failures.",
            )

    # Rate limit exceeded
    for pattern in _RATE_LIMIT_PATTERNS:
        if pattern in combined:
            return RootCauseResult(
                resolved=True,
                category="state",
                explanation="Rate limit exceeded for change attempts",
                suggested_fix="Wait for the rate limit window to expire "
                              "before retrying.",
            )

    # Missing database table
    match = _MISSING_TABLE_RE.search(report.message) or \
            _MISSING_TABLE_RE.search(report.traceback)
    if match:
        table = match.group(1)
        return RootCauseResult(
            resolved=True,
            category="state",
            explanation=f"Missing database table: {table}",
            suggested_fix=f"Run database.initialise() to create table "
                          f"'{table}', or check schema migration.",
        )

    return None


# -------------------------------------------------------------------
# Layer 3: Behavioral rules
# -------------------------------------------------------------------

_TIMEOUT_PATTERNS = (
    "timed out",
    "timeout",
    "timeoutexpired",
    "deadline exceeded",
)

_RECURSION_PATTERNS = (
    "maximum recursion depth exceeded",
    "recursionerror",
)


def _check_behavioral(
    report: FailureReport,
    failure_history: Sequence[FailureReport] = (),
) -> Optional[RootCauseResult]:
    """Check for behavioral failures (loops, regressions, timeouts)."""
    combined = (report.exception_type + " " + report.message + " " +
                report.traceback).lower()

    # Infinite recursion
    for pattern in _RECURSION_PATTERNS:
        if pattern in combined:
            return RootCauseResult(
                resolved=True,
                category="behavioral",
                explanation="Infinite recursion detected",
                suggested_fix="Add termination condition to the recursive "
                              "call or convert to iterative approach.",
            )

    # Timeout
    for pattern in _TIMEOUT_PATTERNS:
        if pattern in combined:
            return RootCauseResult(
                resolved=True,
                category="behavioral",
                explanation="Operation timed out",
                suggested_fix="Increase timeout, optimize the slow "
                              "operation, or add a circuit breaker.",
            )

    # Repeated regression: same failure type 3+ times in history
    if len(failure_history) >= 2:
        current_type = report.exception_type
        repeat_count = sum(
            1 for h in failure_history
            if h.exception_type == current_type
        )
        if repeat_count >= 2:
            return RootCauseResult(
                resolved=False,
                category="behavioral",
                explanation=f"Repeated regression: '{current_type}' has "
                            f"occurred {repeat_count + 1} times",
                suggested_fix=None,
            )

    return None


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------


def analyze(
    report: FailureReport,
    failure_history: Sequence[FailureReport] = (),
) -> RootCauseResult:
    """Analyze a failure report through the layered rule engine.

    Checks are applied in priority order: structural → state → behavioral.
    The first match wins.  If no rule matches, returns an unresolved result.

    Args:
        report: The failure to analyze.
        failure_history: Previous failures for regression detection.

    Returns:
        A :class:`RootCauseResult` indicating whether the cause was
        identified and what to do about it.
    """
    # Layer 1: Structural
    result = _check_structural(report)
    if result is not None:
        return result

    # Layer 2: State
    result = _check_state(report)
    if result is not None:
        return result

    # Layer 3: Behavioral
    result = _check_behavioral(report, failure_history)
    if result is not None:
        return result

    # Unresolved — delegate to LLM
    return RootCauseResult(
        resolved=False,
        category="unknown",
        explanation=f"Could not determine root cause for "
                    f"{report.exception_type}: {report.message}",
        suggested_fix=None,
    )
