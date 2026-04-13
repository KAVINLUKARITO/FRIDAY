"""Diff safety checks for package boundaries and protected modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from aiworker.dev.patch_validator import extract_touched_files

_PROTECTED_PREFIXES: tuple[str, ...] = (
    "aiworker/safety/",
    "aiworker/governance/",
)


@dataclass(frozen=True)
class DiffSafetyResult:
    safe: bool
    errors: tuple[str, ...]
    touched_files: tuple[str, ...]
    package_roots: tuple[str, ...]
    directories: tuple[str, ...]


def _package_root(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _directory(path: str) -> str:
    parts = path.split("/")
    if len(parts) <= 1:
        return ""
    return "/".join(parts[:-1])


def validate_diff_safety(diff_text: str, allowed_files: Sequence[str]) -> DiffSafetyResult:
    """Validate diff structural safety constraints deterministically."""
    errors: list[str] = []
    touched = extract_touched_files(diff_text)

    if len(touched) != 1:
        errors.append("Atomic patch rule violated: exactly one file must be modified")

    for file_path in touched:
        if file_path.startswith(_PROTECTED_PREFIXES):
            errors.append(f"Protected module cannot be modified: {file_path}")

    package_roots = tuple(sorted({_package_root(path) for path in touched}))
    if len(package_roots) > 1:
        errors.append("Cross-package modifications are not allowed")

    directories = tuple(sorted({_directory(path) for path in touched}))
    if len(directories) > 1:
        errors.append("Multi-directory modifications are not allowed")

    allowed = {path.replace('\\\\', '/').lstrip('./') for path in allowed_files}
    for file_path in touched:
        if file_path not in allowed:
            errors.append(f"File is outside allowed scope: {file_path}")

    return DiffSafetyResult(
        safe=len(errors) == 0,
        errors=tuple(errors),
        touched_files=touched,
        package_roots=package_roots,
        directories=directories,
    )


__all__ = ["DiffSafetyResult", "validate_diff_safety"]
