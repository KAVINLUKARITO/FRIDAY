"""# FILE: aiworker/monitor/status.py — Real system health checks via psutil."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    import psutil
except Exception:  # pragma: no cover - exercised by import-time environments
    psutil = None


@dataclass(frozen=True)
class SystemStatus:
    """Immutable snapshot of host resource usage."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_usage_percent: float = 0.0

    @property
    def is_healthy(self) -> bool:
        return (
            self.cpu_percent < 90.0
            and self.memory_percent < 90.0
            and self.disk_usage_percent < 95.0
        )

    def to_dict(self) -> dict[str, float | bool]:
        return {
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_usage_percent": self.disk_usage_percent,
            "is_healthy": self.is_healthy,
        }


def get_system_status(cpu_interval: Optional[float] = 1.0) -> SystemStatus:
    """Return live system metrics and fail open if collection breaks."""
    try:
        if psutil is None:
            return SystemStatus()
        return SystemStatus(
            cpu_percent=psutil.cpu_percent(interval=cpu_interval),
            memory_percent=psutil.virtual_memory().percent,
            disk_usage_percent=psutil.disk_usage("/").percent,
        )
    except Exception:
        return SystemStatus()
