from __future__ import annotations

import json
from pathlib import Path

import pytest

import runner
import tools
from agents.bug_bounty.analyzer_agent import AnalyzerAgent
from agents.bug_bounty.exploit_validator_agent import ExploitValidatorAgent
from agents.bug_bounty.recon_agent import ReconAgent
from agents.bug_bounty.reporter_agent import ReporterAgent
from agents.bug_bounty.scanner_agent import ScannerAgent
from executor import Executor
from message_bus import Event, EventType, bus
from storage import Storage
from validator import Validator
from verifier import Verifier


@pytest.fixture()
def bug_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    workspace.mkdir()
    runtime.mkdir()
    monkeypatch.setattr(tools.settings, "workspace_dir", workspace)
    monkeypatch.setattr(tools.settings, "db_path", runtime / "history.db")
    monkeypatch.setattr(tools.settings, "bug_bounty_target", "http://localhost:8080")
    monkeypatch.setattr(runner.settings, "workspace_dir", workspace)
    monkeypatch.setattr(runner.settings, "db_path", runtime / "history.db")
    monkeypatch.setattr(runner.settings, "bug_bounty_target", "http://localhost:8080")
    monkeypatch.setattr(tools.settings, "safe_test_mode", True)
    bus.clear()
    return tmp_path


def _components() -> tuple[Validator, Executor, Verifier, Storage]:
    storage = Storage(tools.settings.db_path)
    storage.init_db()
    return Validator(), Executor(), Verifier(), storage


