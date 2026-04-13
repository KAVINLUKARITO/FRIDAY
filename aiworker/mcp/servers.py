"""
AIWorker MCP Servers - Phase 2 Integration

Three Model Context Protocol servers using FastMCP for stdio transport:
- filesystem: Safe file operations with path traversal protection
- code_executor: Sandboxed Python execution with resource limits
- git_ops: Git repository operations with safety constraints

Usage: python -m aiworker.mcp.servers <server_name>
"""

import asyncio
import os
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP

# Base path constraint for filesystem operations
BASE_PATH = Path("/opt/aiworker").resolve()

# Whitelisted imports for code executor
WHITELISTED_IMPORTS = {
    "os", "sys", "pathlib", "json", "re", "datetime", "collections",
    "itertools", "functools", "typing", "math", "random", "string",
    "hashlib", "base64", "urllib.parse", "textwrap", "inspect",
    "dataclasses", "enum", "abc", "copy", "pickle", "csv", "io"
}

# Size limits
MAX_READ_SIZE = 50 * 1024  # 50KB
MAX_WRITE_SIZE = 100 * 1024  # 100KB
MAX_EXECUTION_TIME = 120  # seconds
MAX_MEMORY_MB = 512


def _validate_path(path_str: str) -> Path:
    """Validate and resolve path within BASE_PATH."""
    try:
        # Resolve the path
        target = Path(path_str).expanduser().resolve()
        
        # Check for symlinks
        if target.is_symlink() or any(p.is_symlink() for p in target.parents if p.exists()):
            raise ValueError("Symlinks are not allowed")
        
        # Ensure path is within BASE_PATH
        try:
            target.relative_to(BASE_PATH)
        except ValueError:
            raise ValueError(f"Path must be within {BASE_PATH}")
        
        return target
    except Exception as e:
        raise ValueError(f"Invalid path: {e}")


def _check_imports(code: str) -> list[str]:
    """Check code for non-whitelisted imports."""
    violations = []
    
    # Pattern to match import statements
    import_patterns = [
        r'^\s*import\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        r'^\s*from\s+([a-zA-Z_][a-zA-Z0-9_]*).*import',
    ]
    
    for line in code.split('\n'):
        for pattern in import_patterns:
            match = re.match(pattern, line)
            if match:
                module = match.group(1)
                if module not in WHITELISTED_IMPORTS:
                    violations.append(module)
    
    return violations


