from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus
from urllib.parse import urlparse

import httpx

from config import settings


class SafetyError(Exception):
    """Raised when a path attempts to escape the configured workspace."""


class ToolError(Exception):
    """Raised when a tool cannot complete its operation safely."""


def _workspace_root() -> Path:
    return settings.workspace_dir.resolve()


def _resolve_workspace_path(path: str) -> Path:
    root = _workspace_root()
    candidate = (root / path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafetyError(f"path escapes workspace: {path}") from exc
    return candidate


def _relative_workspace_path(path: Path) -> str:
    return path.relative_to(_workspace_root()).as_posix()


def read_file(path: str) -> str:
    """Read and return the complete contents of a workspace file."""

    import os

    path = path.strip()
    if not path:
        raise ToolError("file path is empty")

    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = Path(os.getcwd()) / path_obj
    path_obj = path_obj.resolve()

    print(f"[TOOL] read_file -> resolved_path={path_obj}")

    if not path_obj.exists() or not path_obj.is_file():
        raise ToolError(f"file does not exist: {path_obj}")

    with open(path_obj, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str) -> str:
    """Write text content to a workspace file and return a status message."""

    resolved = _resolve_workspace_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"written: {path}"


def list_files(path: str = ".") -> list[str]:
    """List all files under a workspace directory as sorted relative paths."""

    resolved = _resolve_workspace_path(path)
    if not resolved.exists():
        raise ToolError(f"path does not exist: {path}")
    if resolved.is_file():
        return [_relative_workspace_path(resolved)]
    return sorted(
        _relative_workspace_path(file_path)
        for file_path in resolved.rglob("*")
        if file_path.is_file()
    )


def http_get(url: str, timeout: float | None = None) -> str:
    """Fetch a text response over HTTP(S) and return the body."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError(f"unsupported URL scheme: {parsed.scheme}")
    request_timeout = timeout if timeout is not None else settings.http_timeout
    try:
        response = httpx.get(url, timeout=request_timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(str(exc)) from exc
    return response.text


def web_search(query: str) -> str:
    """Return a stable DuckDuckGo search URL for the supplied query."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ToolError("search query is empty")
    url = "https://duckduckgo.com/?q=" + quote_plus(normalized_query)
    return f"Search results page: {url}"


def parse_csv(path: str) -> list[dict[str, str]]:
    """Parse a workspace CSV file into a list of dictionaries."""

    resolved = _resolve_workspace_path(path)
    if not resolved.exists() or not resolved.is_file():
        raise ToolError(f"file does not exist: {path}")
    with resolved.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "http_get": http_get,
    "web_search": web_search,
    "parse_csv": parse_csv,
}


def _load_aiworker_tools() -> Any:
    module_path = Path(__file__).resolve().parent / "aiworker" / "tools.py"
    spec = importlib.util.spec_from_file_location("_aiworker_tools_compat", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.settings = settings
    return module


_AIWORKER_TOOLS = _load_aiworker_tools()
if _AIWORKER_TOOLS is not None:
    SafetyError = getattr(_AIWORKER_TOOLS, "SafetyError")
    ToolError = getattr(_AIWORKER_TOOLS, "ToolError")
    _SECURITY_HEADERS = getattr(_AIWORKER_TOOLS, "_SECURITY_HEADERS")
    socket = getattr(_AIWORKER_TOOLS, "socket")
    for _name in (
        "safe_resolve",
        "parse_html",
        "http_request",
        "scan_headers",
        "check_sql_injection",
        "check_xss",
        "port_scan",
        "get_market_data",
        "calculate_indicators",
        "place_order",
        "get_portfolio",
    ):
        globals()[_name] = getattr(_AIWORKER_TOOLS, _name)
        TOOL_REGISTRY[_name] = globals()[_name]
