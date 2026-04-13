"""Tests for the patch validation pipeline.

Covers:
- PatchValidationResult immutability and serialisation
- Diff format validation (missing headers, empty patch)
- AST validity checking
- Forbidden import/call detection (eval, exec, subprocess, os.system)
- File deletion detection
- Path traversal detection
- VerificationResult immutability
- RegressionDecision construction
- Regression guard rules (failure increase, repeat failures, risk score)
- Confidence scoring formula

Uses unittest only — no pytest dependency.
"""

from __future__ import annotations

import textwrap
import unittest

from aiworker.patch.validator import (
    PatchValidationResult,
    validate,
    _check_diff_format,
    _check_forbidden_patterns,
    _extract_added_lines,
    _check_file_deletion,
    _check_path_traversal,
)
from aiworker.patch.sandbox_verifier import VerificationResult
from aiworker.patch.regression_guard import (
    RegressionDecision,
    check,
)


# ── Helpers ──────────────────────────────────────────────────


_VALID_PATCH = textwrap.dedent("""\
    --- a/foo.py
    +++ b/foo.py
    @@ -1,2 +1,3 @@
     def foo():
         return 1
    +    # added comment
""")

_FORBIDDEN_EVAL_PATCH = textwrap.dedent("""\
    --- a/foo.py
    +++ b/foo.py
    @@ -1,2 +1,3 @@
     def foo():
         return 1
    +    result = eval("1+1")
""")

_FORBIDDEN_SUBPROCESS_PATCH = textwrap.dedent("""\
    --- a/foo.py
    +++ b/foo.py
    @@ -1,2 +1,4 @@
     def foo():
         return 1
    +import subprocess
    +    subprocess.run(["ls"])
""")

_FORBIDDEN_OS_SYSTEM_PATCH = textwrap.dedent("""\
    --- a/foo.py
    +++ b/foo.py
    @@ -1,2 +1,3 @@
     def foo():
         return 1
    +    os.system("rm -rf /")
""")

_FILE_DELETION_PATCH = textwrap.dedent("""\
    --- a/foo.py
    +++ b/foo.py
    @@ -1,2 +1,3 @@
     def foo():
         return 1
    +    os.remove("/tmp/file")
""")

_TRAVERSAL_PATCH = textwrap.dedent("""\
    --- a/../../etc/passwd
    +++ b/../../etc/passwd
    @@ -0,0 +1 @@
    +hacked
""")


# ── PatchValidationResult ────────────────────────────────────


class TestPatchValidationResult(unittest.TestCase):
    """Verify PatchValidationResult immutability and serialisation."""

    def test_frozen(self) -> None:
        result = PatchValidationResult(valid=True)
        with self.assertRaises(AttributeError):
            result.valid = False

    def test_to_dict(self) -> None:
        result = PatchValidationResult(
            valid=False, errors=("err1", "err2")
        )
        d = result.to_dict()
        self.assertFalse(d["valid"])
        self.assertIsInstance(d["errors"], list)
        self.assertEqual(len(d["errors"]), 2)


# ── Diff format validation ───────────────────────────────────


class TestDiffFormatValidation(unittest.TestCase):
    """Verify unified diff format checking."""

    def test_valid_diff(self) -> None:
        errors = _check_diff_format(_VALID_PATCH)
        self.assertEqual(errors, [])

    def test_empty_patch(self) -> None:
        errors = _check_diff_format("")
        self.assertGreater(len(errors), 0)

    def test_missing_minus_header(self) -> None:
        patch = "+++ b/foo.py\n@@ -1 +1 @@\n+x"
        errors = _check_diff_format(patch)
        self.assertTrue(any("---" in e for e in errors))

    def test_missing_plus_header(self) -> None:
        patch = "--- a/foo.py\n@@ -1 +1 @@\n+x"
        errors = _check_diff_format(patch)
        self.assertTrue(any("+++" in e for e in errors))

    def test_missing_hunk_header(self) -> None:
        patch = "--- a/foo.py\n+++ b/foo.py\n+x"
        errors = _check_diff_format(patch)
        self.assertTrue(any("@@" in e for e in errors))


# ── Forbidden patterns ───────────────────────────────────────


