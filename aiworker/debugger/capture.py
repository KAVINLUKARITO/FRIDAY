"""Structured failure capture for the autonomous repair pipeline.

Captures structured information about test failures, exceptions, and
affected files.  All data is returned as frozen dataclasses with no
side effects.

No network calls, no filesystem writes, no global state.
"""

from __future__ import annotations

import re
import traceback as _tb
from dataclasses import dataclass
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class FailureReport:
    """Immutable structured failure information.

    Attributes:
        exception_type: Fully qualified exception class name.
        message: The exception message string.
        traceback: Full traceback text.
        failing_tests: Test identifiers that failed.
        affected_files: Source files implicated by the traceback.
    """

    exception_type: str
    message: str
    traceback: str
    failing_tests: tuple[str, ...]
    affected_files: tuple[str, ...]

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.exception_type or not self.exception_type.strip():
            errors.append("exception_type must be a non-empty string")
        if errors:
            raise ValueError(
                "Invalid FailureReport: " + "; ".join(errors)
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "exception_type": self.exception_type,
            "message": self.message,
            "traceback": self.traceback,
            "failing_tests": list(self.failing_tests),
            "affected_files": list(self.affected_files),
        }


_FILE_RE = re.compile(r'File "([^"]+\.py)"')


def _extract_affected_files(tb_text: str) -> tuple[str, ...]:
    """Extract unique .py file paths from a traceback string.

    Only includes paths containing ``aiworker/`` to avoid stdlib noise.
    Deterministic: same input produces same sorted output.
    """
    matches = _FILE_RE.findall(tb_text)
    unique = sorted({
        m for m in matches
        if "aiworker/" in m or "aiworker\\" in m
    })
    return tuple(unique)


def _extract_failing_tests(test_output: str) -> tuple[str, ...]:
    """Extract failing test identifiers from pytest-style output.

    Looks for patterns like ``FAILED test_foo.py::TestClass::test_method``.
    Deterministic: same input produces same sorted output.
    """
    pattern = re.compile(r"FAILED\s+(\S+)")
    matches = pattern.findall(test_output)
    return tuple(sorted(set(matches)))


def capture_exception(
    exc: BaseException,
    test_output: str = "",
    extra_files: Sequence[str] = (),
) -> FailureReport:
    """Build a FailureReport from a caught exception.

    Args:
        exc: The exception that was caught.
        test_output: Optional pytest stdout/stderr for test ID extraction.
        extra_files: Additional files known to be affected.

    Returns:
        A frozen :class:`FailureReport`.
    """
    exc_type = type(exc).__qualname__
    module = type(exc).__module__
    if module and module != "builtins":
        exc_type = f"{module}.{exc_type}"

    tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
    affected = _extract_affected_files(tb_text)
    if extra_files:
        combined = sorted(set(affected) | set(extra_files))
        affected = tuple(combined)

    failing = _extract_failing_tests(test_output)

    return FailureReport(
        exception_type=exc_type,
        message=str(exc),
        traceback=tb_text,
        failing_tests=failing,
        affected_files=affected,
    )


def capture_test_failure(
    test_output: str,
    stderr: str = "",
    exception_type: str = "TestFailure",
    message: str = "One or more tests failed",
) -> FailureReport:
    """Build a FailureReport from test runner output without a live exception.

    Args:
        test_output: The stdout from a test runner (e.g. pytest).
        stderr: The stderr from a test runner.
        exception_type: Classification of the failure.
        message: Human-readable summary.

    Returns:
        A frozen :class:`FailureReport`.
    """
    combined = test_output + "\n" + stderr
    affected = _extract_affected_files(combined)
    failing = _extract_failing_tests(combined)

    return FailureReport(
        exception_type=exception_type,
        message=message,
        traceback=combined.strip(),
        failing_tests=failing,
        affected_files=affected,
    )
