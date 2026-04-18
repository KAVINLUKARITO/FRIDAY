from __future__ import annotations

from typing import Any

from agents.base_agent import AgentState, BaseAgent
from aiworker.message_bus import Event, EventType
from config import settings


class StrategyAgent(BaseAgent):
    """Moving-average crossover strategy agent."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("StrategyAgent", *args, **kwargs)

    def handle_market_data(self, event: Event) -> None:
        self.queue_context(
            {
                "symbol": event.payload["symbol"],
                "prices": list(event.payload.get("price_history", [])),
                "current_price": float(event.payload["data"]["close"]),
            }
        )
        self.execute_loop(event.payload["symbol"], event.run_id)

    def plan(self, state: AgentState) -> dict[str, Any]:
        return {
            "tool_name": "calculate_indicators",
            "parameters": {
                "prices": list(state.context["prices"]),
                "short_window": settings.ma_short,
                "long_window": settings.ma_long,
            },
            "reason": f"Calculate moving-average signal for {state.task}",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def on_complete(self, state: AgentState) -> None:
        indicators = dict(state.context.get("last_output", {}))
        signal = indicators.get("signal", "HOLD")
        if signal in {"BUY", "SELL"}:
            self.bus.publish(
                Event(
                    event_type=EventType.SIGNAL_GENERATED,
                    source_agent=self.name,
                    payload={
                        "symbol": state.context["symbol"],
                        "signal": signal,
                        "short_ma": indicators.get("short_ma"),
                        "long_ma": indicators.get("long_ma"),
                        "current_price": state.context["current_price"],
                    },
                    run_id=state.run_id,
                )
            )
        else:
            self.logger.info("signal HOLD for %s; skipping publish", state.context["symbol"])
        state.status = "completed"
