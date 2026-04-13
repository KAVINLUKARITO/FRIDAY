from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from config import settings
from execution_engine import ExecutionEngine
from models import OrderStatus, Position, Signal
from risk_manager import KillSwitch
from storage import Storage


@pytest.fixture()
def storage():
    runtime = Path("runtime/test_tmp/execution")
    runtime.mkdir(parents=True, exist_ok=True)
    db_path = runtime / f"trading_{uuid4()}.db"
    store = Storage(db_path)
    store.init_db()
    return store


def make_signal(side: str = "BUY") -> Signal:
    return Signal(
        signal_id=str(uuid4()),
        symbol="BTCUSDT",
        side=side,
        strategy_name="ma_crossover",
        reason="test",
        entry_price=100.0,
        stop_loss=98.0 if side == "BUY" else 102.0,
        take_profit=104.0 if side == "BUY" else 96.0,
        timestamp=datetime.now(UTC),
    )


def test_place_order_fills_immediately_in_paper_mode(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "paper")
    engine = ExecutionEngine(storage, KillSwitch())
    order = asyncio.run(engine.place_order(make_signal("BUY"), 1.0))
    assert order.status is OrderStatus.FILLED


def test_fill_price_includes_slippage_for_buy(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "paper")
    monkeypatch.setattr(settings, "slippage_pct", 0.01)
    engine = ExecutionEngine(storage, KillSwitch())
    order = asyncio.run(engine.place_order(make_signal("BUY"), 1.0))
    assert order.fill_price == pytest.approx(101.0)


def test_fill_price_includes_slippage_for_sell(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "paper")
    monkeypatch.setattr(settings, "slippage_pct", 0.01)
    engine = ExecutionEngine(storage, KillSwitch())
    order = asyncio.run(engine.place_order(make_signal("SELL"), 1.0))
    assert order.fill_price == pytest.approx(99.0)


def test_duplicate_client_order_id_returns_existing_order(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "paper")
    engine = ExecutionEngine(storage, KillSwitch())
    signal = make_signal("BUY")
    first = asyncio.run(engine.place_order(signal, 1.0))
    second = asyncio.run(engine.place_order(signal, 1.0))
    assert first.order_id == second.order_id


def test_all_retries_exhausted_rejected_status(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "paper")
    monkeypatch.setattr(settings, "max_order_retries", 2)
    engine = ExecutionEngine(storage, KillSwitch())

    def fail_fill(order):  # type: ignore[no-untyped-def]
        raise RuntimeError("fill failed")

    monkeypatch.setattr(engine, "_paper_fill", fail_fill)
    order = asyncio.run(engine.place_order(make_signal("BUY"), 1.0))
    assert order.status is OrderStatus.REJECTED


def test_cancel_order_sets_status_to_cancelled(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "paper")
    engine = ExecutionEngine(storage, KillSwitch())
    signal = make_signal("BUY")
    order = asyncio.run(engine.place_order(signal, 1.0))
    order.status = OrderStatus.PENDING
    storage.update_order(order)
    cancelled = asyncio.run(engine.cancel_order(order.order_id))
    refreshed = storage.get_order(order.order_id)
    assert cancelled is True
    assert refreshed is not None and refreshed.status is OrderStatus.CANCELLED


def test_close_position_places_opposite_side_order(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "paper")
    engine = ExecutionEngine(storage, KillSwitch())
    position = Position(
        position_id="p1",
        symbol="BTCUSDT",
        side="LONG",
        qty=1.0,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=98.0,
        take_profit=104.0,
        unrealized_pnl=0.0,
        opened_at=datetime.now(UTC),
        order_id="o1",
    )
    order = asyncio.run(engine.close_position(position, 105.0, "TAKE_PROFIT"))
    assert order.side == "SELL"
