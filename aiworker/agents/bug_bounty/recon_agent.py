from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from agents.base_agent import AgentState, BaseAgent
from aiworker.message_bus import Event, EventType


class ReconAgent(BaseAgent):
    """Initial reconnaissance agent for safe local targets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("ReconAgent", *args, **kwargs)

    def total_steps(self, state: AgentState) -> int:
        return 3

    def plan(self, state: AgentState) -> dict[str, Any]:
        target = state.task
        parsed = urlparse(target)
        if state.step_number == 1:
            return {
                "tool_name": "http_request",
                "parameters": {"url": target, "method": "GET"},
                "reason": "Fetch target landing page for reconnaissance",
                "step_number": state.step_number,
                "agent_name": self.name,
            }
        if state.step_number == 2:
            html = str(state.context.get("http_response", {}).get("body", ""))
            return {
                "tool_name": "parse_html",
                "parameters": {"html": html, "selector": "a"},
                "reason": "Extract links discovered during reconnaissance",
                "step_number": state.step_number,
                "agent_name": self.name,
            }
        return {
            "tool_name": "port_scan",
            "parameters": {"host": parsed.hostname or "localhost"},
            "reason": "Scan common localhost ports for exposed services",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        target = state.task
        parsed = urlparse(target)
        if state.step_number == 1:
            return {
                "tool_name": "http_request",
                "parameters": {"url": target, "method": "OPTIONS"},
                "reason": f"Retry reconnaissance request after failure: {failure_reason}",
                "step_number": state.step_number,
                "agent_name": self.name,
            }
        if state.step_number == 2:
            html = str(state.context.get("http_response", {}).get("body", ""))
            return {
                "tool_name": "parse_html",
                "parameters": {"html": html, "selector": "a, form"},
                "reason": f"Retry HTML parsing after failure: {failure_reason}",
                "step_number": state.step_number,
                "agent_name": self.name,
            }
        return {
            "tool_name": "port_scan",
            "parameters": {"host": parsed.hostname or "localhost", "ports": [80, 443, 8080, 8443]},
            "reason": f"Retry port scan after failure: {failure_reason}",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def on_step_verified(self, state: AgentState, action: Any, execution_result: Any, verification_result: Any) -> None:
        super().on_step_verified(state, action, execution_result, verification_result)
        if verification_result.status.value != "SUCCESS":
            return
        if state.step_number == 1:
            state.context["http_response"] = execution_result.output
        elif state.step_number == 2:
            state.context["urls"] = execution_result.output
        elif state.step_number == 3:
            state.context["open_ports"] = execution_result.output.get("open_ports", [])

    def on_complete(self, state: AgentState) -> None:
        payload = {
            "target": state.task,
            "urls": state.context.get("urls", []),
            "open_ports": state.context.get("open_ports", []),
            "response": state.context.get("http_response", {}),
        }
        self.bus.publish(
            Event(
                event_type=EventType.RECON_COMPLETE,
                source_agent=self.name,
                payload=payload,
                run_id=state.run_id,
            )
        )
        state.status = "completed"