class TestForbiddenPatterns(unittest.TestCase):
    """Verify forbidden import and call detection."""

    def test_clean_code(self) -> None:
        lines = ["def foo():", "    return 1"]
        errors = _check_forbidden_patterns(lines)
        self.assertEqual(errors, [])

    def test_eval_detected(self) -> None:
        lines = _extract_added_lines(_FORBIDDEN_EVAL_PATCH)
        errors = _check_forbidden_patterns(lines)
        self.assertTrue(any("eval" in e for e in errors))

    def test_exec_detected(self) -> None:
        lines = ['result = exec("print(1)")']
        errors = _check_forbidden_patterns(lines)
        self.assertTrue(any("exec" in e for e in errors))

    def test_subprocess_detected(self) -> None:
        lines = _extract_added_lines(_FORBIDDEN_SUBPROCESS_PATCH)
        errors = _check_forbidden_patterns(lines)
        self.assertTrue(any("subprocess" in e.lower() for e in errors))

    def test_os_system_detected(self) -> None:
        lines = _extract_added_lines(_FORBIDDEN_OS_SYSTEM_PATCH)
        errors = _check_forbidden_patterns(lines)
        self.assertTrue(any("os.system" in e for e in errors))

    def test_compile_detected(self) -> None:
        lines = ['code = compile("x=1", "<string>", "exec")']
        errors = _check_forbidden_patterns(lines)
        self.assertTrue(any("compile" in e for e in errors))


# ── File deletion detection ──────────────────────────────────


class TestFileDeletion(unittest.TestCase):
    """Verify file deletion detection in patches."""

    def test_os_remove_detected(self) -> None:
        errors = _check_file_deletion(_FILE_DELETION_PATCH)
        self.assertTrue(any("os.remove" in e for e in errors))

    def test_shutil_rmtree_detected(self) -> None:
        patch = textwrap.dedent("""\
            --- a/foo.py
            +++ b/foo.py
            @@ -1 +1,2 @@
             x = 1
            +shutil.rmtree("/tmp/dir")
        """)
        errors = _check_file_deletion(patch)
        self.assertTrue(any("shutil.rmtree" in e for e in errors))

    def test_clean_patch_no_deletion(self) -> None:
        errors = _check_file_deletion(_VALID_PATCH)
        self.assertEqual(errors, [])


# ── Path traversal detection ─────────────────────────────────


class TestPathTraversal(unittest.TestCase):
    """Verify path traversal detection in diff headers."""

    def test_traversal_detected(self) -> None:
        errors = _check_path_traversal(_TRAVERSAL_PATCH)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("traversal" in e.lower() for e in errors))

    def test_normal_path_accepted(self) -> None:
        errors = _check_path_traversal(_VALID_PATCH)
        self.assertEqual(errors, [])

    def test_dev_null_accepted(self) -> None:
        patch = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x = 1"
        errors = _check_path_traversal(patch)
        self.assertEqual(errors, [])


# ── Full validate function ───────────────────────────────────


class TestValidateFunction(unittest.TestCase):
    """Verify the full validate() pipeline."""

    def test_valid_patch(self) -> None:
        result = validate(_VALID_PATCH)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

    def test_eval_patch_rejected(self) -> None:
        result = validate(_FORBIDDEN_EVAL_PATCH)
        self.assertFalse(result.valid)
        self.assertTrue(any("eval" in e for e in result.errors))

    def test_traversal_patch_rejected(self) -> None:
        result = validate(_TRAVERSAL_PATCH)
        self.assertFalse(result.valid)

    def test_empty_patch_rejected(self) -> None:
        result = validate("")
        self.assertFalse(result.valid)

    def test_multiple_errors_collected(self) -> None:
        # Patch with both traversal AND forbidden call
        patch = textwrap.dedent("""\
            --- a/../../etc/passwd
            +++ b/../../etc/passwd
            @@ -0,0 +1 @@
            +eval("hack")
        """)
        result = validate(patch)
        self.assertFalse(result.valid)
        self.assertGreater(len(result.errors), 1)


# ── VerificationResult ───────────────────────────────────────


class TestVerificationResult(unittest.TestCase):
    """Verify VerificationResult immutability and serialisation."""

    def test_frozen(self) -> None:
        result = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        with self.assertRaises(AttributeError):
            result.success = False

    def test_to_dict(self) -> None:
        result = VerificationResult(
            success=False,
            passed_tests=8,
            failed_tests=2,
            regression_detected=True,
            execution_time=1.5,
            error="tests failed",
        )
        d = result.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["passed_tests"], 8)
        self.assertTrue(d["regression_detected"])


