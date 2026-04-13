from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from storage import StepRecord, Storage, TradeRecord, VulnerabilityRecord


def _step(run_id: str) -> StepRecord:
    return StepRecord(
        run_id=run_id,
        agent_name="Agent",
        step_number=1,
        tool_name="list_files",
        parameters={"path": "."},
        reason="List files",
        verification_status="SUCCESS",
        output_summary="[]",
        error=None,
        duration_seconds=0.1,
        timestamp=datetime.now(timezone.utc),
    )


def _trade(run_id: str) -> TradeRecord:
    return TradeRecord(
        run_id=run_id,
        order_id="order-1",
        symbol="BTCUSDT",
        side="BUY",
        qty=1.0,
        price=100.0,
        fill_price=100.0,
        timestamp=datetime.now(timezone.utc),
        pnl=None,
    )


def _vulnerability(run_id: str) -> VulnerabilityRecord:
    return VulnerabilityRecord(
        run_id=run_id,
        agent_name="ExploitValidatorAgent",
        target="http://localhost:8080",
        vuln_type="Missing CSP and HSTS Headers",
        severity="HIGH",
        evidence="missing headers",
        confirmed=True,
        timestamp=datetime.now(timezone.utc),
    )


def test_init_db_creates_all_tables(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "runtime" / "history.db")
    storage.init_db()
    assert storage.db_path.exists()


def test_save_step_and_get_run_steps_round_trip_correctly(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "runtime" / "history.db")
    storage.init_db()
    storage.save_step(_step("run-1"))
    records = storage.get_run_steps("run-1")
    assert len(records) == 1
    assert records[0].agent_name == "Agent"


def test_save_trade_and_get_run_trades_round_trip_correctly(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "runtime" / "history.db")
    storage.init_db()
    storage.save_trade(_trade("run-1"))
    records = storage.get_run_trades("run-1")
    assert len(records) == 1
    assert records[0].symbol == "BTCUSDT"


def test_save_vulnerability_and_get_run_vulnerabilities_round_trip(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "runtime" / "history.db")
    storage.init_db()
    storage.save_vulnerability(_vulnerability("run-1"))
    records = storage.get_run_vulnerabilities("run-1")
    assert len(records) == 1
    assert records[0].severity == "HIGH"


def test_get_all_run_ids_returns_correct_list(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "runtime" / "history.db")
    storage.init_db()
    storage.save_step(_step("run-a"))
    storage.save_trade(_trade("run-b"))
    assert storage.get_all_run_ids() == ["run-a", "run-b"]


def test_get_run_summary_returns_correct_counts(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "runtime" / "history.db")
    storage.init_db()
    storage.save_step(_step("run-1"))
    storage.save_trade(_trade("run-1"))
    storage.save_vulnerability(_vulnerability("run-1"))
    summary = storage.get_run_summary("run-1")
    assert summary["step_count"] == 1
    assert summary["trade_count"] == 1
    assert summary["vulnerability_count"] == 1
