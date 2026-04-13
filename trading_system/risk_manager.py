from __future__ import annotations

import math

from config import settings
from logger import get_logger
from models import PortfolioSnapshot, Position, RiskDecision, Signal
from storage import Storage


class KillSwitch:
    def __init__(self) -> None:
        self._active = False
        self._reason = ""
        self.logger = get_logger("kill_switch")

    def activate(self, reason: str) -> None:
        self._active = True
        self._reason = reason
        self.logger.critical("kill switch activated: %s", reason)

    def is_active(self) -> bool:
        return self._active

    def reset(self) -> None:
        self._active = False
        self._reason = ""


class RiskManager:
    def __init__(self, storage: Storage, kill_switch: KillSwitch) -> None:
        self.storage = storage
        self.kill_switch = kill_switch

    def evaluate(self, signal: Signal, portfolio: PortfolioSnapshot) -> RiskDecision:
        if self.kill_switch.is_active():
            return RiskDecision(approved=False, reason="kill switch active", signal=signal)

        open_trades = self.storage.get_open_trades()
        if len(open_trades) >= settings.max_open_trades:
            return RiskDecision(
                approved=False,
                reason=f"max open trades {settings.max_open_trades} reached",
                signal=signal,
            )

        if portfolio.daily_pnl <= -(settings.initial_balance * settings.max_daily_loss_pct):
            self.kill_switch.activate("daily loss limit breached")
            return RiskDecision(approved=False, reason="daily loss limit breached", signal=signal)

        for trade in open_trades:
            if trade.symbol == signal.symbol and trade.side == signal.side:
                return RiskDecision(
                    approved=False,
                    reason=f"duplicate position for {signal.symbol}",
                    signal=signal,
                )

        risk_amount = portfolio.balance * settings.max_risk_per_trade_pct
        price_risk = abs(signal.entry_price - signal.stop_loss)
        if price_risk == 0:
            return RiskDecision(
                approved=False,
                reason="zero price risk  invalid stop loss",
                signal=signal,
            )

        qty = round(max(risk_amount / price_risk, settings.min_order_qty), 6)
        position_value = qty * signal.entry_price
        if position_value > portfolio.balance:
            qty = math.floor(((portfolio.balance * 0.95) / signal.entry_price) * 1_000_000) / 1_000_000
            if qty < settings.min_order_qty:
                return RiskDecision(approved=False, reason="insufficient balance", signal=signal)

        if signal.side == "BUY" and signal.stop_loss >= signal.entry_price:
            return RiskDecision(
                approved=False,
                reason="stop loss above entry for BUY",
                signal=signal,
            )
        if signal.side == "SELL" and signal.stop_loss <= signal.entry_price:
            return RiskDecision(
                approved=False,
                reason="stop loss below entry for SELL",
                signal=signal,
            )

        return RiskDecision(
            approved=True,
            reason="all checks passed",
            adjusted_qty=round(qty, 6),
            signal=signal,
        )

    def check_exit_conditions(self, position: Position, current_price: float) -> str | None:
        if position.side == "LONG":
            if current_price <= position.stop_loss:
                return "STOP_LOSS"
            if current_price >= position.take_profit:
                return "TAKE_PROFIT"
            return None
        if current_price >= position.stop_loss:
            return "STOP_LOSS"
        if current_price <= position.take_profit:
            return "TAKE_PROFIT"
        return None
