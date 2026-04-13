"""Tests for the secure sandbox execution module.

Validates:
- Sandbox creation and cleanup
- Path boundary enforcement
- Patch application (success and failure)
- Test execution inside the sandbox
- Timeout enforcement
- Structured JSON result format
"""

from __future__ import annotations

import os
import stat
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from aiworker.execution.patcher import Patcher, PatchResult
from aiworker.execution.runner import ExecutionResult, Runner, _parse_pytest_counts
from aiworker.execution.sandbox import Sandbox


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
    """Return a unified diff that adds a multiply function and a test."""
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


def _invalid_patch() -> str:
    """Return a deliberately broken unified diff."""
    return textwrap.dedent(
        """\
        --- a/nonexistent_file.py
        +++ b/nonexistent_file.py
        @@ -1,3 +1,4 @@
         this line does not exist
         neither does this one
        +added line
         also missing
        """
    )


def _timeout_patch() -> str:
    """Return a patch that creates a test which sleeps forever."""
    return textwrap.dedent(
        """\
        --- /dev/null
        +++ b/test_slow.py
        @@ -0,0 +1,6 @@
        +import time
        +
        +
        +def test_hangs():
        +    \"\"\"This test deliberately hangs to validate timeout enforcement.\"\"\"
        +    time.sleep(300)
        """
    )


# ---------------------------------------------------------------------------
# Sandbox tests
# ---------------------------------------------------------------------------

