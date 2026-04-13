"""Tests for the minimal CLI interface.

Validates:
- Argument parsing for all five commands.
- Each command dispatches to the correct handler.
- Structured JSON output.
- Deterministic behaviour (no randomness).
"""
from __future__ import annotations

import json
import os
import textwrap
import tempfile
from unittest import mock

import pytest

from aiworker.cli import build_parser, main


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestBuildParser:
    """Verify that the argument parser accepts all supported commands."""

    def test_validate_requires_patch(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["validate"])

    def test_validate_parses_patch(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "--patch", "some.patch"])
        assert args.command == "validate"
        assert args.patch == "some.patch"

    def test_simulate_requires_patch(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["simulate"])

    def test_simulate_parses_patch(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["simulate", "--patch", "s.patch"])
        assert args.command == "simulate"
        assert args.patch == "s.patch"

    def test_advisory_requires_goal(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["advisory"])

    def test_advisory_parses_goal(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["advisory", "--goal", "improve tests"])
        assert args.command == "advisory"
        assert args.goal == "improve tests"

    def test_memory_stats_no_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["memory-stats"])
        assert args.command == "memory-stats"

    def test_run_parses_runtime_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--goal", "research new techniques", "--max-cycles", "1"])
        assert args.command == "run"
        assert args.goal == "research new techniques"
        assert args.max_cycles == 1

    def test_status_no_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_stop_no_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["stop"])
        assert args.command == "stop"

    def test_list_attempts_no_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["list-attempts"])
        assert args.command == "list-attempts"

    def test_no_command_raises(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


# ---------------------------------------------------------------------------
# Integration tests (thin — call main() with real/mocked modules)
# ---------------------------------------------------------------------------

def _sample_patch() -> str:
    return textwrap.dedent("""\
        --- a/hello.py
        +++ b/hello.py
        @@ -1 +1,2 @@
         print("hello")
        +print("world")
    """)


class TestMainValidate:
    def test_validate_valid_patch(self, tmp_path, capsys) -> None:
        patch_file = tmp_path / "good.patch"
        patch_file.write_text(_sample_patch())
        rc = main(["validate", "--patch", str(patch_file)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "valid" in data
        assert isinstance(data["valid"], bool)

    def test_validate_missing_file(self, capsys) -> None:
        rc = main(["validate", "--patch", "/nonexistent/file.patch"])
        assert rc == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "error" in data


class TestMainSimulate:
    def test_simulate_valid_patch(self, tmp_path, capsys) -> None:
        patch_file = tmp_path / "sim.patch"
        patch_file.write_text(_sample_patch())
        rc = main(["simulate", "--patch", str(patch_file)])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "estimated_success_probability" in data
        assert "overall_risk" in data

    def test_simulate_missing_file(self, capsys) -> None:
        rc = main(["simulate", "--patch", "/nonexistent/file.patch"])
        assert rc == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "error" in data


class TestMainAdvisory:
    def test_advisory_returns_json(self, capsys) -> None:
        # Mock the HTTP call so no external request is made.
        with mock.patch("aiworker.advisory.advisor.urllib.request.urlopen",
                        side_effect=Exception("no network")):
            rc = main(["advisory", "--goal", "add logging"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "risk_analysis" in data


class TestMainMemoryStats:
    def test_memory_stats_in_memory(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("AIWORKER_DB_PATH", ":memory:")
        rc = main(["memory-stats"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["change_attempts"] == 0


class TestMainListAttempts:
    def test_list_attempts_empty(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("AIWORKER_DB_PATH", ":memory:")
        rc = main(["list-attempts"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == []


class TestRuntimeCommands:
    def test_runtime_status_returns_json(self, capsys) -> None:
        rc = main(["status"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "running" in data
        assert "iteration" in data

    def test_runtime_run_bounded_cycle_returns_json(self, capsys, monkeypatch, tmp_path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIWORKER_DB_PATH", str(tmp_path / "runtime.db"))
        rc = main(["run", "--goal", "research new techniques", "--max-cycles", "1", "--sleep-interval", "0"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "iteration" in data
        assert data["iteration"] >= 1


# ---------------------------------------------------------------------------
# Determinism check
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_simulate_is_deterministic(self, tmp_path, capsys) -> None:
        patch_file = tmp_path / "det.patch"
        patch_file.write_text(_sample_patch())
        main(["simulate", "--patch", str(patch_file)])
        out1 = capsys.readouterr().out
        main(["simulate", "--patch", str(patch_file)])
        out2 = capsys.readouterr().out
        assert out1 == out2
