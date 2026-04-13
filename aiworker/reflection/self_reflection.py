"""Self-reflection engine for assessing failures and weak skills."""

from __future__ import annotations

from collections import Counter
import threading
from typing import Any, Iterable, Mapping


class SelfReflectionEngine:
    """Captures reflective summaries used to adjust internal policies."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_report: dict[str, Any] = {
            "failures_analyzed": 0,
            "weak_skills": (),
            "policy_adjustments": {},
            "dominant_failure_mode": "none",
        }

    def analyze_failures(self, attempts: Iterable[Any]) -> dict[str, Any]:
        failures = [getattr(attempt, "outcome", "unknown") for attempt in attempts if getattr(attempt, "outcome", "") != "success"]
        dominant = Counter(failures).most_common(1)[0][0] if failures else "none"
        return {
            "failures_analyzed": len(failures),
            "dominant_failure_mode": dominant,
        }

    def detect_weak_skills(self, skill_summary: Mapping[str, float]) -> tuple[str, ...]:
        weak = [name for name, mastery in skill_summary.items() if float(mastery) < 0.55]
        return tuple(sorted(weak))

    def adjust_internal_policies(
        self,
        failure_report: Mapping[str, Any],
        weak_skills: Iterable[str],
        current_policy: Mapping[str, bool] | None = None,
    ) -> dict[str, Any]:
        policy = dict(current_policy or {})
        dominant_failure_mode = str(failure_report.get("dominant_failure_mode", "none"))
        if dominant_failure_mode in {"sandbox_failed", "validation_failed"}:
            policy["read_only"] = True
        if tuple(weak_skills):
            policy["auto_apply"] = False
        return policy

    def reflect(
        self,
        *,
        attempts: Iterable[Any],
        skill_summary: Mapping[str, float],
        current_policy: Mapping[str, bool] | None = None,
    ) -> dict[str, Any]:
        failure_report = self.analyze_failures(attempts)
        weak_skills = self.detect_weak_skills(skill_summary)
        policy_adjustments = self.adjust_internal_policies(
            failure_report,
            weak_skills,
            current_policy=current_policy,
        )
        report = {
            **failure_report,
            "weak_skills": weak_skills,
            "policy_adjustments": policy_adjustments,
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
                "failures_analyzed": 0,
                "weak_skills": (),
                "policy_adjustments": {},
                "dominant_failure_mode": "none",
            }


self_reflection_engine = SelfReflectionEngine()
