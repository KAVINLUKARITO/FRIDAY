"""Tests for the debugger package (capture + root cause analysis).

Covers:
- FailureReport construction, validation, immutability, serialisation
- Exception capture from live exceptions
- Test failure capture from output strings
- File extraction from tracebacks
- Failing test extraction from pytest output
- Root cause Layer 1: structural (ImportError, AttributeError, SyntaxError)
- Root cause Layer 2: state (circuit breaker, rate limit, missing table)
- Root cause Layer 3: behavioral (recursion, timeout, repeated regression)
- Unresolved fallback to unknown category
- Deterministic analysis

Uses unittest only — no pytest dependency.
"""

from __future__ import annotations

import unittest

from aiworker.debugger.capture import (
    FailureReport,
    capture_exception,
    capture_test_failure,
    _extract_affected_files,
    _extract_failing_tests,
)
from aiworker.debugger.root_cause import (
    RootCauseResult,
    analyze,
)


# ── FailureReport model ──────────────────────────────────────


class TestFailureReport(unittest.TestCase):
    """Verify FailureReport validation and immutability."""

    def test_valid_construction(self) -> None:
        report = FailureReport(
            exception_type="ValueError",
            message="bad input",
            traceback="Traceback...",
            failing_tests=("test_foo",),
            affected_files=("aiworker/foo.py",),
        )
        self.assertEqual(report.exception_type, "ValueError")

    def test_frozen(self) -> None:
        report = FailureReport(
            exception_type="ValueError",
            message="msg",
            traceback="tb",
            failing_tests=(),
            affected_files=(),
        )
        with self.assertRaises(AttributeError):
            report.exception_type = "changed"

    def test_empty_exception_type_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FailureReport(
                exception_type="",
                message="msg",
                traceback="tb",
                failing_tests=(),
                affected_files=(),
            )

    def test_to_dict(self) -> None:
        report = FailureReport(
            exception_type="ImportError",
            message="No module named 'foo'",
            traceback="tb",
            failing_tests=("test_a", "test_b"),
            affected_files=("aiworker/a.py",),
        )
        d = report.to_dict()
        self.assertEqual(d["exception_type"], "ImportError")
        self.assertIsInstance(d["failing_tests"], list)
        self.assertIsInstance(d["affected_files"], list)

    def test_empty_message_allowed(self) -> None:
        report = FailureReport(
            exception_type="RuntimeError",
            message="",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        self.assertEqual(report.message, "")


# ── File extraction ──────────────────────────────────────────


class TestFileExtraction(unittest.TestCase):
    """Verify traceback file path extraction."""

    def test_extracts_aiworker_paths(self) -> None:
        tb = '''
  File "/repo/aiworker/governance/policy.py", line 42, in evaluate
  File "/repo/aiworker/autonomy/loop.py", line 100, in run
  File "/usr/lib/python3.12/unittest/runner.py", line 10, in run
'''
        files = _extract_affected_files(tb)
        self.assertIn("/repo/aiworker/governance/policy.py", files)
        self.assertIn("/repo/aiworker/autonomy/loop.py", files)
        # stdlib should be excluded
        self.assertNotIn("/usr/lib/python3.12/unittest/runner.py", files)

    def test_empty_traceback(self) -> None:
        self.assertEqual(_extract_affected_files(""), ())

    def test_deterministic(self) -> None:
        tb = 'File "aiworker/a.py", line 1\nFile "aiworker/b.py", line 2'
        r1 = _extract_affected_files(tb)
        r2 = _extract_affected_files(tb)
        self.assertEqual(r1, r2)

    def test_deduplicates(self) -> None:
        tb = 'File "aiworker/a.py", line 1\nFile "aiworker/a.py", line 5'
        files = _extract_affected_files(tb)
        self.assertEqual(files.count("aiworker/a.py"), 1)


# ── Failing test extraction ──────────────────────────────────


class TestFailingTestExtraction(unittest.TestCase):
    """Verify pytest output test ID extraction."""

    def test_extracts_failed_tests(self) -> None:
        output = """
FAILED test_foo.py::TestFoo::test_bar
FAILED test_baz.py::test_qux
PASSED test_ok.py::test_ok
"""
        tests = _extract_failing_tests(output)
        self.assertIn("test_foo.py::TestFoo::test_bar", tests)
        self.assertIn("test_baz.py::test_qux", tests)
        self.assertEqual(len(tests), 2)

    def test_empty_output(self) -> None:
        self.assertEqual(_extract_failing_tests(""), ())

    def test_no_failures(self) -> None:
        self.assertEqual(_extract_failing_tests("4 passed in 0.1s"), ())


# ── Capture functions ────────────────────────────────────────


class TestCaptureException(unittest.TestCase):
    """Verify capture_exception builds reports from live exceptions."""

    def test_captures_import_error(self) -> None:
        try:
            raise ImportError("No module named 'fake_module'")
        except ImportError as exc:
            report = capture_exception(exc)
        self.assertIn("ImportError", report.exception_type)
        self.assertIn("fake_module", report.message)
        self.assertGreater(len(report.traceback), 0)

    def test_captures_with_test_output(self) -> None:
        try:
            raise ValueError("bad")
        except ValueError as exc:
            report = capture_exception(
                exc,
                test_output="FAILED test_x.py::test_y",
            )
        self.assertIn("test_x.py::test_y", report.failing_tests)

    def test_captures_extra_files(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            report = capture_exception(
                exc,
                extra_files=("aiworker/extra.py",),
            )
        self.assertIn("aiworker/extra.py", report.affected_files)


class TestCaptureTestFailure(unittest.TestCase):
    """Verify capture_test_failure builds reports from output strings."""

    def test_from_test_output(self) -> None:
        output = 'FAILED test_a.py::test_b\nFile "aiworker/foo.py", line 5'
        report = capture_test_failure(output)
        self.assertEqual(report.exception_type, "TestFailure")
        self.assertIn("test_a.py::test_b", report.failing_tests)
        self.assertIn("aiworker/foo.py", report.affected_files)

    def test_custom_exception_type(self) -> None:
        report = capture_test_failure(
            "error", exception_type="CustomError"
        )
        self.assertEqual(report.exception_type, "CustomError")


# ── RootCauseResult model ────────────────────────────────────


class TestRootCauseResult(unittest.TestCase):
    """Verify RootCauseResult validation and immutability."""

    def test_valid_construction(self) -> None:
        result = RootCauseResult(
            resolved=True,
            category="structural",
            explanation="Missing module",
            suggested_fix="Install module",
        )
        self.assertTrue(result.resolved)

    def test_frozen(self) -> None:
        result = RootCauseResult(
            resolved=False, category="unknown", explanation="test"
        )
        with self.assertRaises(AttributeError):
            result.resolved = True

    def test_empty_category_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RootCauseResult(resolved=False, category="", explanation="x")

    def test_empty_explanation_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RootCauseResult(resolved=False, category="x", explanation="")

    def test_to_dict(self) -> None:
        result = RootCauseResult(
            resolved=True,
            category="structural",
            explanation="Missing module",
            suggested_fix="Install it",
        )
        d = result.to_dict()
        self.assertTrue(d["resolved"])
        self.assertEqual(d["category"], "structural")
        self.assertIn("suggested_fix", d)


# ── Layer 1: Structural rules ────────────────────────────────


class TestStructuralRules(unittest.TestCase):
    """Verify Layer 1 root cause detection."""

    def test_import_error(self) -> None:
        report = FailureReport(
            exception_type="ModuleNotFoundError",
            message="No module named 'missing_pkg'",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "structural")
        self.assertIn("missing_pkg", result.explanation)
        self.assertIsNotNone(result.suggested_fix)

    def test_attribute_error(self) -> None:
        report = FailureReport(
            exception_type="AttributeError",
            message="module 'aiworker' has no attribute 'foo'",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "structural")
        self.assertIn("foo", result.explanation)

    def test_syntax_error(self) -> None:
        report = FailureReport(
            exception_type="SyntaxError",
            message="SyntaxError: invalid syntax",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "structural")

    def test_generic_attribute_error(self) -> None:
        report = FailureReport(
            exception_type="AttributeError",
            message="something weird happened",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "structural")


# ── Layer 2: State rules ─────────────────────────────────────


class TestStateRules(unittest.TestCase):
    """Verify Layer 2 root cause detection."""

    def test_circuit_breaker(self) -> None:
        report = FailureReport(
            exception_type="RuntimeError",
            message="Circuit breaker is open after 3 failures",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "state")
        self.assertIn("circuit breaker", result.explanation.lower())

    def test_rate_limit(self) -> None:
        report = FailureReport(
            exception_type="RuntimeError",
            message="Rate limit exceeded: too many attempts",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "state")

    def test_missing_table(self) -> None:
        report = FailureReport(
            exception_type="sqlite3.OperationalError",
            message="no such table: lessons",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "state")
        self.assertIn("lessons", result.explanation)


# ── Layer 3: Behavioral rules ────────────────────────────────


class TestBehavioralRules(unittest.TestCase):
    """Verify Layer 3 root cause detection."""

    def test_recursion_error(self) -> None:
        report = FailureReport(
            exception_type="RecursionError",
            message="maximum recursion depth exceeded",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "behavioral")

    def test_timeout(self) -> None:
        report = FailureReport(
            exception_type="TimeoutError",
            message="Operation timed out after 60s",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertTrue(result.resolved)
        self.assertEqual(result.category, "behavioral")

    def test_repeated_regression(self) -> None:
        current = FailureReport(
            exception_type="AssertionError",
            message="test failed",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        history = [
            FailureReport(
                exception_type="AssertionError",
                message="test failed",
                traceback="",
                failing_tests=(),
                affected_files=(),
            )
            for _ in range(3)
        ]
        result = analyze(current, failure_history=history)
        self.assertFalse(result.resolved)
        self.assertEqual(result.category, "behavioral")
        self.assertIn("regression", result.explanation.lower())

    def test_no_regression_with_short_history(self) -> None:
        current = FailureReport(
            exception_type="RuntimeError",
            message="something generic",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(current, failure_history=[])
        # Should fall through to unknown
        self.assertEqual(result.category, "unknown")


# ── Unresolved fallback ──────────────────────────────────────


class TestUnresolved(unittest.TestCase):
    """Verify unknown failures produce unresolved results."""

    def test_unknown_error(self) -> None:
        report = FailureReport(
            exception_type="RuntimeError",
            message="something completely unexpected",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        result = analyze(report)
        self.assertFalse(result.resolved)
        self.assertEqual(result.category, "unknown")
        self.assertIsNone(result.suggested_fix)

    def test_deterministic(self) -> None:
        report = FailureReport(
            exception_type="ImportError",
            message="No module named 'x'",
            traceback="",
            failing_tests=(),
            affected_files=(),
        )
        r1 = analyze(report)
        r2 = analyze(report)
        self.assertEqual(r1.resolved, r2.resolved)
        self.assertEqual(r1.category, r2.category)
        self.assertEqual(r1.explanation, r2.explanation)


if __name__ == "__main__":
    unittest.main()
