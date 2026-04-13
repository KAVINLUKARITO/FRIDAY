from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from config import settings
from models import BarData, Signal
from storage import Storage
from strategy_engine import StrategyEngine


def make_bar(close: float, index: int) -> BarData:
    return BarData(
        symbol="BTCUSDT",
        timestamp=datetime.now(UTC) + timedelta(minutes=index),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100.0,
        simulated=True,
    )


@pytest.fixture()
def strategy(monkeypatch: pytest.MonkeyPatch) -> StrategyEngine:
    monkeypatch.setattr(settings, "symbols", ["BTCUSDT"])
    monkeypatch.setattr(settings, "ma_short", 3)
    monkeypatch.setattr(settings, "ma_long", 5)
    monkeypatch.setattr(settings, "bar_history_size", 6)
    runtime = Path("runtime/test_tmp/strategy")
    runtime.mkdir(parents=True, exist_ok=True)
    store = Storage(runtime / f"trading_{datetime.now(UTC).timestamp()}.db")
    store.init_db()
    return StrategyEngine(store)


async def collect_signal(engine: StrategyEngine, closes: list[float]) -> list[Signal]:
    signals: list[Signal] = []

    async def callback(signal: Signal) -> None:
        signals.append(signal)

    for index, close in enumerate(closes):
        await engine.on_bar(make_bar(close, index), callback)
    return signals


def test_no_signal_before_ma_long_bars_accumulated(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [100, 99, 98, 97, 96]))
    assert signals == []


def test_buy_signal_on_confirmed_upward_crossover(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [10, 9, 8, 9, 10, 12]))
    assert any(signal.side == "BUY" for signal in signals)


def test_sell_signal_on_confirmed_downward_crossover(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [10, 11, 12, 11, 10, 8]))
    assert any(signal.side == "SELL" for signal in signals)


def test_no_duplicate_signals_on_flat_ma(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [10, 10, 10, 10, 10, 10, 10]))
    assert signals == []


def test_stop_loss_below_entry_for_buy_signal(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [10, 9, 8, 9, 10, 12]))
    buy_signal = next(signal for signal in signals if signal.side == "BUY")
    assert buy_signal.stop_loss < buy_signal.entry_price


def test_take_profit_above_entry_for_buy_signal(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [10, 9, 8, 9, 10, 12]))
    buy_signal = next(signal for signal in signals if signal.side == "BUY")
    assert buy_signal.take_profit > buy_signal.entry_price


def test_stop_loss_above_entry_for_sell_signal(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [10, 11, 12, 11, 10, 8]))
    sell_signal = next(signal for signal in signals if signal.side == "SELL")
    assert sell_signal.stop_loss > sell_signal.entry_price


def test_take_profit_below_entry_for_sell_signal(strategy: StrategyEngine) -> None:
    signals = asyncio.run(collect_signal(strategy, [10, 11, 12, 11, 10, 8]))
    sell_signal = next(signal for signal in signals if signal.side == "SELL")
    assert sell_signal.take_profit < sell_signal.entry_price


def test_signal_id_is_unique_per_signal(strategy: StrategyEngine) -> None:
    first = asyncio.run(collect_signal(strategy, [10, 9, 8, 9, 10, 12]))
    second = asyncio.run(collect_signal(strategy, [12, 11, 10, 11, 12, 14]))
    ids = [signal.signal_id for signal in first + second]
    assert len(ids) == len(set(ids))


def test_price_history_trims_to_bar_history_size(strategy: StrategyEngine) -> None:
    asyncio.run(collect_signal(strategy, [1, 2, 3, 4, 5, 6, 7, 8]))
    assert len(strategy.get_price_history("BTCUSDT")) == 6
