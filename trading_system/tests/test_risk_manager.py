from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from config import settings
from models import PortfolioSnapshot, Position, Signal, Trade
from risk_manager import KillSwitch, RiskManager


class MockStorage:
    def __init__(self, open_trades: list[Trade] | None = None) -> None:
        self._open_trades = open_trades or []

    def get_open_trades(self) -> list[Trade]:
        return list(self._open_trades)


def make_signal(side: str = "BUY", entry: float = 100.0, stop: float = 98.0) -> Signal:
    return Signal(
        signal_id=str(uuid4()),
        symbol="BTCUSDT",
        side=side,
        strategy_name="ma_crossover",
        reason="test",
        entry_price=entry,
        stop_loss=stop,
        take_profit=104.0 if side == "BUY" else 96.0,
        timestamp=datetime.now(UTC),
    )


def make_snapshot(balance: float = 10000.0, daily_pnl: float = 0.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id=str(uuid4()),
        run_id="run-1",
        balance=balance,
        equity=balance,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        open_positions=0,
        daily_pnl=daily_pnl,
        daily_loss_limit_used_pct=0.0,
        timestamp=datetime.now(UTC),
    )


def make_trade(symbol: str = "BTCUSDT", side: str = "BUY") -> Trade:
    return Trade(
        trade_id=str(uuid4()),
        order_id=str(uuid4()),
        symbol=symbol,
        side=side,
        qty=1.0,
        entry_price=100.0,
        status="OPEN",
        strategy_name="ma_crossover",
        opened_at=datetime.now(UTC),
        run_id="run-1",
    )


def test_valid_signal_approved_with_correct_qty() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    decision = risk.evaluate(make_signal(), make_snapshot())
    assert decision.approved is True
    assert decision.adjusted_qty == pytest.approx(50.0)


def test_kill_switch_active_rejects_all_signals() -> None:
    kill = KillSwitch()
    kill.activate("manual")
    risk = RiskManager(MockStorage(), kill)
    decision = risk.evaluate(make_signal(), make_snapshot())
    assert decision.approved is False
    assert decision.reason == "kill switch active"


def test_max_open_trades_exceeded_rejects_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_open_trades", 1)
    risk = RiskManager(MockStorage([make_trade()]), KillSwitch())
    decision = risk.evaluate(make_signal(), make_snapshot())
    assert decision.approved is False
    assert "max open trades" in decision.reason


def test_daily_loss_limit_breach_activates_kill_switch_and_rejects() -> None:
    kill = KillSwitch()
    risk = RiskManager(MockStorage(), kill)
    decision = risk.evaluate(make_signal(), make_snapshot(daily_pnl=-600.0))
    assert decision.approved is False
    assert decision.reason == "daily loss limit breached"
    assert kill.is_active() is True


def test_duplicate_position_same_symbol_side_rejected() -> None:
    risk = RiskManager(MockStorage([make_trade("BTCUSDT", "BUY")]), KillSwitch())
    decision = risk.evaluate(make_signal("BUY"), make_snapshot())
    assert decision.approved is False
    assert "duplicate position" in decision.reason


def test_zero_price_risk_rejected() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    decision = risk.evaluate(make_signal(entry=100.0, stop=100.0), make_snapshot())
    assert decision.approved is False
    assert "zero price risk" in decision.reason


def test_insufficient_balance_qty_adjusted_or_rejected() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    decision = risk.evaluate(make_signal(entry=10000.0, stop=9990.0), make_snapshot(balance=100.0))
    assert decision.approved is False or (decision.adjusted_qty is not None and decision.adjusted_qty <= 0.0095)


def test_buy_stop_loss_above_entry_rejected() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    decision = risk.evaluate(make_signal(side="BUY", entry=100.0, stop=101.0), make_snapshot())
    assert decision.approved is False
    assert decision.reason == "stop loss above entry for BUY"


def test_sell_stop_loss_below_entry_rejected() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    decision = risk.evaluate(make_signal(side="SELL", entry=100.0, stop=99.0), make_snapshot())
    assert decision.approved is False
    assert decision.reason == "stop loss below entry for SELL"


def test_check_exit_conditions_triggers_stop_loss_for_long_correctly() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    position = Position(
        position_id="p1",
        symbol="BTCUSDT",
        side="LONG",
        qty=1.0,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        unrealized_pnl=0.0,
        opened_at=datetime.now(UTC),
        order_id="o1",
    )
    assert risk.check_exit_conditions(position, 95.0) == "STOP_LOSS"


def test_check_exit_conditions_triggers_take_profit_for_long_correctly() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    position = Position(
        position_id="p1",
        symbol="BTCUSDT",
        side="LONG",
        qty=1.0,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        unrealized_pnl=0.0,
        opened_at=datetime.now(UTC),
        order_id="o1",
    )
    assert risk.check_exit_conditions(position, 110.0) == "TAKE_PROFIT"


def test_check_exit_conditions_returns_none_when_neither_hit() -> None:
    risk = RiskManager(MockStorage(), KillSwitch())
    position = Position(
        position_id="p1",
        symbol="BTCUSDT",
        side="LONG",
        qty=1.0,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        unrealized_pnl=0.0,
        opened_at=datetime.now(UTC),
        order_id="o1",
    )
    assert risk.check_exit_conditions(position, 103.0) is None
