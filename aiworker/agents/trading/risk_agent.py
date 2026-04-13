from __future__ import annotations

import math
from typing import Any

from agents.base_agent import AgentState, BaseAgent
from config import settings
from message_bus import Event, EventType


class RiskAgent(BaseAgent):
    """Risk approval agent for generated trading signals."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("RiskAgent", *args, **kwargs)
        self.balance = settings.initial_balance
        self.positions: dict[str, float] = {}

    def handle_signal_generated(self, event: Event) -> None:
        self.queue_context(dict(event.payload))
        self.execute_loop(event.payload["symbol"], event.run_id)

    def handle_portfolio_updated(self, event: Event) -> None:
        self.balance = float(event.payload["balance"])
        self.positions = {str(symbol): float(qty) for symbol, qty in event.payload["positions"].items()}

    def plan(self, state: AgentState) -> dict[str, Any]:
        return {
            "tool_name": "get_portfolio",
            "parameters": {"balance": self.balance, "positions": self.positions},
            "reason": f"Snapshot current portfolio before risk decision for {state.task}",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def on_complete(self, state: AgentState) -> None:
        symbol = state.context["symbol"]
        side = state.context["signal"]
        price = float(state.context["current_price"])
        max_position_value = self.balance * settings.max_position_pct
        qty = math.floor((max_position_value / price) * 1_000_000) / 1_000_000 if price > 0 else 0.0
        existing_qty = float(self.positions.get(symbol, 0.0))
        existing_value = existing_qty * price
        proposed_value = qty * price
        stop_loss_price = price * (1.0 - settings.stop_loss_pct) if side == "BUY" else price * (1.0 + settings.stop_loss_pct)

        rejection_reason: str | None = None
        if qty <= 0:
            rejection_reason = "calculated quantity is not positive"
        elif proposed_value > max_position_value:
            rejection_reason = "proposed position exceeds risk limit"
        elif existing_value + proposed_value > max_position_value:
            rejection_reason = "existing position already exceeds symbol limit"
        elif stop_loss_price <= 0:
            rejection_reason = "invalid stop loss price"

        if rejection_reason is None:
            self.bus.publish(
                Event(
                    event_type=EventType.RISK_APPROVED,
                    source_agent=self.name,
                    payload={
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "price": price,
                        "stop_loss_price": round(stop_loss_price, 6),
                    },
                    run_id=state.run_id,
                )
            )
        else:
            self.logger.info("risk rejected for %s: %s", symbol, rejection_reason)
            self.bus.publish(
                Event(
                    event_type=EventType.RISK_REJECTED,
                    source_agent=self.name,
                    payload={"symbol": symbol, "reason": rejection_reason},
                    run_id=state.run_id,
                )
            )
        state.status = "completed"
