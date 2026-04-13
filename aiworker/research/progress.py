"""Shared research progress tracker for dashboard telemetry."""

from __future__ import annotations

import threading


class ResearchProgressTracker:
    """Tracks research task totals and completions for live dashboard progress."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._research_tasks_total = 0
        self._research_tasks_completed = 0

    def reset(self) -> None:
        with self._lock:
            self._research_tasks_total = 0
            self._research_tasks_completed = 0

    def start_run(self, total: int = 0) -> None:
        with self._lock:
            self._research_tasks_total = max(0, int(total))
            self._research_tasks_completed = 0

    def set_total(self, total: int) -> None:
        with self._lock:
            self._research_tasks_total = max(0, int(total))
            self._research_tasks_completed = min(
                self._research_tasks_completed,
                self._research_tasks_total,
            )

    def record_completed(self, count: int = 1) -> None:
        with self._lock:
            if self._research_tasks_total <= 0:
                self._research_tasks_total = max(0, int(count))
            self._research_tasks_completed = min(
                self._research_tasks_total,
                self._research_tasks_completed + max(0, int(count)),
            )

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            total = self._research_tasks_total
            completed = min(self._research_tasks_completed, total)
            progress = (completed / total) if total else 0.0
            return {
                "research_tasks_total": total,
                "research_tasks_completed": completed,
                "research_progress": round(progress, 4),
            }

    def get_research_progress(self) -> float:
        return float(self.snapshot()["research_progress"])


research_progress = ResearchProgressTracker()


def get_research_progress() -> float:
    return research_progress.get_research_progress()


def get_research_status() -> dict[str, int | float]:
    return research_progress.snapshot()
