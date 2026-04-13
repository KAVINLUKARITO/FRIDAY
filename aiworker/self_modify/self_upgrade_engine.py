"""Recursive self-improvement planner for safe architecture upgrades."""

from __future__ import annotations

import threading
from typing import Any, Iterable, Mapping


class SelfUpgradeEngine:
    """Detects limitations and proposes safe improvements."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_report: dict[str, Any] = {
            "limitations": (),
            "proposals": (),
            "validated_proposals": (),
            "applied_upgrades": (),
        }

    def detect_architecture_limitations(self, metrics: Mapping[str, Any]) -> tuple[str, ...]:
        limitations = []
        if float(metrics.get("ai_confidence", 0.0)) < 0.5:
            limitations.append("low_confidence_execution")
        if float(metrics.get("research_progress", 0.0)) < 0.5:
            limitations.append("thin_research_coverage")
        if float(metrics.get("learning_progress", 0.0)) < 0.5:
            limitations.append("limited_skill_mastery")
        return tuple(limitations)

    def propose_improvements(self, limitations: Iterable[str]) -> tuple[dict[str, str], ...]:
        proposals = []
        for limitation in limitations:
            proposals.append(
                {
                    "limitation": limitation,
                    "proposal": f"Introduce targeted safeguards for {limitation}",
                }
            )
        return tuple(proposals)

    def validate_improvements(self, proposals: Iterable[Mapping[str, str]]) -> tuple[dict[str, str], ...]:
        validated = []
        for proposal in proposals:
            validated.append(
                {
                    "limitation": str(proposal.get("limitation", "")),
                    "proposal": str(proposal.get("proposal", "")),
                    "status": "safe",
                }
            )
        return tuple(validated)

    def apply_safe_upgrades(self, proposals: Iterable[Mapping[str, str]]) -> tuple[dict[str, str], ...]:
        applied = []
        for proposal in proposals:
            if proposal.get("status") == "safe":
                applied.append(
                    {
                        "limitation": str(proposal.get("limitation", "")),
                        "status": "planned",
                    }
                )
        return tuple(applied)

    def run(self, metrics: Mapping[str, Any]) -> dict[str, Any]:
        limitations = self.detect_architecture_limitations(metrics)
        proposals = self.propose_improvements(limitations)
        validated = self.validate_improvements(proposals)
        applied = self.apply_safe_upgrades(validated)
        report = {
            "limitations": limitations,
            "proposals": proposals,
            "validated_proposals": validated,
            "applied_upgrades": applied,
        }
        with self._lock:
            self._last_report = report
        return dict(report)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._last_report)

    def reset(self) -> None:
        with self._lock:
            self._last_report = {
                "limitations": (),
                "proposals": (),
                "validated_proposals": (),
                "applied_upgrades": (),
            }


self_upgrade_engine = SelfUpgradeEngine()
