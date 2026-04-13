"""Deterministic module dependency mapper.

Traverses Python import relationships to depth=2 to identify
modules that may be affected by or relevant to a failure.

Uses AST-based import extraction — no execution, no network,
no side effects.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class ModuleNode:
    """A node in the dependency graph.

    Attributes:
        module_path: Dotted module path (e.g. ``aiworker.governance.policy``).
        file_path: Filesystem path to the module file, or empty string.
        imports: Direct imports from this module.
        depth: How many hops from the root module.
    """

    module_path: str
    file_path: str
    imports: tuple[str, ...]
    depth: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "module_path": self.module_path,
            "file_path": self.file_path,
            "imports": list(self.imports),
            "depth": self.depth,
        }


def _extract_imports_from_source(source: str) -> list[str]:
    """Extract import targets from Python source using AST.

    Returns dotted module names from ``import X`` and ``from X import Y``
    statements.  Only includes ``aiworker.*`` imports.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("aiworker"):
                    imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("aiworker"):
                imports.append(node.module)
    return sorted(set(imports))


def _module_to_filepath(module_path: str, repo_root: str) -> str:
    """Convert a dotted module path to a filesystem path.

    Returns the path if it exists, else empty string.
    """
    parts = module_path.split(".")
    # Try as a file: aiworker/foo/bar.py
    file_path = os.path.join(repo_root, *parts) + ".py"
    if os.path.isfile(file_path):
        return file_path
    # Try as a package: aiworker/foo/bar/__init__.py
    pkg_init = os.path.join(repo_root, *parts, "__init__.py")
    if os.path.isfile(pkg_init):
        return pkg_init
    return ""


def map_dependencies(
    root_modules: Sequence[str],
    repo_root: str,
    max_depth: int = 2,
) -> tuple[ModuleNode, ...]:
    """Build a dependency graph starting from root modules.

    Traverses imports up to ``max_depth`` hops.  Only follows
    ``aiworker.*`` imports.  Deterministic for identical inputs.

    Args:
        root_modules: Starting module paths to trace from.
        repo_root: Absolute path to the repository root.
        max_depth: Maximum traversal depth (default 2).

    Returns:
        A tuple of :class:`ModuleNode` instances in BFS order.
    """
    visited: dict[str, ModuleNode] = {}
    queue: list[tuple[str, int]] = [(m, 0) for m in root_modules]

    while queue:
        mod_path, depth = queue.pop(0)
        if mod_path in visited or depth > max_depth:
            continue

        file_path = _module_to_filepath(mod_path, repo_root)
        if file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()
                imports = tuple(_extract_imports_from_source(source))
            except (OSError, UnicodeDecodeError):
                imports = ()
        else:
            imports = ()

        node = ModuleNode(
            module_path=mod_path,
            file_path=file_path,
            imports=imports,
            depth=depth,
        )
        visited[mod_path] = node

        if depth < max_depth:
            for imp in imports:
                if imp not in visited:
                    queue.append((imp, depth + 1))

    return tuple(visited.values())


def affected_module_paths(
    file_paths: Sequence[str],
    repo_root: str,
) -> tuple[str, ...]:
    """Convert filesystem paths to dotted module paths.

    Args:
        file_paths: Absolute or relative .py file paths.
        repo_root: Repository root directory.

    Returns:
        Sorted tuple of dotted module paths.
    """
    modules: list[str] = []
    for fp in file_paths:
        # Make relative to repo root
        if os.path.isabs(fp):
            try:
                rel = os.path.relpath(fp, repo_root)
            except ValueError:
                continue
        else:
            rel = fp
        # Strip .py and __init__
        if rel.endswith("__init__.py"):
            rel = os.path.dirname(rel)
        elif rel.endswith(".py"):
            rel = rel[:-3]
        else:
            continue
        # Convert path separators to dots
        mod = rel.replace(os.sep, ".").replace("/", ".")
        if mod.startswith("aiworker"):
            modules.append(mod)
    return tuple(sorted(set(modules)))
