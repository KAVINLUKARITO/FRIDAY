from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

from config import settings
from models import Order, PortfolioSnapshot, Position, Trade
from storage import Storage


class PortfolioManager:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.balance: float = settings.initial_balance
        self.positions: dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.daily_pnl: float = 0.0
        self.daily_reset_date: date = date.today()
        self.run_id: str = settings.run_id

    def load_state(self) -> None:
        latest = self.storage.get_latest_snapshot()
        if latest is None:
            self.balance = settings.initial_balance
            self.realized_pnl = 0.0
            self.daily_pnl = 0.0
            self.daily_reset_date = date.today()
            self.run_id = settings.run_id
        else:
            self.balance = latest.balance
            self.realized_pnl = latest.realized_pnl
            self.daily_pnl = latest.daily_pnl
            self.daily_reset_date = latest.timestamp.date()
            self.run_id = latest.run_id

        if settings.state_path.exists():
            try:
                payload = json.loads(settings.state_path.read_text(encoding="utf-8"))
                self.run_id = str(payload.get("run_id", self.run_id))
                if "balance" in payload:
                    self.balance = float(payload["balance"])
                if "realized_pnl" in payload:
                    self.realized_pnl = float(payload["realized_pnl"])
                if "daily_pnl" in payload:
                    self.daily_pnl = float(payload["daily_pnl"])
                stored_reset_date = payload.get("daily_reset_date")
                if stored_reset_date:
                    self.daily_reset_date = date.fromisoformat(str(stored_reset_date))
            except (OSError, json.JSONDecodeError):
                pass

        if self.daily_reset_date != date.today():
            self.daily_pnl = 0.0
            self.daily_reset_date = date.today()

        self.positions = {}
        for trade in self.storage.get_open_trades():
            order = self.storage.get_order(trade.order_id)
            if order is None:
                continue
            entry = order.fill_price if order.fill_price is not None else order.entry_price
            self.positions[trade.symbol] = Position(
                position_id=trade.trade_id,
                symbol=trade.symbol,
                side="LONG" if trade.side == "BUY" else "SHORT",
                qty=trade.qty,
                entry_price=entry,
                current_price=entry,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                unrealized_pnl=0.0,
                opened_at=trade.opened_at,
                order_id=trade.order_id,
            )

    def save_state(self) -> None:
        snapshot = self.get_snapshot()
        self.storage.save_snapshot(snapshot)
        payload = {
            "run_id": self.run_id,
            "balance": self.balance,
            "realized_pnl": self.realized_pnl,
            "daily_pnl": self.daily_pnl,
            "daily_reset_date": self.daily_reset_date.isoformat(),
            "positions": {symbol: position.model_dump(mode="json") for symbol, position in self.positions.items()},
        }
        settings.state_path.parent.mkdir(parents=True, exist_ok=True)
        settings.state_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def on_order_filled(self, order: Order) -> Trade:
        fill_price = order.fill_price if order.fill_price is not None else order.entry_price
        trade = Trade(
            trade_id=str(uuid4()),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            entry_price=fill_price,
            status="OPEN",
            strategy_name=order.strategy_name,
            opened_at=order.filled_at if order.filled_at is not None else datetime.now(UTC),
            run_id=order.run_id,
        )
        if order.side == "BUY":
            self.balance -= order.qty * fill_price
        else:
            self.balance += order.qty * fill_price
        self.positions[order.symbol] = Position(
            position_id=trade.trade_id,
            symbol=order.symbol,
            side="LONG" if order.side == "BUY" else "SHORT",
            qty=order.qty,
            entry_price=fill_price,
            current_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            unrealized_pnl=0.0,
            opened_at=trade.opened_at,
            order_id=trade.order_id,
        )
        self.storage.save_trade(trade)
        self.save_state()
        return trade

    def on_position_closed(self, position: Position, exit_price: float, reason: str) -> Trade:
        open_trade = next(
            (trade for trade in self.storage.get_open_trades() if trade.trade_id == position.position_id),
            None,
        )
        if open_trade is None:
            raise RuntimeError(f"open trade not found for position {position.position_id}")

        if position.side == "LONG":
            pnl = (exit_price - position.entry_price) * position.qty
            self.balance += position.qty * exit_price
        else:
            pnl = (position.entry_price - exit_price) * position.qty
            self.balance -= position.qty * exit_price

        open_trade.exit_price = exit_price
        open_trade.pnl = pnl
        open_trade.status = "CLOSED"
        open_trade.closed_at = datetime.now(UTC)

        self.realized_pnl += pnl
        self.daily_pnl += pnl
        self.positions.pop(position.symbol, None)
        self.storage.update_trade(open_trade)
        self.save_state()
        return open_trade

    def update_prices(self, symbol: str, price: float) -> None:
        position = self.positions.get(symbol)
        if position is None:
            return
        position.current_price = price
        if position.side == "LONG":
            position.unrealized_pnl = (price - position.entry_price) * position.qty
        else:
            position.unrealized_pnl = (position.entry_price - price) * position.qty

    def get_snapshot(self) -> PortfolioSnapshot:
        unrealized_pnl = sum(position.unrealized_pnl for position in self.positions.values())
        equity = self.balance + unrealized_pnl
        daily_loss_limit_used_pct = abs(min(self.daily_pnl, 0.0)) / (
            settings.initial_balance * settings.max_daily_loss_pct
        )
        return PortfolioSnapshot(
            snapshot_id=str(uuid4()),
            run_id=self.run_id,
            balance=round(self.balance, 6),
            equity=round(equity, 6),
            unrealized_pnl=round(unrealized_pnl, 6),
            realized_pnl=round(self.realized_pnl, 6),
            open_positions=len(self.positions),
            daily_pnl=round(self.daily_pnl, 6),
            daily_loss_limit_used_pct=round(daily_loss_limit_used_pct, 6),
            timestamp=datetime.now(UTC),
        )

    def get_open_positions(self) -> list[Position]:
        return list(self.positions.values())

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)
