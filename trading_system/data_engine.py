from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from threading import Event
from typing import Awaitable, Callable

from config import settings
from logger import get_logger
from models import BarData
from storage import Storage


class DataEngine:
    def __init__(
        self,
        storage: Storage,
        on_bar: Callable[[BarData], Awaitable[None]],
    ) -> None:
        self.storage = storage
        self.on_bar = on_bar
        self.logger = get_logger("data_engine")
        self._shutdown_event = Event()
        self._last_bars: dict[str, BarData] = {}
        self._last_prices: dict[str, float] = {
            symbol: settings.base_prices.get(symbol, 100.0) for symbol in settings.symbols
        }
        self._rng = random.Random(20260411)
        self._exchange: object | None = None

    async def start(self) -> None:
        try:
            if settings.mode == "paper":
                await self._simulated_loop()
                return
            if settings.mode == "live" and settings.api_key:
                await self._live_loop()
                return
            self.logger.warning("live mode not fully configured; falling back to simulation")
            await self._simulated_loop()
        except Exception:
            self.logger.exception("data engine stopped due to unhandled error")
            self.stop()
            raise

    async def _simulated_loop(self) -> None:
        while not self._shutdown_event.is_set():
            for symbol in settings.symbols:
                last_price = self._last_prices.get(symbol, settings.base_prices.get(symbol, 100.0))
                change = self._rng.gauss(0.0, settings.simulated_volatility_pct)
                new_price = max(0.000001, last_price * (1.0 + change))
                high_noise = abs(self._rng.gauss(0.0, 0.001))
                low_noise = abs(self._rng.gauss(0.0, 0.001))
                bar = BarData(
                    symbol=symbol,
                    timestamp=datetime.now(UTC),
                    open=round(last_price, 6),
                    high=round(max(last_price, new_price) * (1.0 + high_noise), 6),
                    low=round(min(last_price, new_price) * (1.0 - low_noise), 6),
                    close=round(new_price, 6),
                    volume=round(self._rng.uniform(100.0, 10000.0), 6),
                    simulated=True,
                )
                self._last_prices[symbol] = bar.close
                self._last_bars[symbol] = bar
                self.storage.save_bar(bar)
                await self.on_bar(bar)
            await asyncio.sleep(settings.poll_interval_seconds)

    async def _live_loop(self) -> None:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError:
            self.logger.warning("ccxt is not installed; falling back to simulation")
            await self._simulated_loop()
            return

        exchange_cls = getattr(ccxt, settings.exchange_id)
        exchange = exchange_cls(
            {
                "apiKey": settings.api_key,
                "secret": settings.api_secret,
                "enableRateLimit": True,
            }
        )
        if settings.testnet and hasattr(exchange, "set_sandbox_mode"):
            exchange.set_sandbox_mode(True)
        self._exchange = exchange

        while not self._shutdown_event.is_set():
            for symbol in settings.symbols:
                try:
                    ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1m", limit=1)
                    if not ohlcv:
                        continue
                    candle = ohlcv[-1]
                    bar = BarData(
                        symbol=symbol,
                        timestamp=datetime.fromtimestamp(candle[0] / 1000, tz=UTC),
                        open=float(candle[1]),
                        high=float(candle[2]),
                        low=float(candle[3]),
                        close=float(candle[4]),
                        volume=float(candle[5]),
                        simulated=False,
                    )
                    self._last_prices[symbol] = bar.close
                    self._last_bars[symbol] = bar
                    self.storage.save_bar(bar)
                    await self.on_bar(bar)
                except Exception as exc:
                    self.logger.error("live data fetch failed for %s: %s", symbol, exc)
                    await asyncio.sleep(5.0)
            await asyncio.sleep(settings.poll_interval_seconds)

    def stop(self) -> None:
        self._shutdown_event.set()

    def get_last_bar(self, symbol: str) -> BarData | None:
        return self._last_bars.get(symbol)

    def get_last_bar_age(self, symbol: str) -> float:
        bar = self.get_last_bar(symbol)
        if bar is None:
            return float("inf")
        return max((datetime.now(UTC) - bar.timestamp).total_seconds(), 0.0)