def test_recon_agent_completes_and_publishes_recon_complete(
    bug_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator, executor, verifier, storage = _components()
    recon = ReconAgent(bus, validator, executor, verifier, storage)
    monkeypatch.setitem(tools.TOOL_REGISTRY, "http_request", lambda **kwargs: {"headers": {}, "body": "<a href='/a'>A</a>"})
    monkeypatch.setitem(tools.TOOL_REGISTRY, "parse_html", lambda **kwargs: ["/a"])
    monkeypatch.setitem(tools.TOOL_REGISTRY, "port_scan", lambda **kwargs: {"open_ports": [8080], "closed_ports": []})
    events: list[Event] = []
    bus.subscribe(EventType.RECON_COMPLETE, lambda event: events.append(event))

    state = recon.execute_loop("http://localhost:8080", "run-1")

    assert state.status == "completed"
    assert events[0].payload["open_ports"] == [8080]


def test_scanner_agent_activates_on_recon_complete_and_publishes_scan_complete(
    bug_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator, executor, verifier, storage = _components()
    scanner = ScannerAgent(bus, validator, executor, verifier, storage)
    monkeypatch.setitem(tools.TOOL_REGISTRY, "scan_headers", lambda **kwargs: {"missing": ["Content-Security-Policy"], "present": [], "risk_level": "MEDIUM"})
    monkeypatch.setitem(tools.TOOL_REGISTRY, "check_sql_injection", lambda **kwargs: {"tested": True, "vulnerable": False, "evidence": "ok", "simulated": True})
    monkeypatch.setitem(tools.TOOL_REGISTRY, "check_xss", lambda **kwargs: {"tested": True, "vulnerable": False, "evidence": "ok", "simulated": True})
    events: list[Event] = []
    bus.subscribe(EventType.SCAN_COMPLETE, lambda event: events.append(event))

    scanner.handle_recon_complete(
        Event(
            event_type=EventType.RECON_COMPLETE,
            source_agent="ReconAgent",
            payload={"target": "http://localhost:8080", "response": {"headers": {}}, "urls": [], "open_ports": [8080]},
            run_id="run-1",
        )
    )

    assert events
    assert events[0].payload["header_findings"]["risk_level"] == "MEDIUM"


def test_analyzer_agent_classifies_high_severity_correctly(bug_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    analyzer = AnalyzerAgent(bus, validator, executor, verifier, storage)
    events: list[Event] = []
    bus.subscribe(EventType.ANALYSIS_COMPLETE, lambda event: events.append(event))

    analyzer.handle_scan_complete(
        Event(
            event_type=EventType.SCAN_COMPLETE,
            source_agent="ScannerAgent",
            payload={
                "target": "http://localhost:8080",
                "header_findings": {
                    "missing": ["Content-Security-Policy", "Strict-Transport-Security"],
                    "present": [],
                    "risk_level": "HIGH",
                },
                "sqli_result": {"vulnerable": False},
                "xss_result": {"vulnerable": False},
            },
            run_id="run-1",
        )
    )

    assert events
    assert any(finding["severity"] == "HIGH" for finding in events[0].payload["findings"])


def test_exploit_validator_agent_confirms_high_findings(
    bug_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator, executor, verifier, storage = _components()
    agent = ExploitValidatorAgent(bus, validator, executor, verifier, storage)
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "http_request",
        lambda **kwargs: {
            "headers": {"X-Frame-Options": "DENY"},
            "body": "ok",
            "status_code": 200,
            "url": "http://localhost:8080",
            "elapsed_ms": 1.0,
        },
    )
    events: list[Event] = []
    bus.subscribe(EventType.EXPLOIT_VALIDATED, lambda event: events.append(event))

    agent.handle_analysis_complete(
        Event(
            event_type=EventType.ANALYSIS_COMPLETE,
            source_agent="AnalyzerAgent",
            payload={
                "target": "http://localhost:8080",
                "findings": [{"type": "Missing CSP and HSTS Headers", "severity": "HIGH", "detail": "missing"}],
            },
            run_id="run-1",
        )
    )

    assert events
    assert events[0].payload["validated_findings"][0]["confirmed"] is True


def test_reporter_agent_writes_json_report_to_workspace(bug_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    reporter = ReporterAgent(bus, validator, executor, verifier, storage)

    reporter.handle_exploit_validated(
        Event(
            event_type=EventType.EXPLOIT_VALIDATED,
            source_agent="ExploitValidatorAgent",
            payload={
                "target": "http://localhost:8080",
                "validated_findings": [
                    {"type": "Missing CSP and HSTS Headers", "severity": "HIGH", "confirmed": True, "evidence": "missing"},
                ],
            },
            run_id="run-1",
        )
    )

    report_path = tools.settings.workspace_dir / "bug_bounty_report_run-1.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["high"] == 1


def test_full_pipeline_run_completes_without_error_and_report_contains_expected_fields(
    bug_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "http_request",
        lambda **kwargs: {
            "status_code": 200,
            "headers": {"X-Frame-Options": "DENY"},
            "body": "<a href='/home'>home</a>",
            "url": "http://localhost:8080",
            "elapsed_ms": 1.0,
        },
    )
    monkeypatch.setitem(tools.TOOL_REGISTRY, "parse_html", lambda **kwargs: ["/home"])
    monkeypatch.setitem(tools.TOOL_REGISTRY, "port_scan", lambda **kwargs: {"open_ports": [8080], "closed_ports": [80]})
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "scan_headers",
        lambda **kwargs: {
            "missing": ["Content-Security-Policy", "Strict-Transport-Security"],
            "present": ["X-Frame-Options"],
            "risk_level": "HIGH",
        },
    )
    monkeypatch.setitem(tools.TOOL_REGISTRY, "check_sql_injection", lambda **kwargs: {"tested": True, "vulnerable": False, "evidence": "ok", "simulated": True})
    monkeypatch.setitem(tools.TOOL_REGISTRY, "check_xss", lambda **kwargs: {"tested": True, "vulnerable": False, "evidence": "ok", "simulated": True})

    run_id = runner.run_bug_bounty("http://localhost:8080")
    report_path = tools.settings.workspace_dir / f"bug_bounty_report_{run_id}.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["run_id"] == run_id
    assert "summary" in report
    assert "findings" in report
