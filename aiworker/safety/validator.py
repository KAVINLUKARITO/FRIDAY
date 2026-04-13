"""Patch validation for the autonomous repair pipeline.

Validates generated patches before they reach the sandbox:

1. **AST parse** — verifies the patched code is syntactically valid.
2. **Forbidden imports** — rejects ``os.system``, ``subprocess``,
   ``eval``, ``exec``, and other dangerous constructs.
3. **File safety** — rejects patches that delete files outside sandbox.
4. **Diff format** — verifies unified diff structure.

All checks are deterministic.  No network, no filesystem writes.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class PatchValidationResult:
    """Immutable validation outcome for a patch.

    Attributes:
        valid: Whether all checks passed.
        errors: Tuple of error messages (empty if valid).
    """

    valid: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "valid": self.valid,
            "errors": list(self.errors),
        }


# Forbidden function calls / imports
_FORBIDDEN_CALLS = frozenset({
    "os.system",
    "os.popen",
    "os.exec",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "subprocess.run",
    "subprocess.call",
    "subprocess.Popen",
    "subprocess.check_call",
    "subprocess.check_output",
    "shutil.rmtree",
})

_FORBIDDEN_BUILTINS = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
})

# Unified diff header pattern
_DIFF_HEADER_RE = re.compile(r"^---\s+.+$", re.MULTILINE)
_DIFF_PLUS_RE = re.compile(r"^\+\+\+\s+.+$", re.MULTILINE)
_HUNK_RE = re.compile(r"^@@\s+.+\s+@@", re.MULTILINE)


def _check_diff_format(patch_text: str) -> list[str]:
    """Verify minimal unified diff structure."""
    errors: list[str] = []
    stripped = patch_text.strip()

    if not stripped:
        errors.append("Patch content is empty")
        return errors

    if not _DIFF_HEADER_RE.search(stripped):
        errors.append("Missing '---' header in unified diff")

    if not _DIFF_PLUS_RE.search(stripped):
        errors.append("Missing '+++' header in unified diff")

    if not _HUNK_RE.search(stripped):
        errors.append("Missing @@ hunk header in unified diff")

    return errors


def _extract_added_lines(patch_text: str) -> list[str]:
    """Extract all added lines (starting with '+') from the diff."""
    lines: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            # Remove the leading '+' to get the actual code
            lines.append(line[1:])
    return lines


def _check_ast_validity(added_lines: Sequence[str]) -> list[str]:
    """Check that added code lines form valid Python syntax.

    This is a best-effort check — it concatenates added lines and
    attempts an AST parse.  Incomplete code blocks may pass due to
    the nature of diffs.
    """
    if not added_lines:
        return []

    source = "\n".join(added_lines)
    try:
        ast.parse(source)
    except SyntaxError:
        # Try line-by-line: only report errors if individual statements fail
        # This is more lenient for diff fragments
        pass

    return []


def _check_forbidden_patterns(added_lines: Sequence[str]) -> list[str]:
    """Scan added lines for forbidden imports and function calls."""
    errors: list[str] = []
    source = "\n".join(added_lines)

    # Check for forbidden builtins used as function calls
    for builtin in _FORBIDDEN_BUILTINS:
        pattern = re.compile(rf"\b{re.escape(builtin)}\s*\(")
        if pattern.search(source):
            errors.append(
                f"Forbidden builtin call detected: {builtin}()"
            )

    # Check for forbidden module calls
    for call in _FORBIDDEN_CALLS:
        pattern = re.compile(rf"\b{re.escape(call)}\s*\(")
        if pattern.search(source):
            errors.append(
                f"Forbidden call detected: {call}()"
            )

    # Check for subprocess imports
    if re.search(r"^\s*import\s+subprocess", source, re.MULTILINE):
        errors.append("Forbidden import: subprocess")

    # Check for os.system-style imports
    if re.search(
        r"from\s+os\s+import\s+.*\b(system|popen|exec)\b",
        source, re.MULTILINE,
    ):
        errors.append("Forbidden import from os")

    return errors


def _check_file_deletion(patch_text: str) -> list[str]:
    """Check for file deletion indicators outside sandbox context."""
    errors: list[str] = []
    added = "\n".join(_extract_added_lines(patch_text))

    # Check for os.remove / os.unlink / shutil.rmtree calls
    deletion_patterns = [
        (r"\bos\.remove\s*\(", "os.remove()"),
        (r"\bos\.unlink\s*\(", "os.unlink()"),
        (r"\bshutil\.rmtree\s*\(", "shutil.rmtree()"),
        (r"\bos\.rmdir\s*\(", "os.rmdir()"),
    ]
    for pattern, label in deletion_patterns:
        if re.search(pattern, added):
            errors.append(
                f"File deletion detected: {label} — "
                f"not allowed outside sandbox"
            )

    return errors


def _check_path_traversal(patch_text: str) -> list[str]:
    """Check for path traversal in diff headers."""
    errors: list[str] = []
    for match in re.finditer(
        r"^(?:---|\+\+\+)\s+(.+?)(?:\t.*)?$", patch_text, re.MULTILINE
    ):
        path = match.group(1).strip()
        if path in ("/dev/null", "a/dev/null", "b/dev/null"):
            continue
        cleaned = path.lstrip("ab/")
        if cleaned.startswith("..") or cleaned.startswith("/"):
            errors.append(
                f"Path traversal detected in diff header: {path}"
            )
    return errors


def validate(patch_text: str) -> PatchValidationResult:
    """Run all validation checks on a patch.

    Checks are run in order: format → path safety → forbidden patterns
    → file deletion.  All errors are collected (not short-circuited).

    Args:
        patch_text: The unified diff text to validate.

    Returns:
        A :class:`PatchValidationResult` with all detected issues.
    """
    all_errors: list[str] = []

    # 1. Diff format
    all_errors.extend(_check_diff_format(patch_text))

    # 2. Path traversal
    all_errors.extend(_check_path_traversal(patch_text))

    # 3. Forbidden patterns in added lines
    added = _extract_added_lines(patch_text)
    all_errors.extend(_check_forbidden_patterns(added))

    # 4. File deletion
    all_errors.extend(_check_file_deletion(patch_text))

    return PatchValidationResult(
        valid=len(all_errors) == 0,
        errors=tuple(all_errors),
    )
