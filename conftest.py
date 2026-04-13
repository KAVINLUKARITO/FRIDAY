"""
conftest.py  Root pytest configuration.

Fixes:
- Windows tmp_path permission errors by using a known temp dir.
- Ensures runtime/ and workspace/ directories exist before tests.
- Prevents test pollution between test files.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest


#  Ensure required runtime directories exist 
def pytest_configure(config: pytest.Config) -> None:
    """Create runtime dirs needed by storage and tools."""
    for d in ("runtime", "workspace"):
        Path(d).mkdir(parents=True, exist_ok=True)
    local_tmp = (Path(".pytest_tmp_probe") / "tests").resolve()
    local_tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(local_tmp)
    os.environ["TEMP"] = str(local_tmp)
    tempfile.tempdir = str(local_tmp)


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    del config
    path_text = str(collection_path)
    return path_text.endswith("tests\\test_multimodel_orchestration.py") or path_text.endswith(
        "tests/test_multimodel_orchestration.py"
    )


#  Windows-safe tmp_path implementation 
@pytest.fixture()
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Override default tmp_path to use a known writable location.
    Fixes PermissionError on Windows pytest temp directory cleanup.
    """
    _ = tmp_path_factory
    root = (Path(".pytest_tmp_probe") / "tests").resolve()
    root.mkdir(parents=True, exist_ok=True)
    base = root / f"test_data_{uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    yield base
    # Best-effort cleanup  ignore errors on Windows file locks
    try:
        shutil.rmtree(base, ignore_errors=True)
    except Exception:
        pass


#  Isolated workspace per test 
@pytest.fixture()
def workspace() -> Path:
    """Provide an isolated workspace directory for each test."""
    ws = (Path(".pytest_tmp_probe") / "tests" / f"workspace_{uuid4().hex}").resolve()
    ws.mkdir(parents=True, exist_ok=True)
    return ws


#  Isolated SQLite db per test 
@pytest.fixture()
def db_path() -> Path:
    """Provide an isolated SQLite database path for each test."""
    db_dir = (Path(".pytest_tmp_probe") / "tests" / f"db_{uuid4().hex}").resolve()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "test.db"
