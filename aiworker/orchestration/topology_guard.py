"""Structural guardrails for patch topology and package boundaries."""

from __future__ import annotations

import os
from typing import Sequence

from aiworker.orchestration.architecture_models import GuardDecision


_BLOCKED_PREFIXES = (
    "aiworker/safety",
    "aiworker/governance",
    "aiworker/execution",
)


def parse_repo_tree(repo_root: str) -> tuple[str, ...]:
    """Return deterministic sorted file tree rooted at repo_root."""
    paths: list[str] = []
    for root, _, files in os.walk(repo_root):
        for name in files:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, repo_root).replace("\\", "/")
            paths.append(rel_path)
    paths.sort()
    return tuple(paths)


def _normalize_path(raw_path: str) -> str:
    path = raw_path.strip()
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    path = path.lstrip("./")
    return path.replace("\\", "/")


def extract_touched_files(diff: str) -> tuple[str, ...]:
    """Extract touched files from unified diff or apply_patch-style blocks."""
    touched: list[str] = []

    for line in diff.splitlines():
        if line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate != "/dev/null":
                touched.append(_normalize_path(candidate))
        elif line.startswith("*** Update File: "):
            touched.append(_normalize_path(line[len("*** Update File: ") :]))
        elif line.startswith("*** Add File: "):
            touched.append(_normalize_path(line[len("*** Add File: ") :]))
        elif line.startswith("*** Delete File: "):
            touched.append(_normalize_path(line[len("*** Delete File: ") :]))
        elif line.startswith("*** Move to: "):
            touched.append(_normalize_path(line[len("*** Move to: ") :]))

    unique_sorted = tuple(sorted({p for p in touched if p}))
    return unique_sorted


def _package_root(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "aiworker":
        return "/".join(parts[:2])
    return parts[0]


def evaluate_patch(diff: str, allowed_files: Sequence[str], repo_root: str) -> GuardDecision:
    """Validate patch topology constraints and file-level allow-list."""
    _ = parse_repo_tree(repo_root)
    touched = extract_touched_files(diff)

    if not touched:
        return GuardDecision(
            allowed=False,
            reason="No touched files detected",
            touched_files=(),
            package_roots=(),
        )

    for path in touched:
        if path.startswith("/") or ".." in path.split("/"):
            return GuardDecision(
                allowed=False,
                reason="Invalid path traversal detected",
                touched_files=touched,
                package_roots=tuple(sorted({_package_root(p) for p in touched})),
            )

    for path in touched:
        if path.startswith(_BLOCKED_PREFIXES):
            return GuardDecision(
                allowed=False,
                reason="Patch touches protected package",
                touched_files=touched,
                package_roots=tuple(sorted({_package_root(p) for p in touched})),
            )

    package_roots = tuple(sorted({_package_root(path) for path in touched}))
    if len(package_roots) > 1:
        return GuardDecision(
            allowed=False,
            reason="Patch touches multiple packages",
            touched_files=touched,
            package_roots=package_roots,
        )

    allowed_set = {_normalize_path(path) for path in allowed_files}
    for path in touched:
        if path not in allowed_set:
            return GuardDecision(
                allowed=False,
                reason="Patch includes file outside allowed task scope",
                touched_files=touched,
                package_roots=package_roots,
            )

    return GuardDecision(
        allowed=True,
        reason="Patch allowed",
        touched_files=touched,
        package_roots=package_roots,
    )
