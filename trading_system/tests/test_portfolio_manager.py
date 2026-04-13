from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from config import settings
from models import Order, OrderStatus
from portfolio_manager import PortfolioManager
from storage import Storage


@pytest.fixture()
def storage(monkeypatch: pytest.MonkeyPatch) -> Storage:
    runtime = Path("runtime/test_tmp/portfolio")
    runtime.mkdir(parents=True, exist_ok=True)
    db_path = runtime / f"trading_{uuid4()}.db"
    state_path = runtime / f"state_{uuid4()}.json"
    monkeypatch.setattr(settings, "db_path", db_path)
    monkeypatch.setattr(settings, "state_path", state_path)
    store = Storage(settings.db_path)
    store.init_db()
    return store


def make_order(side: str = "BUY", price: float = 100.0) -> Order:
    now = datetime.now(UTC)
    return Order(
        order_id=str(uuid4()),
        client_order_id=str(uuid4()),
        symbol="BTCUSDT",
        side=side,
        qty=1.0,
        entry_price=price,
        stop_loss=98.0 if side == "BUY" else 102.0,
        take_profit=104.0 if side == "BUY" else 96.0,
        status=OrderStatus.FILLED,
        fill_price=price,
        filled_at=now,
        strategy_name="ma_crossover",
        run_id="run-1",
        created_at=now,
        updated_at=now,
    )


def test_load_state_initializes_with_initial_balance_when_no_snapshot(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    assert manager.balance == settings.initial_balance


def test_on_order_filled_creates_trade_and_deducts_from_balance(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    order = make_order("BUY", 100.0)
    storage.save_order(order)
    trade = manager.on_order_filled(order)
    assert trade.status == "OPEN"
    assert manager.balance == pytest.approx(settings.initial_balance - 100.0)


def test_on_position_closed_computes_correct_pnl_for_long_win(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    order = make_order("BUY", 100.0)
    storage.save_order(order)
    manager.on_order_filled(order)
    position = manager.get_position("BTCUSDT")
    assert position is not None
    trade = manager.on_position_closed(position, 110.0, "TAKE_PROFIT")
    assert trade.pnl == pytest.approx(10.0)


def test_on_position_closed_computes_correct_pnl_for_long_loss(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    order = make_order("BUY", 100.0)
    storage.save_order(order)
    manager.on_order_filled(order)
    position = manager.get_position("BTCUSDT")
    assert position is not None
    trade = manager.on_position_closed(position, 90.0, "STOP_LOSS")
    assert trade.pnl == pytest.approx(-10.0)


def test_update_prices_updates_unrealized_pnl_for_open_position(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    order = make_order("BUY", 100.0)
    storage.save_order(order)
    manager.on_order_filled(order)
    manager.update_prices("BTCUSDT", 110.0)
    position = manager.get_position("BTCUSDT")
    assert position is not None and position.unrealized_pnl == pytest.approx(10.0)


def test_daily_pnl_resets_on_new_calendar_day(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    manager.daily_pnl = -50.0
    manager.daily_reset_date = date.today() - timedelta(days=1)
    manager.save_state()

    reloaded = PortfolioManager(storage)
    reloaded.load_state()
    assert reloaded.daily_pnl == 0.0


def test_get_snapshot_equity_equals_balance_plus_unrealized_pnl(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    order = make_order("BUY", 100.0)
    storage.save_order(order)
    manager.on_order_filled(order)
    manager.update_prices("BTCUSDT", 110.0)
    snapshot = manager.get_snapshot()
    assert snapshot.equity == pytest.approx(snapshot.balance + snapshot.unrealized_pnl)


def test_save_state_and_reload_state_produce_identical_snapshots(storage: Storage) -> None:
    manager = PortfolioManager(storage)
    manager.load_state()
    order = make_order("BUY", 100.0)
    storage.save_order(order)
    manager.on_order_filled(order)
    manager.update_prices("BTCUSDT", 105.0)
    first = manager.get_snapshot()
    manager.save_state()

    reloaded = PortfolioManager(storage)
    reloaded.load_state()
    second = reloaded.get_snapshot()
    assert second.balance == pytest.approx(first.balance)
    assert second.realized_pnl == pytest.approx(first.realized_pnl)
    assert second.daily_pnl == pytest.approx(first.daily_pnl)
    assert second.open_positions == first.open_positions