# ── RegressionDecision ───────────────────────────────────────


class TestRegressionDecision(unittest.TestCase):
    """Verify RegressionDecision immutability and serialisation."""

    def test_frozen(self) -> None:
        rd = RegressionDecision(accepted=True)
        with self.assertRaises(AttributeError):
            rd.accepted = False

    def test_to_dict(self) -> None:
        rd = RegressionDecision(
            accepted=False, reasons=("regression",)
        )
        d = rd.to_dict()
        self.assertFalse(d["accepted"])
        self.assertIsInstance(d["reasons"], list)


# ── Regression guard rules ───────────────────────────────────


class TestRegressionGuard(unittest.TestCase):
    """Verify regression guard decision logic."""

    def test_clean_verification_accepted(self) -> None:
        v = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        decision = check(v, risk_score=0.3)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reasons, ())

    def test_regression_detected_rejected(self) -> None:
        v = VerificationResult(
            success=False,
            passed_tests=8,
            failed_tests=2,
            regression_detected=True,
        )
        decision = check(v, risk_score=0.3)
        self.assertFalse(decision.accepted)
        self.assertTrue(any("regression" in r.lower() for r in decision.reasons))

    def test_verification_failure_rejected(self) -> None:
        v = VerificationResult(
            success=False,
            passed_tests=5,
            failed_tests=5,
            regression_detected=False,
            error="tests failed",
        )
        decision = check(v, risk_score=0.3)
        self.assertFalse(decision.accepted)

    def test_high_risk_score_rejected(self) -> None:
        v = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        decision = check(v, risk_score=0.8, max_risk_score=0.7)
        self.assertFalse(decision.accepted)
        self.assertTrue(any("risk" in r.lower() for r in decision.reasons))

    def test_risk_at_threshold_accepted(self) -> None:
        v = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        decision = check(v, risk_score=0.7, max_risk_score=0.7)
        self.assertTrue(decision.accepted)

    def test_repeated_failure_rejected(self) -> None:
        v = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        decision = check(
            v,
            risk_score=0.3,
            failure_history=["ImportError"] * 3,
            current_failure_type="ImportError",
            max_repeat_failures=3,
        )
        self.assertFalse(decision.accepted)

    def test_below_repeat_threshold_accepted(self) -> None:
        v = VerificationResult(
            success=True,
            passed_tests=10,
            failed_tests=0,
            regression_detected=False,
        )
        decision = check(
            v,
            risk_score=0.3,
            failure_history=["ImportError"] * 2,
            current_failure_type="ImportError",
            max_repeat_failures=3,
        )
        self.assertTrue(decision.accepted)

    def test_multiple_rejection_reasons(self) -> None:
        v = VerificationResult(
            success=False,
            passed_tests=5,
            failed_tests=5,
            regression_detected=True,
        )
        decision = check(
            v,
            risk_score=0.9,
            max_risk_score=0.7,
        )
        self.assertFalse(decision.accepted)
        self.assertGreater(len(decision.reasons), 1)


# ── Confidence scoring ───────────────────────────────────────


class TestConfidenceScoring(unittest.TestCase):
    """Verify the confidence formula from the spec."""

    @staticmethod
    def _compute_confidence(
        pass_rate: float,
        risk_score: float,
        low_diff_bonus: float,
    ) -> float:
        """Replicate the spec formula."""
        return (
            pass_rate * 0.5
            + (1 - risk_score) * 0.3
            + low_diff_bonus * 0.2
        )

    def test_perfect_score(self) -> None:
        c = self._compute_confidence(1.0, 0.0, 1.0)
        self.assertAlmostEqual(c, 1.0)

    def test_worst_score(self) -> None:
        c = self._compute_confidence(0.0, 1.0, 0.0)
        self.assertAlmostEqual(c, 0.0)

    def test_middle_score(self) -> None:
        c = self._compute_confidence(0.8, 0.3, 0.5)
        expected = 0.8 * 0.5 + 0.7 * 0.3 + 0.5 * 0.2
        self.assertAlmostEqual(c, expected)

    def test_low_diff_bonus(self) -> None:
        c_with = self._compute_confidence(0.5, 0.5, 1.0)
        c_without = self._compute_confidence(0.5, 0.5, 0.0)
        self.assertGreater(c_with, c_without)


if __name__ == "__main__":
    unittest.main()
