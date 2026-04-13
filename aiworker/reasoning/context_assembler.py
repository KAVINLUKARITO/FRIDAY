"""Context assembler for the reasoning pipeline.

Extracts relevant source code context from the repository to provide
to the LLM adapter.  Only reads files — never writes.

Deterministic: same inputs always produce same outputs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence

from aiworker.reasoning.module_mapper import ModuleNode


@dataclass(frozen=True)
class FileContext:
    """Source content of a single file for LLM context.

    Attributes:
        file_path: Relative path within the repository.
        module_path: Dotted module name.
        content: File contents (truncated if too large).
        line_count: Total lines in the original file.
        truncated: Whether the content was truncated.
    """

    file_path: str
    module_path: str
    content: str
    line_count: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "file_path": self.file_path,
            "module_path": self.module_path,
            "content": self.content,
            "line_count": self.line_count,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class AssembledContext:
    """Aggregated context ready for LLM consumption.

    Attributes:
        files: Relevant file contexts.
        total_tokens_estimate: Rough token count (chars / 4).
        summary: Human-readable summary of what was assembled.
    """

    files: tuple[FileContext, ...]
    total_tokens_estimate: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "files": [f.to_dict() for f in self.files],
            "total_tokens_estimate": self.total_tokens_estimate,
            "summary": self.summary,
        }


# Maximum lines per file before truncation.
_MAX_LINES_PER_FILE = 200

# Maximum total characters across all files.
_MAX_TOTAL_CHARS = 50_000


def _read_file_context(
    node: ModuleNode,
    repo_root: str,
    max_lines: int = _MAX_LINES_PER_FILE,
) -> FileContext | None:
    """Read a file and return its context, or None if unreadable."""
    if not node.file_path or not os.path.isfile(node.file_path):
        return None

    try:
        with open(node.file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return None

    line_count = len(lines)
    truncated = line_count > max_lines
    content = "".join(lines[:max_lines])

    # Make path relative to repo_root
    try:
        rel_path = os.path.relpath(node.file_path, repo_root)
    except ValueError:
        rel_path = node.file_path

    return FileContext(
        file_path=rel_path,
        module_path=node.module_path,
        content=content,
        line_count=line_count,
        truncated=truncated,
    )


def assemble_context(
    nodes: Sequence[ModuleNode],
    repo_root: str,
    max_lines_per_file: int = _MAX_LINES_PER_FILE,
    max_total_chars: int = _MAX_TOTAL_CHARS,
) -> AssembledContext:
    """Assemble source context from dependency graph nodes.

    Reads files referenced by the nodes, respecting per-file and total
    size limits.  Files are included in BFS order (depth-first nodes
    have priority).

    Args:
        nodes: Module graph nodes from ``module_mapper.map_dependencies``.
        repo_root: Repository root for relative path computation.
        max_lines_per_file: Maximum lines to include per file.
        max_total_chars: Maximum total characters across all files.

    Returns:
        An :class:`AssembledContext` with file contents and metadata.
    """
    # Sort by depth (closest first), then by path for determinism.
    sorted_nodes = sorted(nodes, key=lambda n: (n.depth, n.module_path))

    files: list[FileContext] = []
    total_chars = 0

    for node in sorted_nodes:
        if total_chars >= max_total_chars:
            break
        ctx = _read_file_context(node, repo_root, max_lines_per_file)
        if ctx is None:
            continue
        remaining = max_total_chars - total_chars
        if len(ctx.content) > remaining:
            # Truncate to fit
            ctx = FileContext(
                file_path=ctx.file_path,
                module_path=ctx.module_path,
                content=ctx.content[:remaining],
                line_count=ctx.line_count,
                truncated=True,
            )
        files.append(ctx)
        total_chars += len(ctx.content)

    token_estimate = total_chars // 4

    summary = (
        f"Assembled {len(files)} files, "
        f"~{token_estimate} tokens, "
        f"from {len(sorted_nodes)} modules."
    )

    return AssembledContext(
        files=tuple(files),
        total_tokens_estimate=token_estimate,
        summary=summary,
    )
