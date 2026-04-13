from __future__ import annotations

import threading
from pathlib import Path

import pytest

import tools
from agents.trading.data_agent import DataAgent
from agents.trading.execution_agent import ExecutionAgent
from agents.trading.portfolio_agent import PortfolioAgent
from agents.trading.risk_agent import RiskAgent
from agents.trading.strategy_agent import StrategyAgent
from executor import Executor
from message_bus import Event, EventType, bus
from storage import Storage
from validator import Validator
from verifier import Verifier


@pytest.fixture()
def trading_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    workspace.mkdir()
    runtime.mkdir()
    monkeypatch.setattr(tools.settings, "workspace_dir", workspace)
    monkeypatch.setattr(tools.settings, "db_path", runtime / "history.db")
    monkeypatch.setattr(tools.settings, "poll_interval_seconds", 0.01)
    monkeypatch.setattr(tools.settings, "ma_short", 2)
    monkeypatch.setattr(tools.settings, "ma_long", 3)
    monkeypatch.setattr(tools.settings, "trading_symbols", ["BTCUSDT"])
    bus.clear()
    return tmp_path


def _components() -> tuple[Validator, Executor, Verifier, Storage]:
    storage = Storage(tools.settings.db_path)
    storage.init_db()
    return Validator(), Executor(), Verifier(), storage


def test_data_agent_publishes_market_data_updated(
    trading_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator, executor, verifier, storage = _components()
    data_agent = DataAgent(bus, validator, executor, verifier, storage)
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "get_market_data",
        lambda **kwargs: {
            "symbol": "BTCUSDT",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "simulated": True,
        },
    )
    events: list[Event] = []

    def capture(event: Event) -> None:
        events.append(event)
        data_agent.shutdown_event.set()

    bus.subscribe(EventType.MARKET_DATA_UPDATED, capture)
    thread = threading.Thread(target=data_agent.poll_market_data, args=("run-1",), daemon=True)
    thread.start()
    thread.join(timeout=1.0)
    assert events


def test_strategy_agent_publishes_signal_generated_on_crossover(trading_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    strategy = StrategyAgent(bus, validator, executor, verifier, storage)
    events: list[Event] = []
    bus.subscribe(EventType.SIGNAL_GENERATED, lambda event: events.append(event))

    strategy.handle_market_data(
        Event(
            event_type=EventType.MARKET_DATA_UPDATED,
            source_agent="DataAgent",
            payload={
                "symbol": "BTCUSDT",
                "data": {"close": 105.0},
                "price_history": [100.0, 101.0, 105.0],
            },
            run_id="run-1",
        )
    )

    assert events
    assert events[0].payload["signal"] == "BUY"


def test_risk_agent_approves_valid_order(trading_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    risk = RiskAgent(bus, validator, executor, verifier, storage)
    events: list[Event] = []
    bus.subscribe(EventType.RISK_APPROVED, lambda event: events.append(event))

    risk.handle_signal_generated(
        Event(
            event_type=EventType.SIGNAL_GENERATED,
            source_agent="StrategyAgent",
            payload={"symbol": "BTCUSDT", "signal": "BUY", "current_price": 100.0},
            run_id="run-1",
        )
    )

    assert events
    assert events[0].payload["qty"] > 0


def test_risk_agent_rejects_order_exceeding_max_position_pct(trading_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    risk = RiskAgent(bus, validator, executor, verifier, storage)
    risk.positions["BTCUSDT"] = 20.0
    events: list[Event] = []
    bus.subscribe(EventType.RISK_REJECTED, lambda event: events.append(event))

    risk.handle_signal_generated(
        Event(
            event_type=EventType.SIGNAL_GENERATED,
            source_agent="StrategyAgent",
            payload={"symbol": "BTCUSDT", "signal": "BUY", "current_price": 100.0},
            run_id="run-1",
        )
    )

    assert events


def test_execution_agent_saves_trade_to_storage(trading_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    agent = ExecutionAgent(bus, validator, executor, verifier, storage)

    agent.handle_risk_approved(
        Event(
            event_type=EventType.RISK_APPROVED,
            source_agent="RiskAgent",
            payload={"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "price": 100.0},
            run_id="run-1",
        )
    )

    trades = storage.get_run_trades("run-1")
    assert len(trades) == 1


def test_portfolio_agent_updates_balance_correctly_after_buy(trading_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    agent = PortfolioAgent(bus, validator, executor, verifier, storage)
    events: list[Event] = []
    bus.subscribe(EventType.PORTFOLIO_UPDATED, lambda event: events.append(event))

    agent.handle_order_executed(
        Event(
            event_type=EventType.ORDER_EXECUTED,
            source_agent="ExecutionAgent",
            payload={"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "fill_price": 100.0, "timestamp": "2026-01-01T00:00:00+00:00"},
            run_id="run-1",
        )
    )

    assert agent.balance == pytest.approx(9900.0)
    assert events[0].payload["positions"]["BTCUSDT"] == pytest.approx(1.0)


def test_portfolio_agent_updates_balance_correctly_after_sell(trading_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    agent = PortfolioAgent(bus, validator, executor, verifier, storage)
    agent.handle_order_executed(
        Event(
            event_type=EventType.ORDER_EXECUTED,
            source_agent="ExecutionAgent",
            payload={"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "fill_price": 100.0, "timestamp": "2026-01-01T00:00:00+00:00"},
            run_id="run-1",
        )
    )
    agent.handle_order_executed(
        Event(
            event_type=EventType.ORDER_EXECUTED,
            source_agent="ExecutionAgent",
            payload={"symbol": "BTCUSDT", "side": "SELL", "qty": 1.0, "fill_price": 110.0, "timestamp": "2026-01-01T00:01:00+00:00"},
            run_id="run-1",
        )
    )
    assert agent.balance == pytest.approx(10010.0)


def test_pnl_calculated_correctly(trading_env: Path) -> None:
    validator, executor, verifier, storage = _components()
    agent = PortfolioAgent(bus, validator, executor, verifier, storage)
    events: list[Event] = []
    bus.subscribe(EventType.PORTFOLIO_UPDATED, lambda event: events.append(event))
    agent.handle_order_executed(
        Event(
            event_type=EventType.ORDER_EXECUTED,
            source_agent="ExecutionAgent",
            payload={"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "fill_price": 100.0, "timestamp": "2026-01-01T00:00:00+00:00"},
            run_id="run-1",
        )
    )
    agent.handle_order_executed(
        Event(
            event_type=EventType.ORDER_EXECUTED,
            source_agent="ExecutionAgent",
            payload={"symbol": "BTCUSDT", "side": "SELL", "qty": 1.0, "fill_price": 110.0, "timestamp": "2026-01-01T00:01:00+00:00"},
            run_id="run-1",
        )
    )
    assert events[-1].payload["last_trade_pnl"] == pytest.approx(10.0)
