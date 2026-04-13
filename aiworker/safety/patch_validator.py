"""Deterministic patch validator for orchestrated autonomous loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from aiworker.dev.patch_validator import extract_touched_files, validate_patch as _validate_patch


@dataclass(frozen=True)
class PatchValidationResult:
    valid: bool
    errors: Tuple[str, ...]
    touched_files: Tuple[str, ...]
    risk_score: float


def validate_patch(
    diff_text: str,
    *,
    allowed_file: str,
    max_lines: int,
) -> PatchValidationResult:
    """Validate one-file diff against deterministic safety constraints."""
    touched = extract_touched_files(diff_text)
    errors: list[str] = []

    if len(touched) != 1:
        errors.append("Patch must modify exactly one file")
    elif touched[0] != allowed_file:
        errors.append(f"Patch must only modify allowed file: {allowed_file}")

    deterministic = _validate_patch(diff_text, allowed_files=(allowed_file,), allow_deletions=False)
    errors.extend(deterministic.errors)

    changed_lines = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            changed_lines += 1
    if changed_lines > max_lines:
        errors.append(f"Patch exceeds max_lines budget ({changed_lines} > {max_lines})")

    return PatchValidationResult(
        valid=len(errors) == 0,
        errors=tuple(errors),
        touched_files=touched,
        risk_score=deterministic.risk_score,
    )


__all__ = ["PatchValidationResult", "validate_patch"]
