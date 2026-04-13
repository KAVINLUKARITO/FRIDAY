from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from models import BarData, Order, OrderStatus, PortfolioSnapshot, Trade
from storage import Storage


def make_order(index: int = 0) -> Order:
    now = datetime.now(UTC) + timedelta(seconds=index)
    return Order(
        order_id=str(uuid4()),
        client_order_id=f"client-{index}-{uuid4()}",
        symbol="BTCUSDT",
        side="BUY",
        qty=1.0,
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=104.0,
        status=OrderStatus.PENDING,
        strategy_name="ma_crossover",
        run_id="run-1",
        created_at=now,
        updated_at=now,
    )


def make_trade(order_id: str) -> Trade:
    return Trade(
        trade_id=str(uuid4()),
        order_id=order_id,
        symbol="BTCUSDT",
        side="BUY",
        qty=1.0,
        entry_price=100.0,
        status="OPEN",
        strategy_name="ma_crossover",
        opened_at=datetime.now(UTC),
        run_id="run-1",
    )


def make_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id=str(uuid4()),
        run_id="run-1",
        balance=10000.0,
        equity=10000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        open_positions=0,
        daily_pnl=0.0,
        daily_loss_limit_used_pct=0.0,
        timestamp=datetime.now(UTC),
    )


def make_bar(index: int) -> BarData:
    return BarData(
        symbol="BTCUSDT",
        timestamp=datetime.now(UTC) + timedelta(minutes=index),
        open=100.0 + index,
        high=101.0 + index,
        low=99.0 + index,
        close=100.5 + index,
        volume=1000.0 + index,
        simulated=True,
    )


def _db_path(test_name: str) -> Path:
    runtime = Path("runtime/test_tmp/storage")
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / f"{test_name}_{uuid4()}.db"


def test_init_db_creates_all_tables_and_indexes() -> None:
    storage = Storage(_db_path("init"))
    storage.init_db()
    storage.ping()


def test_save_order_and_get_order_round_trip_correctly() -> None:
    storage = Storage(_db_path("save_order"))
    storage.init_db()
    order = make_order()
    storage.save_order(order)
    loaded = storage.get_order(order.order_id)
    assert loaded is not None and loaded.client_order_id == order.client_order_id


def test_update_order_persists_status_change() -> None:
    storage = Storage(_db_path("update_order"))
    storage.init_db()
    order = make_order()
    storage.save_order(order)
    order.status = OrderStatus.FILLED
    storage.update_order(order)
    loaded = storage.get_order(order.order_id)
    assert loaded is not None and loaded.status is OrderStatus.FILLED


def test_get_order_by_client_id_returns_correct_order() -> None:
    storage = Storage(_db_path("client_id"))
    storage.init_db()
    order = make_order()
    storage.save_order(order)
    loaded = storage.get_order_by_client_id(order.client_order_id)
    assert loaded is not None and loaded.order_id == order.order_id


def test_get_open_orders_filters_by_status_correctly() -> None:
    storage = Storage(_db_path("open_orders"))
    storage.init_db()
    open_order = make_order(1)
    closed_order = make_order(2)
    closed_order.status = OrderStatus.CANCELLED
    storage.save_order(open_order)
    storage.save_order(closed_order)
    open_orders = storage.get_open_orders()
    assert [order.order_id for order in open_orders] == [open_order.order_id]


def test_save_trade_and_get_open_trades_round_trip() -> None:
    storage = Storage(_db_path("open_trades"))
    storage.init_db()
    order = make_order()
    storage.save_order(order)
    trade = make_trade(order.order_id)
    storage.save_trade(trade)
    open_trades = storage.get_open_trades()
    assert len(open_trades) == 1


def test_save_snapshot_and_get_latest_snapshot_round_trip() -> None:
    storage = Storage(_db_path("snapshot"))
    storage.init_db()
    snapshot = make_snapshot()
    storage.save_snapshot(snapshot)
    latest = storage.get_latest_snapshot()
    assert latest is not None and latest.snapshot_id == snapshot.snapshot_id


def test_save_bar_and_get_bars_return_correct_history() -> None:
    storage = Storage(_db_path("bars"))
    storage.init_db()
    bar1 = make_bar(1)
    bar2 = make_bar(2)
    storage.save_bar(bar1)
    storage.save_bar(bar2)
    bars = storage.get_bars("BTCUSDT")
    assert [bar.close for bar in bars] == [bar1.close, bar2.close]


def test_get_bars_respects_limit_parameter() -> None:
    storage = Storage(_db_path("bars_limit"))
    storage.init_db()
    for index in range(5):
        storage.save_bar(make_bar(index))
    bars = storage.get_bars("BTCUSDT", limit=2)
    assert len(bars) == 2


def test_concurrent_writes_do_not_raise_exceptions() -> None:
    storage = Storage(_db_path("concurrent"))
    storage.init_db()

    def write_order(index: int) -> None:
        storage.save_order(make_order(index))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write_order, range(10)))

    assert len(storage.get_open_orders()) == 10
