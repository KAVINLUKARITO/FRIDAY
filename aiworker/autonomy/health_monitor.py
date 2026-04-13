"""Health monitor — aggregates system health from subsystem checks."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    healthy: bool
    reason: str


@dataclass
class HealthReport:
    checks: List[HealthCheckResult] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(c.healthy for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "checks": [{"name": c.name, "healthy": c.healthy, "reason": c.reason} for c in self.checks],
        }


class HealthMonitor:
    def __init__(self) -> None:
        self._checks: Dict[str, Callable[[], HealthCheckResult]] = {}

    def register(self, name: str, fn: Callable[[], HealthCheckResult]) -> None:
        self._checks[name] = fn

    def run(self) -> HealthReport:
        results = []
        for name, fn in self._checks.items():
            try:
                result = fn()
            except Exception as exc:
                result = HealthCheckResult(name=name, healthy=False, reason=f"Exception: {exc}")
            results.append(result)
        return HealthReport(checks=results)

    def is_healthy(self) -> bool:
        return self.run().healthy
