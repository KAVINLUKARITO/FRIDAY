from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agents.base_agent import AgentState, BaseAgent
from aiworker.message_bus import Event, EventType
from config import settings


class ReporterAgent(BaseAgent):
    """Generate and persist a structured bug bounty report."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("ReporterAgent", *args, **kwargs)

    def handle_exploit_validated(self, event: Event) -> None:
        self.queue_context(
            {
                "target": event.payload["target"],
                "validated_findings": list(event.payload.get("validated_findings", [])),
            }
        )
        self.execute_loop(event.payload["target"], event.run_id)

    def plan(self, state: AgentState) -> dict[str, Any]:
        findings = state.context.get("validated_findings", [])
        report = self._build_report(state.run_id, state.context["target"], findings)
        report_path = f"bug_bounty_report_{state.run_id}.json"
        state.context["report_path"] = report_path
        return {
            "tool_name": "write_file",
            "parameters": {"path": report_path, "content": json.dumps(report, indent=2)},
            "reason": "Write structured bug bounty report to workspace",
            "step_number": state.step_number,
            "agent_name": self.name,
        }

    def replan(self, state: AgentState, failure_reason: str) -> dict[str, Any]:
        action = self.plan(state)
        action["reason"] = f"{action['reason']} after failure: {failure_reason}"
        return action

    def on_complete(self, state: AgentState) -> None:
        self.bus.publish(
            Event(
                event_type=EventType.REPORT_READY,
                source_agent=self.name,
                payload={"report_path": state.context["report_path"]},
                run_id=state.run_id,
            )
        )
        state.status = "completed"

    def _build_report(self, run_id: str, target: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
        summary = {
            "total_findings": len(findings),
            "critical": sum(1 for finding in findings if finding.get("severity") == "CRITICAL"),
            "high": sum(1 for finding in findings if finding.get("severity") == "HIGH"),
            "medium": sum(1 for finding in findings if finding.get("severity") == "MEDIUM"),
            "low": sum(1 for finding in findings if finding.get("severity") == "LOW"),
        }
        report_findings: list[dict[str, Any]] = []
        for index, finding in enumerate(findings, start=1):
            finding_type = str(finding.get("type", "Unknown Finding"))
            report_findings.append(
                {
                    "id": index,
                    "type": finding_type,
                    "severity": finding.get("severity", "LOW"),
                    "confirmed": bool(finding.get("confirmed", False)),
                    "evidence": str(finding.get("evidence", "")),
                    "recommendation": self._recommendation_for(finding_type),
                }
            )
        return {
            "run_id": run_id,
            "target": target,
            "scan_timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "findings": report_findings,
            "safe_mode": settings.safe_test_mode,
        }

    def _recommendation_for(self, finding_type: str) -> str:
        recommendations = {
            "Missing CSP and HSTS Headers": "Configure Content-Security-Policy and Strict-Transport-Security headers.",
            "SQL Injection": "Use parameterized queries and validate all user-controlled input.",
            "Cross-Site Scripting": "Escape untrusted output and enforce a strict content security policy.",
        }
        if finding_type.startswith("Missing "):
            return "Add the missing security header and verify it on every response."
        return recommendations.get(finding_type, "Review the finding, validate the root cause, and remediate safely.")