def _is_git_repo() -> bool:
    """Check if current directory is a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_git_command(args: list[str], timeout: int = 30) -> dict[str, Any]:
    """Run a git command safely."""
    if not _is_git_repo():
        return {"success": False, "error": "Not a git repository", "stdout": "", "stderr": ""}
    
    try:
        # Block dangerous commands
        dangerous = ["push", "force", "--force", "-f", "clean", "reset", "checkout", "-"]
        if any(d in args for d in dangerous[:6]) and args != ["checkout"]:
            if "checkout" in args and len(args) == 2:
                pass  # Allow checkout with specific ref
            else:
                return {"success": False, "error": "Command not allowed", "stdout": "", "stderr": ""}
        
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(BASE_PATH)
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out", "stdout": "", "stderr": ""}
    except Exception as e:
        return {"success": False, "error": str(e), "stdout": "", "stderr": ""}


# =============================================================================
# Server 1: Filesystem MCP Server
# =============================================================================

filesystem_mcp = FastMCP("filesystem")


@filesystem_mcp.tool()
def read_file(
    path: Annotated[str, "File path to read"],
    offset: Annotated[int, "Line offset to start reading"] = 0,
    limit: Annotated[int, "Maximum lines to read"] = 1000
) -> dict[str, Any]:
    """Read file contents with offset and limit."""
    try:
        target = _validate_path(path)
        
        if not target.exists():
            return {"success": False, "error": f"File not found: {path}", "content": "", "lines_read": 0}
        
        if not target.is_file():
            return {"success": False, "error": "Path is not a file", "content": "", "lines_read": 0}
        
        # Check file size
        file_size = target.stat().st_size
        if file_size > MAX_READ_SIZE:
            return {
                "success": False, 
                "error": f"File too large ({file_size} bytes > {MAX_READ_SIZE} limit)",
                "content": "",
                "lines_read": 0
            }
        
        with open(target, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        # Apply offset and limit
        start = max(0, offset)
        end = min(len(lines), start + limit)
        selected_lines = lines[start:end]
        
        return {
            "success": True,
            "content": ''.join(selected_lines),
            "lines_read": len(selected_lines),
            "total_lines": len(lines),
            "offset": start
        }
    
    except Exception as e:
        return {"success": False, "error": str(e), "content": "", "lines_read": 0}


@filesystem_mcp.tool()
def write_file(
    path: Annotated[str, "File path to write"],
    content: Annotated[str, "Content to write"],
    append: Annotated[bool, "Append to existing file"] = False
) -> dict[str, Any]:
    """Write content to file with size limits."""
    try:
        target = _validate_path(path)
        
        # Check content size
        content_bytes = content.encode('utf-8')
        if len(content_bytes) > MAX_WRITE_SIZE:
            return {
                "success": False,
                "error": f"Content too large ({len(content_bytes)} bytes > {MAX_WRITE_SIZE} limit)",
                "bytes_written": 0
            }
        
        # Ensure parent directory exists
        target.parent.mkdir(parents=True, exist_ok=True)
        
        mode = 'a' if append else 'w'
        with open(target, mode, encoding='utf-8') as f:
            f.write(content)
        
        return {
            "success": True,
            "bytes_written": len(content_bytes),
            "path": str(target)
        }
    
    except Exception as e:
        return {"success": False, "error": str(e), "bytes_written": 0}


@filesystem_mcp.tool()
def list_dir(
    path: Annotated[str, "Directory path to list"] = "."
) -> dict[str, Any]:
    """List directory contents."""
    try:
        target = _validate_path(path)
        
        if not target.exists():
            return {"success": False, "error": f"Directory not found: {path}", "entries": []}
        
        if not target.is_dir():
            return {"success": False, "error": "Path is not a directory", "entries": []}
        
        entries = []
        for item in target.iterdir():
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "path": str(item.relative_to(BASE_PATH)),
                    "type": "directory" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else None,
                    "modified": stat.st_mtime
                })
            except (OSError, PermissionError):
                continue
        
        return {
            "success": True,
            "entries": sorted(entries, key=lambda x: (x["type"] != "directory", x["name"])),
            "count": len(entries)
        }
    
    except Exception as e:
        return {"success": False, "error": str(e), "entries": []}


@filesystem_mcp.tool()
def file_exists(
    path: Annotated[str, "File path to check"]
) -> dict[str, Any]:
    """Check if file or directory exists."""
    try:
        target = _validate_path(path)
        exists = target.exists()
        
        result = {
            "success": True,
            "exists": exists,
            "is_file": target.is_file() if exists else False,
            "is_directory": target.is_dir() if exists else False
        }
        
        if exists and target.is_file():
            stat = target.stat()
            result["size"] = stat.st_size
            result["modified"] = stat.st_mtime
        
        return result
    
    except Exception as e:
        return {"success": False, "error": str(e), "exists": False}


# =============================================================================
# Server 2: Code Executor MCP Server
# =============================================================================

code_executor_mcp = FastMCP("code_executor")


@code_executor_mcp.tool()
def execute_python(
    code: Annotated[str, "Python code to execute"],
    timeout: Annotated[int, "Execution timeout in seconds"] = MAX_EXECUTION_TIME
) -> dict[str, Any]:
    """Execute Python code in sandboxed subprocess with resource limits."""
    start_time = time.time()
    
    try:
        # Check imports
        violations = _check_imports(code)
        if violations:
            return {
                "success": False,
                "error": f"Non-whitelisted imports detected: {', '.join(violations)}",
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "execution_time_ms": 0
            }
        
        # Create temporary file for code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        try:
            # Build execution script with resource limits
            wrapper_code = f'''
import resource
import sys
import os
import runpy

# Set resource limits
resource.setrlimit(resource.RLIMIT_AS, ({MAX_MEMORY_MB * 1024 * 1024}, {MAX_MEMORY_MB * 1024 * 1024}))
resource.setrlimit(resource.RLIMIT_CPU, ({timeout}, {timeout + 5}))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

# Block network by setting dummy proxy
os.environ['http_proxy'] = 'http://localhost:0'
os.environ['https_proxy'] = 'http://localhost:0'
os.environ['HTTP_PROXY'] = 'http://localhost:0'
os.environ['HTTPS_PROXY'] = 'http://localhost:0'

runpy.run_path({repr(temp_path)}, run_name='__main__')
'''
            
            # Run in subprocess
            result = subprocess.run(
                [sys.executable, '-c', wrapper_code],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
            )
            
            execution_time = int((time.time() - start_time) * 1000)
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "execution_time_ms": execution_time
            }
        
        finally:
            # Cleanup temp file
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Execution timed out after {timeout} seconds",
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "execution_time_ms": int((time.time() - start_time) * 1000)
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "execution_time_ms": int((time.time() - start_time) * 1000)
        }


# =============================================================================
# Server 3: Git Operations MCP Server
# =============================================================================

git_ops_mcp = FastMCP("git_ops")


@git_ops_mcp.tool()
def git_status() -> dict[str, Any]:
    """Get git repository status."""
    result = _run_git_command(["status", "--porcelain", "-b"])
    
    if result["success"]:
        lines = result["stdout"].strip().split('\n') if result["stdout"].strip() else []
        branch_line = lines[0] if lines and lines[0].startswith('##') else ""
        
        # Parse branch info
        branch = "unknown"
        ahead_behind = {"ahead": 0, "behind": 0}
        
        if branch_line:
            branch_match = re.search(r'## (.+?)(?:\\.\\.\\.|$)', branch_line)
            if branch_match:
                branch = branch_match.group(1)
            
            ahead_match = re.search(r'ahead (\\d+)', branch_line)
            behind_match = re.search(r'behind (\\d+)', branch_line)
            
            if ahead_match:
                ahead_behind["ahead"] = int(ahead_match.group(1))
            if behind_match:
                ahead_behind["behind"] = int(behind_match.group(1))
        
        # Parse file changes
        staged = []
        unstaged = []
        untracked = []
        
        for line in lines[1:]:
            if not line:
                continue
            status = line[:2]
            filename = line[3:]
            
            if status == '??':
                untracked.append(filename)
            elif status[0] != ' ':
                staged.append({"file": filename, "status": status[0]})
            if status[1] != ' ':
                unstaged.append({"file": filename, "status": status[1]})
        
        return {
            "success": True,
            "branch": branch,
            "ahead_behind": ahead_behind,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "is_clean": len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0
        }
    
    return {"success": False, "error": result.get("error", result.get("stderr", "Unknown error"))}


@git_ops_mcp.tool()
def git_diff(
    staged: Annotated[bool, "Show staged changes"] = False
) -> dict[str, Any]:
    """Get git diff output."""
    args = ["diff", "--stat"]
    if staged:
        args.append("--staged")
    
    result = _run_git_command(args)
    
    if result["success"]:
        return {
            "success": True,
            "diff_stat": result["stdout"],
            "has_changes": len(result["stdout"].strip()) > 0
        }
    
    return {"success": False, "error": result.get("error", result.get("stderr", "Unknown error"))}


@git_ops_mcp.tool()
def git_add(
    files: Annotated[list[str], "List of files to stage"]
) -> dict[str, Any]:
    """Stage files for commit."""
    if not files:
        return {"success": False, "error": "No files specified"}
    
    # Validate all files are within repo
    for f in files:
        try:
            _validate_path(f)
        except ValueError as e:
            return {"success": False, "error": f"Invalid file {f}: {e}"}
    
    result = _run_git_command(["add"] + files)
    
    if result["success"]:
        return {"success": True, "files_staged": len(files)}
    
    return {"success": False, "error": result.get("stderr", "Unknown error")}


@git_ops_mcp.tool()
def git_commit(
    message: Annotated[str, "Commit message"]
) -> dict[str, Any]:
    """Create a commit with staged changes."""
    if not message or not message.strip():
        return {"success": False, "error": "Commit message required"}
    
    # Check if there are staged changes
    status = git_status()
    if not status.get("staged"):
        return {"success": False, "error": "No staged changes to commit"}
    
    result = _run_git_command(["commit", "-m", message])
    
    if result["success"]:
        # Extract commit hash
        hash_match = re.search(r'\[.+?([a-f0-9]+)\]', result["stdout"])
        commit_hash = hash_match.group(1)[:8] if hash_match else "unknown"
        
        return {
            "success": True,
            "commit_hash": commit_hash,
            "message": message
        }
    
    return {"success": False, "error": result.get("stderr", "Unknown error")}


@git_ops_mcp.tool()
def git_log(
    limit: Annotated[int, "Number of commits to show"] = 10
) -> dict[str, Any]:
    """Get commit history."""
    limit = min(max(1, limit), 50)  # Clamp between 1-50
    
    result = _run_git_command([
        "log", f"--max-count={limit}",
        "--pretty=format:%H|%h|%an|%ae|%ad|%s",
        "--date=short"
    ])
    
    if result["success"]:
        commits = []
        for line in result["stdout"].strip().split('\n'):
            if '|' in line:
                parts = line.split('|', 5)
                if len(parts) == 6:
                    commits.append({
                        "hash": parts[0],
                        "short_hash": parts[1],
                        "author": parts[2],
                        "email": parts[3],
                        "date": parts[4],
                        "message": parts[5]
                    })
        
        return {"success": True, "commits": commits, "count": len(commits)}
    
    return {"success": False, "error": result.get("stderr", "Unknown error")}


@git_ops_mcp.tool()
def git_checkout(
    ref: Annotated[str, "Branch, tag, or commit to checkout"]
) -> dict[str, Any]:
    """Checkout a git reference."""
    if not ref or not ref.strip():
        return {"success": False, "error": "Reference required"}
    
    # Validate ref format (basic)
    if not re.match(r'^[a-zA-Z0-9_./-]+$', ref):
        return {"success": False, "error": "Invalid reference format"}
    
    result = _run_git_command(["checkout", ref])
    
    if result["success"]:
        return {"success": True, "checked_out": ref}
    
    return {"success": False, "error": result.get("stderr", "Unknown error")}


# =============================================================================
# Main entry point
# =============================================================================

SERVERS = {
    "filesystem": filesystem_mcp,
    "code_executor": code_executor_mcp,
    "git_ops": git_ops_mcp,
}


def main():
    """Run MCP server based on CLI argument."""
    if len(sys.argv) < 2:
        print(f"Usage: python -m aiworker.mcp.servers <server_name>")
        print(f"Available servers: {', '.join(SERVERS.keys())}")
        sys.exit(1)
    
    server_name = sys.argv[1]
    
    if server_name not in SERVERS:
        print(f"Unknown server: {server_name}")
        print(f"Available servers: {', '.join(SERVERS.keys())}")
        sys.exit(1)
    
    # Ensure base path exists
    BASE_PATH.mkdir(parents=True, exist_ok=True)
    
    # Run the server
    server = SERVERS[server_name]
    server.run(transport='stdio')


if __name__ == "__main__":
    main()
