"""Unified diff patch validator.

Validates a patch against the constraints defined in a
:class:`~aiworker.self_modify.change_request.ChangeRequest`:

* Only allowed files may be touched.
* Forbidden files must not appear.
* Total added + removed lines must not exceed the budget.
* Absolute paths and path-traversal sequences are rejected.
* Binary diffs are rejected.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List

from aiworker.self_modify.change_request import ChangeRequest

# Regex that matches unified diff file headers (--- and +++ lines).
_HEADER_RE = re.compile(r"^(?:---|\+\+\+)\s+(.+?)(?:\t.*)?$", re.MULTILINE)

# Regex to detect binary diff markers.
_BINARY_RE = re.compile(
    r"^(?:Binary files .* differ|GIT binary patch)", re.MULTILINE
)


@dataclass
class ValidationResult:
    """Outcome of patch validation.

    Attributes:
        valid: Whether the patch passed all checks.
        errors: List of human-readable reasons for rejection.
        files_touched: Unique file paths referenced by the patch.
        lines_added: Total number of ``+`` (added) lines.
        lines_removed: Total number of ``-`` (removed) lines.
    """

    valid: bool
    errors: List[str] = field(default_factory=list)
    files_touched: List[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0

    @property
    def total_lines_changed(self) -> int:
        """Sum of added and removed lines."""
        return self.lines_added + self.lines_removed

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dictionary."""
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "files_touched": list(self.files_touched),
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "total_lines_changed": self.total_lines_changed,
        }


def _extract_files(patch_content: str) -> list[str]:
    """Extract unique file paths from diff headers.

    Strips the leading ``a/`` or ``b/`` prefix added by ``git diff``
    and skips the ``/dev/null`` sentinel.
    """
    files: list[str] = []
    for match in _HEADER_RE.finditer(patch_content):
        raw = match.group(1).strip()
        if raw in ("/dev/null", "a/dev/null", "b/dev/null"):
            continue
        if raw.startswith(("a/", "b/")):
            raw = raw[2:]
        if raw and raw not in files:
            files.append(raw)
    return files


def _count_lines(patch_content: str) -> tuple[int, int]:
    """Count added and removed content lines in a unified diff.

    Only lines starting with a single ``+`` or ``-`` (but NOT ``+++``
    or ``---`` headers) are counted.
    """
    added = 0
    removed = 0
    for line in patch_content.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def validate_patch(
    patch_content: str, change_request: ChangeRequest
) -> ValidationResult:
    """Validate *patch_content* against *change_request* constraints.

    Checks performed (in order):

    1. Reject empty patches.
    2. Reject binary diffs.
    3. Reject absolute paths or ``../`` traversal in file headers.
    4. Reject files not in ``allowed_files``.
    5. Reject files in ``forbidden_files``.
    6. Reject if total lines changed exceeds budget.

    Returns:
        A :class:`ValidationResult` describing the outcome.
    """
    errors: list[str] = []

    # 1 — empty patch
    stripped = patch_content.strip()
    if not stripped:
        return ValidationResult(valid=False, errors=["Patch content is empty"])

    # 2 — binary diff
    if _BINARY_RE.search(patch_content):
        return ValidationResult(
            valid=False, errors=["Binary diffs are not allowed"]
        )

    # 3 — path safety
    files = _extract_files(patch_content)
    for fpath in files:
        if os.path.isabs(fpath):
            errors.append(
                f"Absolute path not allowed in patch: {fpath!r}"
            )
        normalized = os.path.normpath(fpath)
        if normalized.startswith(".."):
            errors.append(
                f"Path traversal detected in patch: {fpath!r}"
            )

    if errors:
        return ValidationResult(
            valid=False, errors=errors, files_touched=files
        )

    # 4 — allowed files
    allowed_set = set(change_request.allowed_files)
    for fpath in files:
        if fpath not in allowed_set:
            errors.append(
                f"File {fpath!r} is not in allowed_files"
            )

    # 5 — forbidden files
    forbidden_set = set(change_request.forbidden_files)
    for fpath in files:
        if fpath in forbidden_set:
            errors.append(
                f"File {fpath!r} is in forbidden_files"
            )

    # 6 — line budget
    added, removed = _count_lines(patch_content)
    total = added + removed
    if total > change_request.max_lines_changed:
        errors.append(
            f"Patch changes {total} lines, exceeding limit of "
            f"{change_request.max_lines_changed}"
        )

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        files_touched=files,
        lines_added=added,
        lines_removed=removed,
    )
