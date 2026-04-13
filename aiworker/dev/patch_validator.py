"""Deterministic unified-diff patch validation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Sequence

_HEADER_RE = re.compile(r"^(?:---|\+\+\+)\s+(.+?)(?:\t.*)?$", re.MULTILINE)
_HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@", re.MULTILINE)
_BINARY_RE = re.compile(r"(?:^GIT binary patch$|^Binary files .* differ$)", re.MULTILINE)


@dataclass(frozen=True)
class PatchValidationResult:
    valid: bool
    errors: tuple[str, ...]
    risk_score: float


def _normalize_diff_path(path: str) -> str:
    normalized = path.strip()
    if normalized.startswith(("a/", "b/")):
        normalized = normalized[2:]
    normalized = normalized.replace("\\", "/")
    return normalized


def extract_touched_files(diff_text: str) -> tuple[str, ...]:
    files: list[str] = []
    for match in _HEADER_RE.finditer(diff_text):
        raw = match.group(1).strip()
        if raw in ("/dev/null", "a/dev/null", "b/dev/null"):
            continue
        path = _normalize_diff_path(raw)
        if path and path not in files:
            files.append(path)
    return tuple(files)


def _count_changed_lines(diff_text: str) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _is_valid_unified_diff(diff_text: str) -> bool:
    if "--- " not in diff_text or "+++ " not in diff_text:
        return False
    if _HUNK_RE.search(diff_text) is None:
        return False
    return True


def _deletion_detected(diff_text: str) -> bool:
    for line in diff_text.splitlines():
        if line.startswith("+++ ") and line[4:].strip() in ("/dev/null", "b/dev/null"):
            return True
    _, removed = _count_changed_lines(diff_text)
    return removed > 0


def _risk_from_metrics(lines_changed: int, file_count: int, has_deletion: bool) -> float:
    line_ratio = min(1.0, lines_changed / 50.0)
    file_penalty = 0.25 if file_count > 1 else 0.0
    deletion_penalty = 0.2 if has_deletion else 0.0
    risk = (0.6 * line_ratio) + file_penalty + deletion_penalty
    return max(0.0, min(1.0, risk))


def validate_patch(
    diff_text: str,
    allowed_files: Sequence[str],
    *,
    allow_deletions: bool = False,
) -> PatchValidationResult:
    """Validate patch deterministically against strict atomic rules."""
    errors: list[str] = []
    trimmed = diff_text.strip()

    if not trimmed:
        errors.append("Patch is empty")
        return PatchValidationResult(valid=False, errors=tuple(errors), risk_score=1.0)

    if not _is_valid_unified_diff(diff_text):
        errors.append("Patch must be valid unified diff format")

    if _BINARY_RE.search(diff_text) is not None:
        errors.append("Binary patch content is not allowed")

    touched_files = extract_touched_files(diff_text)
    if len(touched_files) == 0:
        errors.append("Patch does not touch a file")
    if len(touched_files) > 1:
        errors.append("Patch must modify exactly one file")

    allowed_set = {_normalize_diff_path(path) for path in allowed_files}
    for file_path in touched_files:
        if os.path.isabs(file_path):
            errors.append(f"Absolute file path is not allowed: {file_path}")
        normalized = os.path.normpath(file_path)
        if normalized.startswith(".."):
            errors.append(f"Path traversal is not allowed: {file_path}")
        if file_path not in allowed_set:
            errors.append(f"File outside allowed scope: {file_path}")

    added, removed = _count_changed_lines(diff_text)
    changed_total = added + removed
    if changed_total > 50:
        errors.append("Patch exceeds 50 changed lines")

    deletion_present = _deletion_detected(diff_text)
    if deletion_present and not allow_deletions:
        errors.append("Deletions are not allowed for this patch")

    risk_score = _risk_from_metrics(changed_total, len(touched_files), deletion_present)
    return PatchValidationResult(
        valid=len(errors) == 0,
        errors=tuple(errors),
        risk_score=risk_score,
    )


__all__ = [
    "PatchValidationResult",
    "extract_touched_files",
    "validate_patch",
]
