from __future__ import annotations

from collections import deque
from statistics import fmean
from typing import Awaitable, Callable
from uuid import uuid4

from config import settings
from models import BarData, Signal
from storage import Storage


class PriceHistory:
    def __init__(self) -> None:
        self._prices: dict[str, deque[float]] = {}

    def add(self, symbol: str, price: float) -> None:
        history = self._prices.setdefault(symbol, deque(maxlen=settings.bar_history_size))
        history.append(float(price))

    def get(self, symbol: str) -> list[float]:
        return list(self._prices.get(symbol, deque()))

    def count(self, symbol: str) -> int:
        return len(self._prices.get(symbol, deque()))


class StrategyEngine:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.price_history = PriceHistory()
        for symbol in settings.symbols:
            for bar in self.storage.get_bars(symbol, limit=settings.bar_history_size):
                self.price_history.add(symbol, bar.close)

    async def on_bar(
        self,
        bar: BarData,
        callback: Callable[[Signal], Awaitable[None]],
    ) -> None:
        self.price_history.add(bar.symbol, bar.close)
        signal: Signal | None = None
        if settings.strategy_name == "ma_crossover":
            signal = self._ma_crossover(bar)
        if signal is not None:
            await callback(signal)

    def _ma_crossover(self, bar: BarData) -> Signal | None:
        prices = self.price_history.get(bar.symbol)
        if len(prices) < settings.ma_long + 1:
            return None

        short_ma = fmean(prices[-settings.ma_short :])
        long_ma = fmean(prices[-settings.ma_long :])
        prev_prices = prices[:-1]
        prev_short_ma = fmean(prev_prices[-settings.ma_short :])
        prev_long_ma = fmean(prev_prices[-settings.ma_long :])

        side: str | None = None
        reason: str | None = None
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            side = "BUY"
            reason = "ma crossover up"
        elif prev_short_ma >= prev_long_ma and short_ma < long_ma:
            side = "SELL"
            reason = "ma crossover down"

        if side is None or reason is None:
            return None

        entry = bar.close
        if side == "BUY":
            stop_loss = entry * (1.0 - settings.stop_loss_pct)
            take_profit = entry * (1.0 + settings.take_profit_pct)
        else:
            stop_loss = entry * (1.0 + settings.stop_loss_pct)
            take_profit = entry * (1.0 - settings.take_profit_pct)

        return Signal(
            signal_id=str(uuid4()),
            symbol=bar.symbol,
            side=side,
            strategy_name=settings.strategy_name,
            reason=reason,
            entry_price=entry,
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            timestamp=bar.timestamp,
            metadata={
                "short_ma": round(short_ma, 6),
                "long_ma": round(long_ma, 6),
                "prev_short_ma": round(prev_short_ma, 6),
                "prev_long_ma": round(prev_long_ma, 6),
            },
        )

    def get_price_history(self, symbol: str) -> list[float]:
        return self.price_history.get(symbol)
