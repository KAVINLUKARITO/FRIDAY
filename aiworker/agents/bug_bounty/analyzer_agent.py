from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.base_agent import AgentState, BaseAgent
from config import settings
from message_bus import Event, EventType
from tools import safe_resolve


class AnalyzerAgent(BaseAgent):
    """Analyze scan results and classify severity."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("AnalyzerAgent", *args, **kwargs)

    def total_steps(self, state: AgentState) -> int:
        return 2

    def handle_scan_complete(self, event: Event) -> None:
        self.queue_context(
            {
                "target": event.payload["target"],
                "scan_payload": event.payload,
            }
        )
        self.execute_loop(event.payload["target"], event.run_id)

    def plan(self, state: AgentState) -> dict[str, Any]:
        workspace = settings.workspace_dir.resolve()
        if state.step_number == 1:
            scan_path = safe_resolve(workspace, f"scan_result_{state.run_id}.json")
            scan_path.parent.mkdir(parents=True, exist_ok=True)
            scan_path.write_text(
                json.dumps(state.context["scan_payload"], indent=2),
                encoding="utf-8",
            )
            state.context["scan_result_path"] = scan_path.relative_to(workspace).as_posix()
            return {
                "tool_name": "read_file",
                "parameters": {"path": state.context["scan_result_path"]},
                "reason": "Read back the stored scan payload for analysis",
                "step_number": state.step_number,
                "agent_name": self.name,
            }

        findings = self._classify_findings(state)
        state.context["findings"] = findings
        return {
            "tool_name": "write_file",
            "parameters": {
                "path": f"analysis_result_{state.run_id}.json",
                "content": json.dumps({"findings": findings}, indent=2),
            },
            "reason": "Persist severity-classified findings",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def on_step_verified(self, state: AgentState, action: Any, execution_result: Any, verification_result: Any) -> None:
        super().on_step_verified(state, action, execution_result, verification_result)
        if verification_result.status.value == "SUCCESS" and state.step_number == 1:
            state.context["scan_payload_readback"] = json.loads(execution_result.output)

    def on_complete(self, state: AgentState) -> None:
        self.bus.publish(
            Event(
                event_type=EventType.ANALYSIS_COMPLETE,
                source_agent=self.name,
                payload={
                    "target": state.context["target"],
                    "findings": state.context.get("findings", []),
                },
                run_id=state.run_id,
            )
        )
        state.status = "completed"

    def _classify_findings(self, state: AgentState) -> list[dict[str, Any]]:
        payload = dict(state.context.get("scan_payload_readback", state.context["scan_payload"]))
        header_findings = payload.get("header_findings", {})
        missing_headers = list(header_findings.get("missing", []))
        sqli_result = payload.get("sqli_result", {})
        xss_result = payload.get("xss_result", {})
        findings: list[dict[str, Any]] = []

        if sqli_result.get("vulnerable"):
            findings.append(
                {
                    "type": "SQL Injection",
                    "severity": "CRITICAL",
                    "detail": sqli_result.get("evidence", ""),
                }
            )
        if xss_result.get("vulnerable"):
            findings.append(
                {
                    "type": "Cross-Site Scripting",
                    "severity": "CRITICAL",
                    "detail": xss_result.get("evidence", ""),
                }
            )

        if "Content-Security-Policy" in missing_headers and "Strict-Transport-Security" in missing_headers:
            findings.append(
                {
                    "type": "Missing CSP and HSTS Headers",
                    "severity": "HIGH",
                    "detail": ", ".join(missing_headers),
                }
            )
        elif missing_headers:
            for header in missing_headers:
                findings.append(
                    {
                        "type": f"Missing {header} Header",
                        "severity": "MEDIUM",
                        "detail": header,
                    }
                )

        if not findings:
            findings.append(
                {
                    "type": "No significant findings",
                    "severity": "LOW",
                    "detail": "All headers present and no simulated vulnerabilities detected",
                }
            )

        return findings
