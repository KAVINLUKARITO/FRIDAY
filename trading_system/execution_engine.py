from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from config import settings
from logger import get_logger
from models import Order, OrderStatus, Position, Signal
from risk_manager import KillSwitch
from storage import Storage


class ExecutionError(Exception):
    pass


class ExecutionEngine:
    def __init__(self, storage: Storage, kill_switch: KillSwitch) -> None:
        self.storage = storage
        self.kill_switch = kill_switch
        self.logger = get_logger("execution_engine")
        self._exchange: object | None = None

    async def place_order(self, signal: Signal, qty: float) -> Order:
        client_order_id = hashlib.sha256(
            f"{signal.signal_id}{signal.symbol}{signal.side}".encode("utf-8")
        ).hexdigest()
        existing = self.storage.get_order_by_client_id(client_order_id)
        if existing is not None and existing.status in {OrderStatus.SUBMITTED, OrderStatus.FILLED}:
            return existing

        now = datetime.now(UTC)
        order = Order(
            order_id=str(uuid4()),
            client_order_id=client_order_id,
            symbol=signal.symbol,
            side=signal.side,
            qty=qty,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status=OrderStatus.PENDING,
            strategy_name=signal.strategy_name,
            run_id=settings.run_id,
            created_at=now,
            updated_at=now,
        )
        if existing is None:
            self.storage.save_order(order)
        else:
            order.order_id = existing.order_id
            self.storage.update_order(order)

        last_error = "unknown execution failure"
        for attempt in range(settings.max_order_retries):
            try:
                if settings.mode == "paper":
                    self._paper_fill(order)
                else:
                    await self._live_fill(order)
                order.updated_at = datetime.now(UTC)
                self.storage.update_order(order)
                return order
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
                self.logger.warning(
                    "order attempt %s/%s failed for %s: %s",
                    attempt + 1,
                    settings.max_order_retries,
                    order.client_order_id,
                    last_error,
                )
                await asyncio.sleep(settings.retry_backoff_seconds * (2**attempt))

        order.status = OrderStatus.REJECTED
        order.rejected_reason = last_error
        order.updated_at = datetime.now(UTC)
        self.storage.update_order(order)
        return order

    def _paper_fill(self, order: Order) -> None:
        if order.side == "BUY":
            fill_price = order.entry_price * (1.0 + settings.slippage_pct)
        else:
            fill_price = order.entry_price * (1.0 - settings.slippage_pct)
        order.fill_price = round(fill_price, 6)
        order.filled_at = datetime.now(UTC)
        order.status = OrderStatus.FILLED

    async def _live_fill(self, order: Order) -> None:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ExecutionError("ccxt is not installed for live mode") from exc

        if self._exchange is None:
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

        exchange = self._exchange
        order.status = OrderStatus.SUBMITTED
        order.updated_at = datetime.now(UTC)
        self.storage.update_order(order)

        response = exchange.create_order(
            symbol=order.symbol,
            type="market",
            side=order.side.lower(),
            amount=order.qty,
        )
        exchange_order_id = response.get("id")
        deadline = asyncio.get_running_loop().time() + settings.order_timeout_seconds

        while asyncio.get_running_loop().time() < deadline:
            fetched = exchange.fetch_order(exchange_order_id, order.symbol)
            status = str(fetched.get("status", "")).lower()
            if status == "closed":
                average = fetched.get("average") or fetched.get("price") or order.entry_price
                order.fill_price = float(average)
                order.filled_at = datetime.now(UTC)
                order.status = OrderStatus.FILLED
                return
            if status in {"rejected", "canceled", "cancelled"}:
                raise ExecutionError(f"exchange rejected order: {status}")
            await asyncio.sleep(1.0)

        raise ExecutionError("live order timed out")

    async def cancel_order(self, order_id: str) -> bool:
        order = self.storage.get_order(order_id)
        if order is None:
            return False
        if order.status not in {OrderStatus.PENDING, OrderStatus.SUBMITTED}:
            return False
        if settings.mode == "live" and self._exchange is not None:
            try:
                self._exchange.cancel_order(order_id, order.symbol)
            except Exception as exc:
                self.logger.warning("cancel failed for %s: %s", order_id, exc)
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(UTC)
        self.storage.update_order(order)
        return True

    async def close_position(self, position: Position, current_price: float, reason: str) -> Order:
        side = "SELL" if position.side == "LONG" else "BUY"
        signal = Signal(
            signal_id=str(uuid4()),
            symbol=position.symbol,
            side=side,
            strategy_name=f"exit_{reason.lower()}",
            reason=reason,
            entry_price=current_price,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            timestamp=datetime.now(UTC),
        )
        return await self.place_order(signal, position.qty)
