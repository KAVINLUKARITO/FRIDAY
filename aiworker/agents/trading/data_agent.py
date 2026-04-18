from __future__ import annotations

import threading
import time
from typing import Any

from agents.base_agent import AgentState, BaseAgent
from aiworker.message_bus import Event, EventType
from aiworker.verifier import VerificationStatus
from config import settings


class DataAgent(BaseAgent):
    """Polling market data agent."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("DataAgent", *args, **kwargs)
        self.shutdown_event = threading.Event()
        self.price_history: dict[str, list[float]] = {symbol: [] for symbol in settings.trading_symbols}
        self._step_counters: dict[str, int] = {symbol: 1 for symbol in settings.trading_symbols}

    def handle_shutdown(self, event: Event) -> None:
        if event.run_id:
            self.shutdown_event.set()

    def plan(self, state: AgentState) -> dict[str, Any]:
        return {
            "tool_name": "get_market_data",
            "parameters": {"symbol": state.task},
            "reason": f"Fetch market data for {state.task}",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def poll_market_data(self, run_id: str) -> None:
        self.shutdown_event.clear()
        while not self.shutdown_event.is_set():
            for symbol in settings.trading_symbols:
                if self.shutdown_event.is_set():
                    break
                state = AgentState(
                    run_id=run_id,
                    agent_name=self.name,
                    task=symbol,
                    step_number=self._step_counters[symbol],
                    context={"symbol": symbol},
                )
                try:
                    verification = self.run_step(state)
                    if verification.status.value == VerificationStatus.SUCCESS.value:
                        market_data = state.context["last_output"]
                        history = self.price_history.setdefault(symbol, [])
                        history.append(float(market_data["close"]))
                        self.price_history[symbol] = history[-100:]
                        self.bus.publish(
                            Event(
                                event_type=EventType.MARKET_DATA_UPDATED,
                                source_agent=self.name,
                                payload={
                                    "symbol": symbol,
                                    "data": market_data,
                                    "price_history": list(self.price_history[symbol]),
                                },
                                run_id=run_id,
                            )
                        )
                    self._step_counters[symbol] += 1
                except Exception as exc:
                    self.logger.exception("market polling failed for %s: %s", symbol, exc)
            if not self.shutdown_event.is_set():
                time.sleep(settings.poll_interval_seconds)
