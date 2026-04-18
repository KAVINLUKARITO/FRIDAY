from __future__ import annotations

from datetime import datetime
from typing import Any

from agents.base_agent import AgentState, BaseAgent
from aiworker.message_bus import Event, EventType
from aiworker.storage import TradeRecord


class ExecutionAgent(BaseAgent):
    """Trade execution agent for approved paper trades."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("ExecutionAgent", *args, **kwargs)

    def handle_risk_approved(self, event: Event) -> None:
        self.queue_context(dict(event.payload))
        self.execute_loop(event.payload["symbol"], event.run_id)

    def plan(self, state: AgentState) -> dict[str, Any]:
        return {
            "tool_name": "place_order",
            "parameters": {
                "symbol": state.context["symbol"],
                "side": state.context["side"],
                "qty": float(state.context["qty"]),
                "price": float(state.context["price"]),
                "mode": "paper",
            },
            "reason": f"Place paper order for {state.task}",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def on_complete(self, state: AgentState) -> None:
        order = dict(state.context["last_output"])
        self.storage.save_trade(
            TradeRecord(
                run_id=state.run_id,
                order_id=order["order_id"],
                symbol=order["symbol"],
                side=order["side"],
                qty=float(order["qty"]),
                price=float(order["price"]),
                fill_price=float(order["fill_price"]),
                timestamp=datetime.fromisoformat(order["timestamp"]),
                pnl=None,
            )
        )
        self.bus.publish(
            Event(
                event_type=EventType.ORDER_EXECUTED,
                source_agent=self.name,
                payload={
                    "order_id": order["order_id"],
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "qty": float(order["qty"]),
                    "fill_price": float(order["fill_price"]),
                    "timestamp": order["timestamp"],
                },
                run_id=state.run_id,
            )
        )
        state.status = "completed"
