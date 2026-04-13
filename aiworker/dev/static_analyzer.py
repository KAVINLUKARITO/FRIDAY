"""Deterministic static analysis for modified Python snippets."""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass

from aiworker.dev.patch_validator import extract_touched_files

_HUNK_START_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")


@dataclass(frozen=True)
class StaticAnalysisIssue:
    file_path: str
    line: int
    column: int
    message: str


@dataclass(frozen=True)
class StaticAnalysisResult:
    safe: bool
    issues: tuple[StaticAnalysisIssue, ...]
    files_analyzed: tuple[str, ...]
    dangerous_call_count: int
    score: float


def _added_lines_by_file(diff_text: str) -> dict[str, list[tuple[int, str]]]:
    results: dict[str, list[tuple[int, str]]] = {}
    current_file: str | None = None
    current_line = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path in ("/dev/null", "b/dev/null"):
                current_file = None
                current_line = 0
            else:
                current_file = path[2:] if path.startswith("b/") else path
                current_file = current_file.replace("\\", "/")
                results.setdefault(current_file, [])
                current_line = 0
            continue

        hunk = _HUNK_START_RE.match(line)
        if hunk is not None:
            current_line = int(hunk.group(1))
            continue

        if current_file is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            results[current_file].append((current_line, line[1:]))
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            current_line += 1

    return results


def _is_subprocess_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "subprocess"


def _is_os_system(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "system"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _collect_issues(file_path: str, tree: ast.AST) -> list[StaticAnalysisIssue]:
    issues: list[StaticAnalysisIssue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    issues.append(
                        StaticAnalysisIssue(
                            file_path=file_path,
                            line=getattr(node, "lineno", 1),
                            column=getattr(node, "col_offset", 0),
                            message="Import of subprocess is not allowed",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                issues.append(
                    StaticAnalysisIssue(
                        file_path=file_path,
                        line=getattr(node, "lineno", 1),
                        column=getattr(node, "col_offset", 0),
                        message="Import from subprocess is not allowed",
                    )
                )
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in {"eval", "exec", "__import__"}:
                issues.append(
                    StaticAnalysisIssue(
                        file_path=file_path,
                        line=getattr(node, "lineno", 1),
                        column=getattr(node, "col_offset", 0),
                        message=f"Call to {fn.id} is not allowed",
                    )
                )
            elif _is_subprocess_attribute(fn):
                issues.append(
                    StaticAnalysisIssue(
                        file_path=file_path,
                        line=getattr(node, "lineno", 1),
                        column=getattr(node, "col_offset", 0),
                        message="subprocess call is not allowed",
                    )
                )
            elif _is_os_system(fn):
                issues.append(
                    StaticAnalysisIssue(
                        file_path=file_path,
                        line=getattr(node, "lineno", 1),
                        column=getattr(node, "col_offset", 0),
                        message="os.system call is not allowed",
                    )
                )
            elif (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "importlib"
                and fn.attr == "import_module"
            ):
                issues.append(
                    StaticAnalysisIssue(
                        file_path=file_path,
                        line=getattr(node, "lineno", 1),
                        column=getattr(node, "col_offset", 0),
                        message="Dynamic import is not allowed",
                    )
                )
    return issues


def analyze_patch_python(diff_text: str) -> StaticAnalysisResult:
    """Analyze modified Python snippets in patch using AST without execution."""
    touched = extract_touched_files(diff_text)
    added_by_file = _added_lines_by_file(diff_text)

    issues: list[StaticAnalysisIssue] = []
    files_analyzed: list[str] = []

    for file_path in touched:
        if not file_path.endswith(".py"):
            continue
        files_analyzed.append(file_path)

        added_lines = [line for _, line in added_by_file.get(file_path, [])]
        if not added_lines:
            continue

        code = textwrap.dedent("\n".join(added_lines)).strip()
        if not code:
            continue

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            issues.append(
                StaticAnalysisIssue(
                    file_path=file_path,
                    line=exc.lineno or 1,
                    column=exc.offset or 0,
                    message=f"Syntax error in added Python snippet: {exc.msg}",
                )
            )
            continue

        issues.extend(_collect_issues(file_path, tree))

    dangerous_count = len(issues)
    score = max(0.0, 1.0 - min(1.0, dangerous_count / 5.0))
    return StaticAnalysisResult(
        safe=dangerous_count == 0,
        issues=tuple(issues),
        files_analyzed=tuple(files_analyzed),
        dangerous_call_count=dangerous_count,
        score=score,
    )


__all__ = [
    "StaticAnalysisIssue",
    "StaticAnalysisResult",
    "analyze_patch_python",
]
