from __future__ import annotations

from typing import Any

from agents.base_agent import AgentState, BaseAgent
from config import settings
from message_bus import Event, EventType


class PortfolioAgent(BaseAgent):
    """Track balance, positions, and realized PnL."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("PortfolioAgent", *args, **kwargs)
        self.balance: float = settings.initial_balance
        self.positions: dict[str, float] = {}
        self.trade_history: list[dict[str, Any]] = []
        self.average_costs: dict[str, float] = {}
        self.last_trade_pnl: float | None = None

    def handle_order_executed(self, event: Event) -> None:
        symbol = str(event.payload["symbol"])
        side = str(event.payload["side"])
        qty = float(event.payload["qty"])
        fill_price = float(event.payload["fill_price"])
        self.last_trade_pnl = None

        if side == "BUY":
            previous_qty = float(self.positions.get(symbol, 0.0))
            previous_cost = float(self.average_costs.get(symbol, 0.0))
            new_qty = previous_qty + qty
            self.balance -= qty * fill_price
            if new_qty > 0:
                self.average_costs[symbol] = ((previous_qty * previous_cost) + (qty * fill_price)) / new_qty
            self.positions[symbol] = new_qty
        else:
            current_qty = float(self.positions.get(symbol, 0.0))
            average_cost = float(self.average_costs.get(symbol, fill_price))
            sell_qty = min(current_qty, qty)
            self.balance += sell_qty * fill_price
            remaining_qty = current_qty - sell_qty
            self.last_trade_pnl = (fill_price - average_cost) * sell_qty
            if remaining_qty > 0:
                self.positions[symbol] = remaining_qty
            else:
                self.positions.pop(symbol, None)
                self.average_costs.pop(symbol, None)

        self.trade_history.append(dict(event.payload))
        self.queue_context({"last_trade_pnl": self.last_trade_pnl})
        self.execute_loop(symbol, event.run_id)

    def plan(self, state: AgentState) -> dict[str, Any]:
        return {
            "tool_name": "get_portfolio",
            "parameters": {"balance": self.balance, "positions": self.positions},
            "reason": f"Value portfolio after trade in {state.task}",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def on_complete(self, state: AgentState) -> None:
        portfolio = dict(state.context["last_output"])
        self.bus.publish(
            Event(
                event_type=EventType.PORTFOLIO_UPDATED,
                source_agent=self.name,
                payload={
                    "balance": portfolio["balance"],
                    "positions": portfolio["positions"],
                    "total_value": portfolio["total_value"],
                    "last_trade_pnl": state.context.get("last_trade_pnl"),
                },
                run_id=state.run_id,
            )
        )
        self.logger.info(
            "portfolio balance=%.2f total_value=%.2f positions=%s pnl=%s",
            float(portfolio["balance"]),
            float(portfolio["total_value"]),
            portfolio["positions"],
            state.context.get("last_trade_pnl"),
        )
        state.status = "completed"
