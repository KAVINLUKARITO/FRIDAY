from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from config import settings
from models import PortfolioSnapshot
from monitor import Monitor
from risk_manager import KillSwitch
from storage import Storage


class FakeDataEngine:
    def __init__(self, ages: dict[str, float]) -> None:
        self.ages = ages

    def get_last_bar_age(self, symbol: str) -> float:
        return self.ages.get(symbol, float("inf"))


class FakePortfolioManager:
    def __init__(self, daily_pnl: float = 0.0, open_positions: int = 0) -> None:
        self.daily_pnl = daily_pnl
        self._open_positions = [object() for _ in range(open_positions)]

    def get_open_positions(self) -> list[object]:
        return list(self._open_positions)

    def get_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            snapshot_id=str(uuid4()),
            run_id="run-1",
            balance=10000.0,
            equity=10000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            open_positions=len(self._open_positions),
            daily_pnl=self.daily_pnl,
            daily_loss_limit_used_pct=0.0,
            timestamp=datetime.now(UTC),
        )


@pytest.fixture()
def storage(monkeypatch: pytest.MonkeyPatch) -> Storage:
    monkeypatch.setattr(settings, "symbols", ["BTCUSDT"])
    runtime = Path("runtime/test_tmp/monitor")
    runtime.mkdir(parents=True, exist_ok=True)
    db_path = runtime / f"trading_{uuid4()}.db"
    store = Storage(db_path)
    store.init_db()
    return store


def test_healthy_status_when_all_checks_pass(storage: Storage) -> None:
    monitor = Monitor(storage, FakeDataEngine({"BTCUSDT": 1.0}), FakePortfolioManager(), KillSwitch())
    result = monitor.health_check()
    assert result.status == "HEALTHY"


def test_degraded_when_bar_age_exceeds_threshold(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_bar_age_seconds", 10.0)
    monitor = Monitor(storage, FakeDataEngine({"BTCUSDT": 11.0}), FakePortfolioManager(), KillSwitch())
    result = monitor.health_check()
    assert result.status == "DEGRADED"


def test_critical_when_kill_switch_is_active(storage: Storage) -> None:
    kill = KillSwitch()
    kill.activate("manual")
    monitor = Monitor(storage, FakeDataEngine({"BTCUSDT": 1.0}), FakePortfolioManager(), kill)
    result = monitor.health_check()
    assert result.status == "CRITICAL"


def test_critical_when_bar_age_exceeds_three_x_threshold(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_bar_age_seconds", 10.0)
    monitor = Monitor(storage, FakeDataEngine({"BTCUSDT": 31.0}), FakePortfolioManager(), KillSwitch())
    result = monitor.health_check()
    assert result.status == "CRITICAL"


def test_alert_triggered_when_daily_loss_over_80pct_limit(storage: Storage) -> None:
    portfolio = FakePortfolioManager(daily_pnl=-(settings.initial_balance * settings.max_daily_loss_pct * 0.81))
    monitor = Monitor(storage, FakeDataEngine({"BTCUSDT": 1.0}), portfolio, KillSwitch())
    result = monitor.health_check()
    assert any("daily loss exceeds 80%" in alert for alert in result.alerts)


def test_health_check_saves_portfolio_snapshot_to_storage(storage: Storage) -> None:
    monitor = Monitor(storage, FakeDataEngine({"BTCUSDT": 1.0}), FakePortfolioManager(), KillSwitch())
    monitor.health_check()
    assert storage.get_latest_snapshot() is not None


def test_no_exceptions_when_storage_returns_empty_results(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "symbols", [])
    monitor = Monitor(storage, FakeDataEngine({}), FakePortfolioManager(), KillSwitch())
    result = monitor.health_check()
    assert result.status in {"HEALTHY", "DEGRADED", "CRITICAL"}
