"""Tests for the controlled self-modification engine (Milestone 2).

Validates:
- ChangeRequest construction and validation
- PatchValidator constraint enforcement
- Approval gate logic
- Engine orchestration
- Security invariants (no workspace modification, no auto-approve)
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from aiworker.execution.runner import ExecutionResult
from aiworker.self_modify.approval import ApprovalDecision, evaluate_approval
from aiworker.self_modify.change_request import ChangeRequest
from aiworker.self_modify.engine import EngineResult, process_change_request
from aiworker.self_modify.patch_validator import (
    ValidationResult,
    validate_patch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with a Python file and a test."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "math_utils.py").write_text(
        textwrap.dedent(
            """\
            def add(a: int, b: int) -> int:
                return a + b
            """
        )
    )
    (ws / "test_math_utils.py").write_text(
        textwrap.dedent(
            """\
            from math_utils import add

            def test_add():
                assert add(1, 2) == 3

            def test_add_negative():
                assert add(-1, -2) == -3
            """
        )
    )
    return ws


def _valid_patch() -> str:
    """Patch that adds a multiply function and tests."""
    return textwrap.dedent(
        """\
        --- a/math_utils.py
        +++ b/math_utils.py
        @@ -1,2 +1,6 @@
         def add(a: int, b: int) -> int:
             return a + b
        +
        +
        +def multiply(a: int, b: int) -> int:
        +    return a * b
        --- a/test_math_utils.py
        +++ b/test_math_utils.py
        @@ -1,7 +1,14 @@
         from math_utils import add
        +from math_utils import multiply
         
         def test_add():
             assert add(1, 2) == 3
         
         def test_add_negative():
             assert add(-1, -2) == -3
        +
        +def test_multiply():
        +    assert multiply(3, 4) == 12
        +
        +def test_multiply_zero():
        +    assert multiply(0, 5) == 0
        """
    )


def _valid_change_request() -> ChangeRequest:
    """ChangeRequest that allows the valid_patch() files."""
    return ChangeRequest(
        goal="Add multiply function",
        allowed_files=["math_utils.py", "test_math_utils.py"],
        forbidden_files=["secrets.py"],
        max_lines_changed=50,
        tests_required=True,
        risk_level="low",
    )


def _successful_sandbox_result() -> ExecutionResult:
    """Simulate a successful sandbox execution."""
    return ExecutionResult(
        success=True,
        patch_applied=True,
        tests_passed=4,
        tests_failed=0,
        stdout="4 passed in 0.10s",
        stderr="",
        execution_time=0.1,
        error=None,
    )


def _failed_sandbox_result() -> ExecutionResult:
    """Simulate a failed sandbox execution."""
    return ExecutionResult(
        success=False,
        patch_applied=True,
        tests_passed=2,
        tests_failed=1,
        stdout="2 passed, 1 failed in 0.10s",
        stderr="",
        execution_time=0.1,
        error="Some tests failed.",
    )


# ---------------------------------------------------------------------------
# ChangeRequest tests
# ---------------------------------------------------------------------------

class TestChangeRequest:
    """Validation of ChangeRequest construction."""

    def test_valid_change_request(self) -> None:
        cr = _valid_change_request()
        assert cr.goal == "Add multiply function"
        assert cr.risk_level == "low"

    def test_empty_allowed_files_rejected(self) -> None:
        with pytest.raises(ValueError, match="allowed_files must not be empty"):
            ChangeRequest(
                goal="Bad request",
                allowed_files=[],
            )

    def test_invalid_risk_level_rejected(self) -> None:
        with pytest.raises(ValueError, match="risk_level"):
            ChangeRequest(
                goal="Bad request",
                allowed_files=["a.py"],
                risk_level="critical",  # type: ignore[arg-type]
            )

    def test_max_lines_too_large_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_lines_changed"):
            ChangeRequest(
                goal="Bad request",
                allowed_files=["a.py"],
                max_lines_changed=500,
            )

    def test_max_lines_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_lines_changed"):
            ChangeRequest(
                goal="Bad request",
                allowed_files=["a.py"],
                max_lines_changed=0,
            )

    def test_empty_goal_rejected(self) -> None:
        with pytest.raises(ValueError, match="goal"):
            ChangeRequest(
                goal="",
                allowed_files=["a.py"],
            )

    def test_overlapping_allowed_forbidden_rejected(self) -> None:
        with pytest.raises(ValueError, match="both allowed and forbidden"):
            ChangeRequest(
                goal="Overlap",
                allowed_files=["a.py", "b.py"],
                forbidden_files=["b.py"],
            )

    def test_to_dict(self) -> None:
        cr = _valid_change_request()
        d = cr.to_dict()
        assert d["goal"] == "Add multiply function"
        assert d["risk_level"] == "low"
        assert isinstance(d["allowed_files"], list)


# ---------------------------------------------------------------------------
# PatchValidator tests
# ---------------------------------------------------------------------------

class TestPatchValidator:
    """Validation of patch content against ChangeRequest constraints."""

    def test_valid_patch_passes(self) -> None:
        result = validate_patch(_valid_patch(), _valid_change_request())
        assert result.valid is True
        assert result.total_lines_changed > 0

    def test_empty_patch_rejected(self) -> None:
        result = validate_patch("", _valid_change_request())
        assert result.valid is False
        assert "empty" in result.errors[0].lower()

    def test_forbidden_file_rejected(self) -> None:
        patch = textwrap.dedent(
            """\
            --- a/secrets.py
            +++ b/secrets.py
            @@ -1 +1,2 @@
             SECRET = "old"
            +SECRET = "new"
            """
        )
        cr = ChangeRequest(
            goal="Touch forbidden",
            allowed_files=["app.py"],
            forbidden_files=["secrets.py"],
        )
        result = validate_patch(patch, cr)
        assert result.valid is False
        assert any("forbidden" in e.lower() for e in result.errors)

    def test_file_outside_allowed_rejected(self) -> None:
        patch = textwrap.dedent(
            """\
            --- a/other.py
            +++ b/other.py
            @@ -1 +1,2 @@
             x = 1
            +x = 2
            """
        )
        cr = ChangeRequest(
            goal="Only math",
            allowed_files=["math_utils.py"],
        )
        result = validate_patch(patch, cr)
        assert result.valid is False
        assert any("not in allowed_files" in e for e in result.errors)

    def test_exceeding_line_limit_rejected(self) -> None:
        # Create a patch with many lines
        lines = "\n".join(f"+line_{i} = {i}" for i in range(60))
        patch = textwrap.dedent(
            f"""\
            --- a/math_utils.py
            +++ b/math_utils.py
            @@ -1,2 +1,62 @@
             def add(a: int, b: int) -> int:
                 return a + b
            {lines}
            """
        )
        cr = ChangeRequest(
            goal="Too many lines",
            allowed_files=["math_utils.py"],
            max_lines_changed=10,
        )
        result = validate_patch(patch, cr)
        assert result.valid is False
        assert any("exceeding limit" in e.lower() for e in result.errors)

    def test_absolute_path_rejected(self) -> None:
        patch = textwrap.dedent(
            """\
            --- /dev/null
            +++ /etc/passwd
            @@ -0,0 +1 @@
            +hacked
            """
        )
        result = validate_patch(patch, _valid_change_request())
        assert result.valid is False
        assert any("absolute" in e.lower() for e in result.errors)

    def test_traversal_path_rejected(self) -> None:
        patch = textwrap.dedent(
            """\
            --- a/../../etc/passwd
            +++ b/../../etc/passwd
            @@ -0,0 +1 @@
            +hacked
            """
        )
        result = validate_patch(patch, _valid_change_request())
        assert result.valid is False
        assert any("traversal" in e.lower() for e in result.errors)

    def test_binary_diff_rejected(self) -> None:
        patch = "Binary files a/image.png and b/image.png differ\n"
        result = validate_patch(patch, _valid_change_request())
        assert result.valid is False
        assert any("binary" in e.lower() for e in result.errors)

    def test_validation_result_to_dict(self) -> None:
        result = validate_patch(_valid_patch(), _valid_change_request())
        d = result.to_dict()
        assert "valid" in d
        assert "total_lines_changed" in d

    def test_dev_null_not_counted_as_file(self) -> None:
        """The /dev/null sentinel should not appear in files_touched."""
        patch = textwrap.dedent(
            """\
            --- /dev/null
            +++ b/math_utils.py
            @@ -0,0 +1 @@
            +# new
            """
        )
        cr = ChangeRequest(
            goal="New file from null",
            allowed_files=["math_utils.py"],
        )
        result = validate_patch(patch, cr)
        assert "/dev/null" not in result.files_touched


# ---------------------------------------------------------------------------
# Approval tests
# ---------------------------------------------------------------------------

class TestApproval:
    """Approval gate logic."""

    def test_failed_sandbox_rejects(self) -> None:
        decision = evaluate_approval(
            _valid_change_request(), _failed_sandbox_result()
        )
        assert decision.eligible is False
        assert "failed" in decision.reason.lower()

    def test_successful_sandbox_eligible(self) -> None:
        decision = evaluate_approval(
            _valid_change_request(), _successful_sandbox_result()
        )
        assert decision.eligible is True
        assert decision.requires_manual_review is False

    def test_high_risk_requires_manual(self) -> None:
        cr = ChangeRequest(
            goal="Risky change",
            allowed_files=["a.py"],
            risk_level="high",
        )
        decision = evaluate_approval(cr, _successful_sandbox_result())
        assert decision.requires_manual_review is True
        assert decision.eligible is False  # not explicitly approved

    def test_high_risk_with_approval(self) -> None:
        cr = ChangeRequest(
            goal="Risky change",
            allowed_files=["a.py"],
            risk_level="high",
        )
        decision = evaluate_approval(
            cr, _successful_sandbox_result(), explicit_approval=True
        )
        assert decision.requires_manual_review is True
        assert decision.eligible is True

    def test_tests_required_with_failures_rejects(self) -> None:
        cr = ChangeRequest(
            goal="With tests",
            allowed_files=["a.py"],
            tests_required=True,
        )
        result = ExecutionResult(
            success=True,
            patch_applied=True,
            tests_passed=3,
            tests_failed=1,
            stdout="",
            stderr="",
            execution_time=0.1,
            error=None,
        )
        decision = evaluate_approval(cr, result)
        assert decision.eligible is False
        assert "failed" in decision.reason.lower()

    def test_decision_to_dict(self) -> None:
        decision = evaluate_approval(
            _valid_change_request(), _successful_sandbox_result()
        )
        d = decision.to_dict()
        assert "eligible" in d
        assert "requires_manual_review" in d
        assert "reason" in d


# ---------------------------------------------------------------------------
# Engine integration tests
# ---------------------------------------------------------------------------

class TestEngine:
    """Integration tests for the self-modification engine."""

    def test_valid_request_returns_approval_required(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        result = process_change_request(
            _valid_change_request(), _valid_patch(), str(ws), timeout=60,
        )
        assert result.validation_passed is True
        assert result.approval_required is True
        assert result.approved is False  # no explicit approval
        assert result.sandbox_result is not None
        assert result.sandbox_result.success is True

    def test_failed_sandbox_returns_not_approved(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        bad_patch = textwrap.dedent(
            """\
            --- a/math_utils.py
            +++ b/math_utils.py
            @@ -1,2 +1,2 @@
             def add(a: int, b: int) -> int:
            -    return a + b
            +    return a - b
            """
        )
        cr = ChangeRequest(
            goal="Break add",
            allowed_files=["math_utils.py"],
            tests_required=True,
        )
        result = process_change_request(cr, bad_patch, str(ws), timeout=60)
        assert result.validation_passed is True
        assert result.approved is False
        # Tests should fail since add(1,2) would return -1
        assert result.sandbox_result is not None

    def test_invalid_patch_rejected_before_sandbox(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        patch = textwrap.dedent(
            """\
            --- a/../../etc/passwd
            +++ b/../../etc/passwd
            @@ -0,0 +1 @@
            +pwned
            """
        )
        result = process_change_request(
            _valid_change_request(), patch, str(ws), timeout=60,
        )
        assert result.validation_passed is False
        assert result.sandbox_result is None
        assert result.approved is False

    def test_workspace_not_modified(self, tmp_path: Path) -> None:
        """Engine must NEVER modify the original workspace."""
        ws = _make_workspace(tmp_path)
        original = (ws / "math_utils.py").read_text()

        process_change_request(
            _valid_change_request(), _valid_patch(), str(ws), timeout=60,
        )

        assert (ws / "math_utils.py").read_text() == original

    def test_engine_result_to_dict(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        result = process_change_request(
            _valid_change_request(), _valid_patch(), str(ws), timeout=60,
        )
        d = result.to_dict()
        expected_keys = {
            "validation_passed",
            "validation_result",
            "sandbox_result",
            "approval_decision",
            "approval_required",
            "approved",
            "decision_context",
            "reason",
        }
        assert set(d.keys()) == expected_keys

    def test_explicit_approval_grants_approved(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        result = process_change_request(
            _valid_change_request(),
            _valid_patch(),
            str(ws),
            timeout=60,
            explicit_approval=True,
        )
        assert result.validation_passed is True
        assert result.approved is True
