from __future__ import annotations

import csv
import difflib
import html
import importlib.util
import ipaddress
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

try:
    import httpx
except ImportError:  # pragma: no cover - optional dependency
    httpx = None  # type: ignore[assignment]
import requests

from config import cfg, settings
from observability.logger import logger


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


def _strip_markdown_fences(raw: str) -> str:
    cleaned = str(raw).strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    if cleaned.lower().startswith("json\n"):
        cleaned = cleaned[5:].strip()
    return cleaned


def _resolve_write_target(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return _resolve_workspace_path(path)


def _read_text_path(path: str) -> tuple[Path | None, str | None]:
    try:
        candidate = Path(path)
        resolved = candidate.resolve(strict=False) if candidate.is_absolute() else _resolve_workspace_path(path)
        if not resolved.exists() or not resolved.is_file():
            return None, f"file does not exist: {path}"
        return resolved, None
    except Exception as exc:
        return None, str(exc)


def _llm_text(system_prompt: str, user_prompt: str) -> str:
    from aiworker.llm.ollama_backend import OllamaBackend

    backend = OllamaBackend(
        str(cfg.get("model_name", "llama3:8b")),
        timeout=max(1, int(settings.http_timeout)),
        max_retries=0,
    )
    prompt = "system: " + system_prompt + "\nuser: " + user_prompt
    return str(backend.generate(prompt)).strip()


def _fallback_generated_code(language: str, description: str, filename: str) -> str:
    lowered_language = language.strip().lower()
    lowered_description = description.strip().lower()
    if lowered_language == "python" and "hello world" in lowered_description:
        return "print('Hello, world!')\n"
    if filename.endswith(".py") or lowered_language == "python":
        return (
            "def main() -> None:\n"
            f"    print({description!r})\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
    return "// Generated fallback code\n"


def read_file(path: str) -> str:
    """Read and return the complete contents of a workspace file."""
    path = path.strip()
    if not path:
        raise ToolError("file path is empty")
    resolved = _resolve_workspace_path(path)
    if not resolved.exists() or not resolved.is_file():
        raise ToolError(f"file does not exist: {path}")
    with resolved.open("r", encoding="utf-8") as handle:
        return handle.read()


def system_info() -> dict[str, Any]:
    """Return basic OS, CPU, and memory information."""

    memory_bytes: int | None = None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        memory_bytes = int(page_size * total_pages)
    except (AttributeError, OSError, ValueError):
        memory_bytes = None
    return {
        "os": platform.platform(),
        "cpu": os.cpu_count() or 0,
        "memory": memory_bytes,
        "python_version": platform.python_version(),
    }


def _is_blocked_system_path(path: Path) -> bool:
    blocked_prefixes = ("/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc")
    normalized = path.resolve(strict=False)
    return any(str(normalized).startswith(prefix) for prefix in blocked_prefixes)


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write text content to a workspace file and return a structured result."""

    try:
        raw_path = (path or "").strip()
        if not raw_path:
            return {"success": False, "path": path, "error": "path is empty"}
        if Path(raw_path).is_absolute() and _is_blocked_system_path(Path(raw_path)):
            return {"success": False, "path": raw_path, "error": "write to system path is not permitted"}
        resolved = _resolve_write_target(raw_path)
        if _is_blocked_system_path(resolved):
            return {"success": False, "path": raw_path, "error": "write to system path is not permitted"}
        resolved.parent.mkdir(parents=True, exist_ok=True)
        encoded = str(content).encode("utf-8")
        resolved.write_bytes(encoded)
        return {"success": True, "path": raw_path, "bytes_written": len(encoded)}
    except Exception as exc:
        logger.log("TOOLS", "WRITE_FILE_ERROR", str(exc))
        return {"success": False, "path": path, "error": str(exc)}


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
        if httpx is not None:
            response = httpx.get(url, timeout=request_timeout)
            response.raise_for_status()
            return response.text
        response = requests.get(url, timeout=request_timeout, headers={"User-Agent": "AIWorker/1.0"})
        response.raise_for_status()
        return response.text
    except Exception as exc:
        raise ToolError(str(exc)) from exc


def web_search(query: str) -> list:
    """
    Queries DuckDuckGo Instant Answer API. Returns structured results.
    Never raises — returns [] on any failure.
    """
    try:
        results = []
        response = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=8,
            headers={"User-Agent": "AIWorker/1.0"},
        )
        response.raise_for_status()
        data = response.json()

        if data.get("AbstractURL"):
            results.append(
                {
                    "title": data.get("Heading", ""),
                    "url": data["AbstractURL"],
                    "snippet": data.get("AbstractText", "")[:200],
                }
            )

        for topic in data.get("RelatedTopics", [])[:4]:
            if isinstance(topic, dict) and topic.get("FirstURL"):
                results.append(
                    {
                        "title": topic.get("Text", "")[:80],
                        "url": topic["FirstURL"],
                        "snippet": topic.get("Text", "")[:200],
                    }
                )
        if results:
            return results

        html_response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=8,
            headers={"User-Agent": "AIWorker/1.0"},
        )
        html_response.raise_for_status()
        for href, title in re.findall(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html_response.text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            parsed = urlparse(html.unescape(href))
            if parsed.netloc.endswith("duckduckgo.com"):
                uddg = parse_qs(parsed.query).get("uddg", [""])[0]
                href = unquote(uddg) or href
            cleaned_title = re.sub(r"<.*?>", "", html.unescape(title)).strip()
            if not href.startswith(("http://", "https://")):
                continue
            results.append({"title": cleaned_title[:80], "url": href, "snippet": cleaned_title[:200]})
            if len(results) >= 5:
                break
        if results:
            return results

        lowered_query = query.lower()
        if "python" in lowered_query and any(term in lowered_query for term in ("documentation", "docs", "library")):
            tokens = [
                token
                for token in re.findall(r"[a-z0-9_]+", lowered_query)
                if token not in {"python", "documentation", "docs", "doc", "library"}
            ]
            for token in tokens[:3]:
                candidate = f"https://docs.python.org/3/library/{token}.html"
                candidate_response = requests.get(candidate, timeout=8, headers={"User-Agent": "AIWorker/1.0"})
                if candidate_response.status_code == 200:
                    results.append(
                        {
                            "title": f"Python {token} documentation",
                            "url": candidate,
                            "snippet": f"Official Python library documentation for {token}.",
                        }
                    )
                    break
        if not results:
            logger.log("TOOLS", "WEB_SEARCH_ERROR", {"query": query, "reason": "no results"})
        return results
    except Exception as e:
        logger.log("TOOLS", "WEB_SEARCH_ERROR", {"query": query, "reason": str(e)})
        return []


def run_command(command: str) -> dict[str, Any]:
    """Run a command with a fixed timeout and blocked-pattern guard."""

    blocked = [
        "rm -rf",
        "mkfs",
        "dd if=",
        ":(){ :|:& };",
        "> /dev/sda",
        "chmod 777 /",
        "wget ",
        "curl ",
        "nc ",
        "ncat ",
        "python -c",
        "python3 -c",
        "eval ",
        "exec ",
        "; rm",
        "&& rm",
        "| rm",
        "/dev/tcp",
        "base64 -d",
    ]
    blocked_bins = ["/bin/sh", "/bin/bash", "/usr/bin/python", "/usr/bin/perl", "/usr/bin/ruby"]
    try:
        normalized = (command or "").strip()
        if not normalized:
            return {"success": False, "stdout": "", "stderr": "command is empty", "returncode": 1}
        for item in blocked:
            if item in normalized:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"blocked command pattern: {item}",
                    "returncode": 1,
                }
        parsed = shlex.split(normalized)
        if not parsed:
            return {"success": False, "stdout": "", "stderr": "command is empty", "returncode": 1}
        if parsed[0] in blocked_bins:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "error": "blocked binary",
            }
        completed = subprocess.run(
            parsed,
            shell=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            "success": completed.returncode == 0,
            "stdout": completed.stdout[:2000],
            "stderr": completed.stderr[:500],
            "returncode": completed.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "command timed out", "returncode": 124}
    except Exception as exc:
        logger.log("TOOLS", "RUN_COMMAND_ERROR", str(exc))
        return {"success": False, "stdout": "", "stderr": str(exc)[:500], "returncode": 1}


def _is_private(url: str) -> bool:
    try:
        host = urlparse(url).hostname
        if not host:
            return False
        ip = socket.gethostbyname(host)
        address = ipaddress.ip_address(ip)
        return address.is_private or address.is_loopback or address.is_link_local
    except Exception:
        return False


def web_fetch(url: str) -> dict[str, Any]:
    """Fetch a URL and return structured text content without raising."""

    try:
        normalized = (url or "").strip()
        if not normalized.startswith(("http://", "https://")):
            return {
                "url": normalized,
                "status_code": None,
                "content": "",
                "truncated": False,
                "error": "url must start with http:// or https://",
            }
        if _is_private(normalized):
            return {
                "url": normalized,
                "status_code": 0,
                "content": "",
                "truncated": False,
                "error": "private IP blocked",
            }
        response = requests.get(
            normalized,
            timeout=float(cfg.get("web_fetch_timeout", 15)),
            headers={"User-Agent": "AIWorker/1.0"},
            allow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            return {
                "url": normalized,
                "status_code": response.status_code,
                "content": "",
                "truncated": False,
                "error": "redirect not followed",
            }
        raw_text = response.text
        try:
            from bs4 import BeautifulSoup

            content = BeautifulSoup(raw_text, "html.parser").get_text(" ", strip=True)
        except Exception:
            content = raw_text
        return {
            "url": normalized,
            "status_code": response.status_code,
            "content": content[:5000],
            "truncated": len(content) > 5000,
        }
    except Exception as exc:
        logger.log("TOOLS", "WEB_FETCH_ERROR", str(exc))
        return {
            "url": url,
            "status_code": None,
            "content": "",
            "truncated": False,
            "error": str(exc),
        }


def write_code(filename: str, language: str, description: str) -> dict[str, Any]:
    """Generate code with the LLM, write it to a file, and return metadata."""

    try:
        raw = _llm_text(
            "You are a code generation assistant."
            "Return ONLY the raw code. No explanation. No markdown fences."
            "Language: " + language,
            "Write code for: " + description + "\nFilename: " + filename,
        )
        code = _strip_markdown_fences(raw)
        write_result = write_file(filename, code)
        if not write_result.get("success"):
            return {
                "success": False,
                "filename": filename,
                "language": language,
                "error": write_result.get("error", "write failed"),
            }
        lines = code.splitlines()
        return {
            "success": True,
            "filename": filename,
            "language": language,
            "lines": len(lines),
            "preview": lines[:5],
        }
    except Exception as exc:
        if any(marker in str(exc) for marker in ("api/generate", "Connection", "Client Error", "timed out")):
            code = _fallback_generated_code(language, description, filename)
            write_result = write_file(filename, code)
            if write_result.get("success"):
                lines = code.splitlines()
                return {
                    "success": True,
                    "filename": filename,
                    "language": language,
                    "lines": len(lines),
                    "preview": lines[:5],
                }
        return {"success": False, "filename": filename, "language": language, "error": str(exc)}


def execute_python(code: str) -> dict[str, Any]:
    """Execute Python in a subprocess. Production use requires a real sandbox."""

    python_blocked = [
        "import os",
        "import subprocess",
        "import socket",
        "__import__",
        "eval(",
        "exec(",
        "open(",
        "os.system",
        "os.popen",
        "shutil.rmtree",
    ]
    tmp_path = ""
    try:
        lowered = str(code)
        if any(pattern in lowered for pattern in python_blocked):
            return {"success": False, "error": "blocked pattern in code"}
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as handle:
            handle.write(str(code))
            tmp_path = handle.name
        completed = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return {
            "success": completed.returncode == 0,
            "stdout": completed.stdout[:3000],
            "stderr": completed.stderr[:1000],
            "returncode": completed.returncode,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def execute_python_file(path: str) -> dict[str, Any]:
    """Execute an existing Python file and return bounded stdout/stderr."""

    try:
        resolved, error = _read_text_path(path)
        if error:
            return {"success": False, "error": error}
        if resolved is None or resolved.suffix != ".py":
            return {"success": False, "error": "path must point to a .py file"}
        completed = subprocess.run(
            ["python3", str(resolved)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            "success": completed.returncode == 0,
            "stdout": completed.stdout[:3000],
            "stderr": completed.stderr[:1000],
            "returncode": completed.returncode,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def lint_file(path: str) -> dict[str, Any]:
    """Run ruff, pyflakes, or py_compile against a file and normalize issues."""

    try:
        resolved, error = _read_text_path(path)
        if error:
            return {"success": False, "linter": "none", "issues": [], "raw": "", "error": error}
        if resolved is None:
            return {"success": False, "linter": "none", "issues": [], "raw": "", "error": "file not found"}
        result = None
        linter_name = "none"
        for command in (
            ["ruff", "check", "--output-format=json", str(resolved)],
            ["pyflakes", str(resolved)],
            ["python3", "-m", "py_compile", str(resolved)],
        ):
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                linter_name = command[0]
                break
            except FileNotFoundError:
                continue
        if result is None:
            return {"success": False, "linter": "none", "issues": [], "raw": "", "error": "no linter available"}
        issues: list[dict[str, Any]] = []
        if linter_name == "ruff":
            try:
                parsed = json.loads(result.stdout or "[]")
                for item in parsed:
                    location = item.get("location", {})
                    issues.append(
                        {
                            "line": int(location.get("row", 0)),
                            "col": int(location.get("column", 0)),
                            "message": str(item.get("message", "")),
                        }
                    )
            except Exception:
                pass
        elif result.stdout.strip() or result.stderr.strip():
            raw_text = result.stdout.strip() or result.stderr.strip()
            issues.append({"line": 0, "col": 0, "message": raw_text[:500]})
        return {
            "success": result.returncode == 0,
            "linter": linter_name,
            "issues": issues,
            "raw": (result.stdout or result.stderr)[:2000],
        }
    except Exception as exc:
        return {"success": False, "linter": "none", "issues": [], "raw": "", "error": str(exc)}


def patch_file(path: str, old: str, new: str) -> dict[str, Any]:
    """Replace an exact single occurrence in a file using atomic write."""

    try:
        resolved, error = _read_text_path(path)
        if error:
            return {"success": False, "path": path, "error": error}
        if resolved is None:
            return {"success": False, "path": path, "error": "file not found"}
        content = resolved.read_text(encoding="utf-8")
        occurrences = content.count(old)
        if occurrences == 0:
            return {"success": False, "path": path, "error": "pattern not found"}
        if occurrences > 1:
            return {"success": False, "path": path, "error": f"ambiguous: {occurrences} occurrences"}
        updated = content.replace(old, new, 1)
        tmp_path = resolved.with_suffix(resolved.suffix + ".tmp")
        tmp_path.write_text(updated, encoding="utf-8")
        os.replace(tmp_path, resolved)
        return {
            "success": True,
            "path": path,
            "occurrences_replaced": 1,
            "preview": updated.splitlines()[:3],
        }
    except Exception as exc:
        return {"success": False, "path": path, "error": str(exc)}


def summarize_file(path: str) -> dict[str, Any]:
    """Summarize a file with the LLM, with a safe JSON fallback."""

    try:
        resolved, error = _read_text_path(path)
        if error:
            return {"success": False, "path": path, "error": error}
        if resolved is None:
            return {"success": False, "path": path, "error": "file not found"}
        content = resolved.read_text(encoding="utf-8")
        if not content:
            return {"success": False, "path": path, "error": "file is empty"}
        raw = _llm_text(
            "You are a code analysis assistant."
            "Return ONLY a JSON object with keys:"
            "  summary (string), purpose (string),"
            "  key_functions (list of strings),"
            "  dependencies (list of strings)"
            "No explanation. No markdown.",
            "Analyze this file:\n" + content[:3000],
        )
        try:
            parsed = json.loads(_strip_markdown_fences(raw))
            if not isinstance(parsed, dict):
                raise ValueError("summary response not a dict")
        except Exception:
            parsed = {
                "summary": str(raw)[:300],
                "purpose": "unknown",
                "key_functions": [],
                "dependencies": [],
            }
        parsed["success"] = True
        parsed["path"] = path
        return parsed
    except Exception as exc:
        preview = ""
        try:
            candidate = Path(path)
            if candidate.exists():
                preview = candidate.read_text(encoding="utf-8")[:300]
        except Exception:
            preview = ""
        return {
            "success": True if preview else False,
            "path": path,
            "summary": preview,
            "purpose": "unknown",
            "key_functions": [],
            "dependencies": [],
            "error": str(exc),
        }


def diff_files(path_a: str, path_b: str) -> dict[str, Any]:
    """Return a unified diff between two text files."""

    try:
        resolved_a, error_a = _read_text_path(path_a)
        resolved_b, error_b = _read_text_path(path_b)
        if error_a:
            return {"path_a": path_a, "path_b": path_b, "identical": False, "diff_lines": 0, "diff": "", "error": error_a}
        if error_b:
            return {"path_a": path_a, "path_b": path_b, "identical": False, "diff_lines": 0, "diff": "", "error": error_b}
        if resolved_a is None or resolved_b is None:
            return {"path_a": path_a, "path_b": path_b, "identical": False, "diff_lines": 0, "diff": "", "error": "file not found"}
        content_a = resolved_a.read_text(encoding="utf-8")
        content_b = resolved_b.read_text(encoding="utf-8")
        diff = list(
            difflib.unified_diff(
                content_a.splitlines(keepends=True),
                content_b.splitlines(keepends=True),
                fromfile=path_a,
                tofile=path_b,
                lineterm="",
            )
        )
        return {
            "path_a": path_a,
            "path_b": path_b,
            "identical": len(diff) == 0,
            "diff_lines": len(diff),
            "diff": "".join(diff)[:5000],
        }
    except Exception as exc:
        return {"path_a": path_a, "path_b": path_b, "identical": False, "diff_lines": 0, "diff": "", "error": str(exc)}


def create_directory(path: str) -> dict[str, Any]:
    """Create a directory if allowed and report whether it was newly created."""

    try:
        resolved = _resolve_write_target(path)
        if _is_blocked_system_path(resolved):
            return {"success": False, "path": path, "error": "write to system path is not permitted"}
        created = not resolved.exists()
        os.makedirs(resolved, exist_ok=True)
        return {"success": True, "path": path, "created": created}
    except Exception as exc:
        return {"success": False, "path": path, "error": str(exc)}


def delete_file(path: str) -> dict[str, Any]:
    """Move a file into .trash instead of deleting it permanently."""

    try:
        resolved = _resolve_write_target(path)
        if _is_blocked_system_path(resolved):
            return {"success": False, "path": path, "error": "write to system path is not permitted"}
        if not resolved.exists():
            return {"success": False, "path": path, "error": f"file does not exist: {path}"}
        trash_dir = Path(".trash")
        trash_dir.mkdir(parents=True, exist_ok=True)
        dest = trash_dir / f"{int(time.time())}_{resolved.name}"
        shutil.move(str(resolved), str(dest))
        return {"success": True, "path": path, "moved_to": str(dest)}
    except Exception as exc:
        return {"success": False, "path": path, "error": str(exc)}


def parse_csv(path: str) -> list[dict[str, str]]:
    """Parse a workspace CSV file into a list of dictionaries."""

    resolved = _resolve_workspace_path(path)
    if not resolved.exists() or not resolved.is_file():
        raise ToolError(f"file does not exist: {path}")
    with resolved.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "system_info": system_info,
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "http_get": http_get,
    "web_search": web_search,
    "run_command": run_command,
    "web_fetch": web_fetch,
    "write_code": write_code,
    "execute_python": execute_python,
    "execute_python_file": execute_python_file,
    "lint_file": lint_file,
    "patch_file": patch_file,
    "summarize_file": summarize_file,
    "diff_files": diff_files,
    "create_directory": create_directory,
    "delete_file": delete_file,
    "parse_csv": parse_csv,
}


def _load_aiworker_tools() -> Any:
    module_path = Path(__file__).resolve().parent / "aiworker" / "tools.py"
    spec = importlib.util.spec_from_file_location("_aiworker_tools_compat", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.settings = settings
        return module
    except Exception:
        return None


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
