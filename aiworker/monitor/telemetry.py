"""Shared telemetry store for the AIWorker monitoring dashboard."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any

from aiworker import __version__
from aiworker.learning.skill_store import SkillRepository
from aiworker.monitor.status import get_system_status
from aiworker.runtime.state import read_runtime_status


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


@dataclass(frozen=True)
class PolicyState:
    read_only: bool = False
    admin_mode: bool = True
    auto_apply: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "read_only": self.read_only,
            "admin_mode": self.admin_mode,
            "auto_apply": self.auto_apply,
        }


class TelemetryStore:
    """In-memory telemetry registry shared by the CLI and dashboard."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started_at = time.monotonic()
        self._request_times: deque[float] = deque()
        self._error_times: deque[datetime] = deque()
        self._patch_outcomes: deque[bool] = deque(maxlen=500)
        self._debug_events: deque[dict[str, Any]] = deque(maxlen=200)
        self._event_counts: dict[str, int] = {}
        self._loop_state = "idle"
        self._latest_confidence = 0.0
        self._llm_calls = 0
        self._token_usage = 0
        self._autonomy_iterations = 0
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._sandbox_failures = 0
        self._last_patch_time: str | None = None
        self._last_error: str | None = None
        self._policy = PolicyState()
        self._skill_repository: SkillRepository | None = None
        self._runtime_state = read_runtime_status()
        self._pipeline: tuple[str, ...] = (
            "GOAL",
            "PLAN",
            "RESEARCH",
            "CODE",
            "TEST",
            "EVALUATE",
            "LEARN",
            "IMPROVE SYSTEM",
        )
        self._current_stage = "idle"

    def _prune(self, now: datetime | None = None) -> None:
        current = now or _utcnow()
        minute_ago = current.timestamp() - 60
        while self._request_times and self._request_times[0] < minute_ago:
            self._request_times.popleft()

        errors_cutoff = current - timedelta(hours=24)
        while self._error_times and self._error_times[0] < errors_cutoff:
            self._error_times.popleft()

    def record(self, event: str, **metadata: Any) -> None:
        with self._lock:
            now = _utcnow()
            self._prune(now)
            self._event_counts[event] = self._event_counts.get(event, 0) + 1

            if event in {"api_request", "request"}:
                self._request_times.append(now.timestamp())
            if event in {"error", "sandbox_failure"}:
                self._error_times.append(now)
                self._last_error = str(metadata.get("detail", event))
            if event == "loop_iteration":
                self._autonomy_iterations += 1
                self._loop_state = str(metadata.get("loop_state", "running"))
            elif event == "loop_started":
                self._loop_state = "running"
            elif event == "task_completed":
                self._tasks_completed += 1
            elif event == "task_failed":
                self._tasks_failed += 1
            elif event in {"loop_completed", "loop_stopped"}:
                self._loop_state = str(metadata.get("loop_state", "idle"))
            elif event == "loop_paused":
                self._loop_state = "paused"
            elif event == "patch_proposed":
                self._last_patch_time = _utcnow_iso()
            elif event == "patch_applied":
                self._patch_outcomes.append(True)
                self._last_patch_time = _utcnow_iso()
            elif event in {"patch_failed", "sandbox_failure"}:
                self._patch_outcomes.append(False)
            elif event == "sandbox_failure":
                self._sandbox_failures += 1

            confidence = metadata.get("confidence")
            if confidence is not None:
                try:
                    self._latest_confidence = max(0.0, min(1.0, float(confidence)))
                except (TypeError, ValueError):
                    pass

            tokens = metadata.get("tokens")
            if tokens is not None:
                try:
                    self._token_usage += max(0, int(tokens))
                except (TypeError, ValueError):
                    pass

    def record_request(self) -> None:
        self.record("api_request")

    def record_error(self, detail: str) -> None:
        self.record("error", detail=detail)

    def record_llm_call(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        confidence: float | None = None,
        model: str | None = None,
    ) -> None:
        del model
        with self._lock:
            self._llm_calls += 1
        self.record(
            "llm_call",
            tokens=max(0, int(prompt_tokens)) + max(0, int(completion_tokens)),
            confidence=confidence,
        )

    def record_debug_stage(
        self,
        stage: str,
        *,
        root_cause: str = "",
        fix_proposal: str = "",
        confidence: float | None = None,
        validation_result: str = "pending",
        detail: str = "",
    ) -> dict[str, Any]:
        event = {
            "timestamp": _utcnow_iso(),
            "stage": stage,
            "root_cause": root_cause,
            "fix_proposal": fix_proposal,
            "confidence": round(float(confidence), 4) if confidence is not None else None,
            "validation_result": validation_result,
            "detail": detail,
        }
        with self._lock:
            self._debug_events.append(event)
            if confidence is not None:
                self._latest_confidence = max(0.0, min(1.0, float(confidence)))
        return event

    def set_loop_state(self, state: str) -> None:
        with self._lock:
            self._loop_state = state

    def set_current_stage(self, stage: str) -> None:
        with self._lock:
            self._current_stage = stage

    def update_runtime_state(
        self,
        *,
        running: bool | None = None,
        paused: bool | None = None,
        iteration_count: int | None = None,
        last_goal: str | None = None,
        last_action: str | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = dict(self._runtime_state)
            if running is not None:
                state["running"] = bool(running)
            if paused is not None:
                state["paused"] = bool(paused)
            if iteration_count is not None:
                state["iteration"] = max(0, int(iteration_count))
            if last_goal is not None:
                state["goal"] = str(last_goal)
            if last_action is not None:
                state["last_action"] = str(last_action)
            if last_error is not None:
                state["last_error"] = last_error
            self._runtime_state = state
            return dict(self._runtime_state)

    def attach_skill_repository(self, repository: SkillRepository | None) -> None:
        with self._lock:
            self._skill_repository = repository

    def policy_state(self) -> dict[str, bool]:
        with self._lock:
            return self._policy.to_dict()

    def reset(self) -> None:
        with self._lock:
            self._request_times.clear()
            self._error_times.clear()
            self._patch_outcomes.clear()
            self._debug_events.clear()
            self._event_counts.clear()
            self._loop_state = "idle"
            self._latest_confidence = 0.0
            self._llm_calls = 0
            self._token_usage = 0
            self._autonomy_iterations = 0
            self._tasks_completed = 0
            self._tasks_failed = 0
            self._sandbox_failures = 0
            self._last_patch_time = None
            self._last_error = None
            self._policy = PolicyState()
            self._skill_repository = None
            self._runtime_state = read_runtime_status()
            self._current_stage = "idle"

    def update_policy(
        self,
        *,
        read_only: bool | None = None,
        admin_mode: bool | None = None,
        auto_apply: bool | None = None,
    ) -> dict[str, bool]:
        with self._lock:
            self._policy = PolicyState(
                read_only=self._policy.read_only if read_only is None else bool(read_only),
                admin_mode=self._policy.admin_mode if admin_mode is None else bool(admin_mode),
                auto_apply=self._policy.auto_apply if auto_apply is None else bool(auto_apply),
            )
            return self._policy.to_dict()

    def metrics_payload(self) -> dict[str, Any]:
        with self._lock:
            self._prune()
            host = get_system_status(cpu_interval=None)
            skill_summary = (
                self._skill_repository.get_skill_summary()
                if self._skill_repository is not None
                else {"skills": {}, "learning_progress": 0.0}
            )
            from aiworker.research.progress import get_research_status
            from aiworker.agents.manager import agent_manager
            from aiworker.knowledge.knowledge_graph import knowledge_graph
            from aiworker.meta_learning.meta_optimizer import meta_optimizer
            from aiworker.monitor.patch_history import patch_history
            from aiworker.reflection.self_reflection import self_reflection_engine
            from aiworker.self_modify.self_upgrade_engine import self_upgrade_engine
            from aiworker.tools.tool_registry import tool_registry
            from aiworker.world_model.world_state import get_world_state

            research_status = get_research_status()
            runtime_status = {**dict(self._runtime_state), **read_runtime_status()}
            world_state = get_world_state()
            knowledge_snapshot = knowledge_graph.snapshot()
            agent_activity = agent_manager.snapshot()
            meta_learning = meta_optimizer.snapshot()
            reflection = self_reflection_engine.snapshot()
            tool_snapshot = tool_registry.snapshot()
            self_improvement = self_upgrade_engine.snapshot()
            patch_events = patch_history.list_events()
            total_patches = len(self._patch_outcomes)
            patch_success_rate = (
                (sum(1 for outcome in self._patch_outcomes if outcome) / total_patches) * 100.0
                if total_patches
                else 0.0
            )
            return {
                "cpu": round(host.cpu_percent, 2),
                "memory": round(host.memory_percent, 2),
                "ai_confidence": round(self._latest_confidence, 4),
                "requests_per_min": len(self._request_times),
                "errors_24h": len(self._error_times),
                "patch_success_rate": round(patch_success_rate, 2),
                "loop_state": self._loop_state,
                "current_stage": self._current_stage,
                "loop_pipeline": list(self._pipeline),
                "skills_mastery": skill_summary["skills"],
                "skills": skill_summary["skills"],
                "learning_progress": skill_summary["learning_progress"],
                "research_progress": research_status["research_progress"],
                "research_tasks_total": research_status["research_tasks_total"],
                "research_tasks_completed": research_status["research_tasks_completed"],
                "runtime_status": runtime_status,
                "runtime_running": runtime_status["running"],
                "runtime_paused": runtime_status["paused"],
                "runtime_iteration": runtime_status["iteration"],
                "active_goal": runtime_status["goal"],
                "last_action": runtime_status["last_action"],
                "world_model": world_state,
                "agent_activity": agent_activity,
                "meta_learning": meta_learning,
                "reflection": reflection,
                "knowledge_graph": knowledge_snapshot["counts"],
                "tool_learning": tool_snapshot,
                "self_improvement": self_improvement,
                "patch_lifecycle": {
                    "total_events": len(patch_events),
                    "latest_patch": patch_events[0] if patch_events else None,
                },
                "loop_iterations": self._autonomy_iterations,
                "tasks_completed": self._tasks_completed,
                "tasks_failed": self._tasks_failed,
                "llm_calls": self._llm_calls,
                "token_usage": self._token_usage,
                "autonomy_loop_iterations": self._autonomy_iterations,
                "sandbox_failures": self._sandbox_failures,
                "errors_per_hour": round(len(self._error_times) / 24.0, 2),
                "health_monitor": host.to_dict(),
                "policy": self._policy.to_dict(),
                "last_error": self._last_error,
            }

    def system_status_payload(self) -> dict[str, Any]:
        metrics = self.metrics_payload()
        debug_worker_status = "active" if self._debug_events else "idle"
        return {
            "uptime": round(time.monotonic() - self._started_at, 2),
            "version": __version__,
            "autonomy_loop_active": metrics["loop_state"] == "running",
            "current_stage": metrics["current_stage"],
            "runtime": metrics["runtime_status"],
            "debug_worker_status": debug_worker_status,
            "last_patch_time": self._last_patch_time,
            "read_only_mode": metrics["policy"]["read_only"],
            "admin_mode": metrics["policy"]["admin_mode"],
            "auto_apply_policy": metrics["policy"]["auto_apply"],
        }

    def loop_state_payload(self) -> dict[str, Any]:
        with self._lock:
            latest_debug = self._debug_events[-1] if self._debug_events else None
            return {
                "loop_state": self._loop_state,
                "active": self._loop_state == "running",
                "iterations": self._autonomy_iterations,
                "current_stage": self._current_stage,
                "runtime": {**dict(self._runtime_state), **read_runtime_status()},
                "last_debug_event": latest_debug,
                "pipeline": list(self._pipeline),
            }

    def debug_stream_payload(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._debug_events)

    def runtime_payload(self) -> dict[str, Any]:
        with self._lock:
            return {**dict(self._runtime_state), **read_runtime_status()}


telemetry = TelemetryStore()
