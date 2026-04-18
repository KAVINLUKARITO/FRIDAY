from __future__ import annotations

from typing import Any

from agents.base_agent import AgentState, BaseAgent
from aiworker.message_bus import Event, EventType


class ScannerAgent(BaseAgent):
    """Scanner agent activated after reconnaissance completes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("ScannerAgent", *args, **kwargs)

    def total_steps(self, state: AgentState) -> int:
        return 3

    def handle_recon_complete(self, event: Event) -> None:
        self.queue_context(
            {
                "target": event.payload["target"],
                "response": event.payload.get("response", {}),
                "urls": event.payload.get("urls", []),
                "open_ports": event.payload.get("open_ports", []),
            }
        )
        self.execute_loop(event.payload["target"], event.run_id)

    def plan(self, state: AgentState) -> dict[str, Any]:
        target = str(state.context["target"])
        if state.step_number == 1:
            return {
                "tool_name": "scan_headers",
                "parameters": {"response": state.context.get("response", {})},
                "reason": "Assess security headers from reconnaissance response",
                "step_number": state.step_number,
                "agent_name": self.name,
            }
        if state.step_number == 2:
            return {
                "tool_name": "check_sql_injection",
                "parameters": {"url": target},
                "reason": "Run safe SQL injection simulation",
                "step_number": state.step_number,
                "agent_name": self.name,
            }
        return {
            "tool_name": "check_xss",
            "parameters": {"url": target},
            "reason": "Run safe XSS simulation",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def on_step_verified(self, state: AgentState, action: Any, execution_result: Any, verification_result: Any) -> None:
        super().on_step_verified(state, action, execution_result, verification_result)
        if verification_result.status.value != "SUCCESS":
            return
        if state.step_number == 1:
            state.context["header_findings"] = execution_result.output
        elif state.step_number == 2:
            state.context["sqli_result"] = execution_result.output
        elif state.step_number == 3:
            state.context["xss_result"] = execution_result.output

    def on_complete(self, state: AgentState) -> None:
        self.bus.publish(
            Event(
                event_type=EventType.SCAN_COMPLETE,
                source_agent=self.name,
                payload={
                    "target": state.context["target"],
                    "header_findings": state.context.get("header_findings", {}),
                    "sqli_result": state.context.get("sqli_result", {}),
                    "xss_result": state.context.get("xss_result", {}),
                },
                run_id=state.run_id,
            )
        )
        state.status = "completed"