class TestSandbox:
    """Unit tests for :class:`Sandbox`."""

    def test_create_and_destroy(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        sandbox = Sandbox(workspace_path=str(ws))
        sandbox_dir = sandbox.create()

        assert os.path.isdir(sandbox_dir)
        assert os.path.isdir(sandbox.get_workspace_dir())
        assert os.path.isfile(
            os.path.join(sandbox.get_workspace_dir(), "math_utils.py")
        )

        sandbox.destroy()
        assert not os.path.exists(sandbox_dir)

    def test_workspace_not_found(self, tmp_path: Path) -> None:
        sandbox = Sandbox(workspace_path=str(tmp_path / "does_not_exist"))
        with pytest.raises(FileNotFoundError):
            sandbox.create()

    def test_validate_path_inside(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        sandbox = Sandbox(workspace_path=str(ws))
        sandbox.create()
        try:
            inner = os.path.join(sandbox.sandbox_dir, "workspace", "math_utils.py")  # type: ignore[arg-type]
            assert sandbox.validate_path(inner) == os.path.realpath(inner)
        finally:
            sandbox.destroy()

    def test_validate_path_traversal(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        sandbox = Sandbox(workspace_path=str(ws))
        sandbox.create()
        try:
            with pytest.raises(ValueError, match="Path traversal detected"):
                sandbox.validate_path("/etc/passwd")
        finally:
            sandbox.destroy()

    def test_destroy_is_idempotent(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        sandbox = Sandbox(workspace_path=str(ws))
        sandbox.create()
        sandbox.destroy()
        sandbox.destroy()  # should not raise

    def test_host_workspace_not_modified(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        original_contents = (ws / "math_utils.py").read_text()

        sandbox = Sandbox(workspace_path=str(ws))
        sandbox.create()
        try:
            sandbox_file = os.path.join(
                sandbox.get_workspace_dir(), "math_utils.py"
            )
            with open(sandbox_file, "a") as fh:
                fh.write("\n# modified in sandbox\n")
        finally:
            sandbox.destroy()

        assert (ws / "math_utils.py").read_text() == original_contents

    def test_destroy_removes_readonly_files(self, tmp_path: Path) -> None:
        """Sandbox with read-only files must still be fully cleaned up."""
        ws = _make_workspace(tmp_path)
        sandbox = Sandbox(workspace_path=str(ws))
        sandbox_dir = sandbox.create()

        # Create a read-only file inside the sandbox
        readonly_file = os.path.join(sandbox.get_workspace_dir(), "readonly.txt")
        with open(readonly_file, "w") as fh:
            fh.write("locked")
        os.chmod(readonly_file, stat.S_IRUSR)

        sandbox.destroy()
        assert not os.path.exists(sandbox_dir)


# ---------------------------------------------------------------------------
# Patcher tests
# ---------------------------------------------------------------------------

class TestPatcher:
    """Unit tests for :class:`Patcher`."""

    def test_apply_valid_patch(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        patcher = Patcher(target_dir=str(ws))
        result = patcher.apply(_valid_patch())

        assert result.success is True
        assert result.return_code == 0
        assert "multiply" in (ws / "math_utils.py").read_text()

    def test_apply_invalid_patch(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        patcher = Patcher(target_dir=str(ws))
        result = patcher.apply(_invalid_patch())

        assert result.success is False
        assert result.return_code != 0

    def test_result_to_dict(self) -> None:
        result = PatchResult(success=True, return_code=0, stdout="ok", stderr="")
        d = result.to_dict()
        assert d == {
            "success": True,
            "return_code": 0,
            "stdout": "ok",
            "stderr": "",
        }

    def test_patcher_nonexistent_dir(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Patcher(target_dir=str(tmp_path / "nope"))

    def test_rejects_absolute_path_in_patch(self, tmp_path: Path) -> None:
        """Patch with an absolute target path must be rejected before execution."""
        ws = _make_workspace(tmp_path)
        patcher = Patcher(target_dir=str(ws))
        malicious = textwrap.dedent(
            """\
            --- /dev/null
            +++ /tmp/hacked.txt
            @@ -0,0 +1 @@
            +pwned
            """
        )
        result = patcher.apply(malicious)
        assert result.success is False
        assert "absolute path" in result.stderr.lower() or "escape" in result.stderr.lower()

    def test_rejects_traversal_path_in_patch(self, tmp_path: Path) -> None:
        """Patch with ../../ path traversal must be rejected."""
        ws = _make_workspace(tmp_path)
        patcher = Patcher(target_dir=str(ws))
        malicious = textwrap.dedent(
            """\
            --- a/../../etc/passwd
            +++ b/../../etc/passwd
            @@ -0,0 +1 @@
            +hacked
            """
        )
        result = patcher.apply(malicious)
        assert result.success is False
        assert "traversal" in result.stderr.lower() or "escape" in result.stderr.lower()

    def test_allows_dev_null_in_patch(self, tmp_path: Path) -> None:
        """/dev/null is a standard diff sentinel and must not be rejected."""
        ws = _make_workspace(tmp_path)
        patcher = Patcher(target_dir=str(ws))
        safe = textwrap.dedent(
            """\
            --- /dev/null
            +++ b/new_file.py
            @@ -0,0 +1 @@
            +# new file
            """
        )
        result = patcher.apply(safe)
        assert result.success is True


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------

class TestRunner:
    """Integration tests for :class:`Runner`."""

    def test_successful_run(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        runner = Runner(
            workspace_path=str(ws),
            patch_content=_valid_patch(),
            timeout=60,
        )
        result = runner.execute()

        assert result.patch_applied is True
        assert result.success is True
        assert result.tests_passed >= 4
        assert result.tests_failed == 0
        assert result.error is None
        assert result.execution_time > 0

    def test_result_to_dict(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        runner = Runner(
            workspace_path=str(ws),
            patch_content=_valid_patch(),
            timeout=60,
        )
        result = runner.execute()
        d = result.to_dict()

        assert isinstance(d, dict)
        expected_keys = {
            "success",
            "patch_applied",
            "tests_passed",
            "tests_failed",
            "stdout",
            "stderr",
            "execution_time",
            "error",
        }
        assert set(d.keys()) == expected_keys

    def test_invalid_patch_returns_failure(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        runner = Runner(
            workspace_path=str(ws),
            patch_content=_invalid_patch(),
            timeout=60,
        )
        result = runner.execute()

        assert result.success is False
        assert result.patch_applied is False
        assert result.error is not None

    def test_sandbox_deleted_after_execution(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        runner = Runner(
            workspace_path=str(ws),
            patch_content=_valid_patch(),
            timeout=60,
        )
        result = runner.execute()

        # After execute(), no sandbox temp directories should remain that
        # were created by *this* run.  We verify by checking no
        # aiworker_sandbox_ dirs exist in the system temp directory.
        temp_root = tempfile.gettempdir()
        remaining = [
            d
            for d in os.listdir(temp_root)
            if d.startswith("aiworker_sandbox_") and os.path.isdir(os.path.join(temp_root, d))
        ]
        assert len(remaining) == 0, f"Sandbox not cleaned up: {remaining}"

    def test_timeout_enforcement(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        runner = Runner(
            workspace_path=str(ws),
            patch_content=_timeout_patch(),
            timeout=3,
        )
        start = time.monotonic()
        result = runner.execute()
        elapsed = time.monotonic() - start

        assert result.success is False
        assert result.patch_applied is True
        assert "timed out" in (result.stderr or "").lower() or "timeout" in (result.error or "").lower()
        assert elapsed < 30, "Timeout was not enforced in a reasonable time"

    def test_invalid_timeout(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            Runner(workspace_path="/tmp", patch_content="", timeout=0)
        with pytest.raises(ValueError):
            Runner(workspace_path="/tmp", patch_content="", timeout=999)

    def test_restricted_env_uses_allowlist(self) -> None:
        """Verify _restricted_env only forwards allowlisted variables."""
        env = Runner._restricted_env()
        # Proxy vars must be present
        assert env["http_proxy"] == "http://0.0.0.0:0"
        assert env["HTTPS_PROXY"] == "http://0.0.0.0:0"
        # PATH should be forwarded (it's allowlisted)
        if "PATH" in os.environ:
            assert "PATH" in env
        # Secrets / tokens from the host must NOT leak
        for key in env:
            assert key in Runner._ENV_ALLOWLIST or key.lower().endswith("_proxy") or key == "no_proxy", (
                f"Unexpected env var leaked to sandbox: {key}"
            )


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestParsePytestCounts:
    """Tests for :func:`_parse_pytest_counts`."""

    def test_all_passed(self) -> None:
        assert _parse_pytest_counts("4 passed in 0.12s") == (4, 0)

    def test_mixed(self) -> None:
        assert _parse_pytest_counts("3 passed, 1 failed in 0.50s") == (3, 1)

    def test_no_results(self) -> None:
        assert _parse_pytest_counts("no tests ran") == (0, 0)
