"""Controlled Autonomy Loop — Phase 1 + Phase 6 integration.

State machine driven iteration over a task queue.
Governance gates EVERY execution:
  - HealthMonitor must pass
  - RateLimiter must allow
  - CircuitBreaker must allow
  - Explicit iteration cap enforced
  - VersionGraph node added after each iteration
  - RollbackEngine detects and recovers from regressions
  - No automatic git commits
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from aiworker.autonomy.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from aiworker.autonomy.health_monitor import HealthMonitor
from aiworker.autonomy.rate_limiter import RateLimiter, RateLimiterConfig
from aiworker.versioning.models import RollbackResult
from aiworker.versioning.rollback_engine import RollbackEngine
from aiworker.versioning.version_graph import VersionGraph


class LoopState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    HALTED = "halted"
    COMPLETED = "completed"


@dataclass(frozen=True)
class IterationResult:
    iteration: int
    task_id: str
    success: bool
    score: float
    score_delta: float
    halt_reason: Optional[str]
    governance_blocked: bool
    duration_seconds: float
    snapshot_id: Optional[str] = None      # VersionGraph node ID
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "task_id": self.task_id,
            "success": self.success,
            "score": self.score,
            "score_delta": self.score_delta,
            "halt_reason": self.halt_reason,
            "governance_blocked": self.governance_blocked,
            "duration_seconds": round(self.duration_seconds, 3),
            "snapshot_id": self.snapshot_id,
            "detail": self.detail,
        }


@dataclass
class LoopConfig:
    max_iterations: int = 50
    min_score_delta: float = -0.1
    breaker_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    limiter_config: RateLimiterConfig = field(default_factory=RateLimiterConfig)
    enable_versioning: bool = True       # toggle version graph integration


@dataclass
class LoopReport:
    state: LoopState
    iterations_run: int
    iterations_succeeded: int
    iterations_failed: int
    governance_blocks: int
    best_score: float
    final_score: float
    results: List[IterationResult] = field(default_factory=list)
    halt_reason: Optional[str] = None
    version_graph: Optional[VersionGraph] = None   # attached if versioning enabled

    def to_dict(self) -> dict:
        d = {
            "state": self.state.value,
            "iterations_run": self.iterations_run,
            "iterations_succeeded": self.iterations_succeeded,
            "iterations_failed": self.iterations_failed,
            "governance_blocks": self.governance_blocks,
            "best_score": self.best_score,
            "final_score": self.final_score,
            "halt_reason": self.halt_reason,
            "results": [r.to_dict() for r in self.results],
        }
        if self.version_graph is not None:
            d["version_graph"] = self.version_graph.to_dict()
        return d


TaskFn = Callable[[str, int], tuple[bool, float, dict]]
TaskProvider = Callable[[int], Optional[str]]


class AutonomyLoop:
    """State machine driving controlled autonomous evolution.

    Args:
        task_provider: Callable(iteration) -> task_id | None.
        task_executor: Callable(task_id, iteration) -> (success, score, detail).
        config: LoopConfig
        health_monitor: Optional HealthMonitor.
        version_graph: Optional pre-existing VersionGraph to attach to.
    """

    def __init__(
        self,
        task_provider: TaskProvider,
        task_executor: TaskFn,
        config: Optional[LoopConfig] = None,
        health_monitor: Optional[HealthMonitor] = None,
        version_graph: Optional[VersionGraph] = None,
    ) -> None:
        self._provider = task_provider
        self._executor = task_executor
        self._config = config or LoopConfig()
        self._health = health_monitor or HealthMonitor()
        self._breaker = CircuitBreaker(self._config.breaker_config)
        self._limiter = RateLimiter(self._config.limiter_config)
        self._state: LoopState = LoopState.IDLE
        self._results: List[IterationResult] = []


        # Version graph — created fresh if not provided and versioning enabled
        if self._config.enable_versioning:
            self._graph: Optional[VersionGraph] = version_graph or VersionGraph()
            self._rollback = RollbackEngine(
                self._graph,
                min_score_delta=self._config.min_score_delta,
            )
        else:
            self._graph = None
            self._rollback = None

    @property
    def state(self) -> LoopState:
        return self._state

    @property
    def version_graph(self) -> Optional[VersionGraph]:
        return self._graph


    def run(self) -> LoopReport:
        """Execute the autonomy loop until completion, halt, or limit."""
        self._state = LoopState.RUNNING
        iterations_run = 0
        iterations_succeeded = 0
        iterations_failed = 0
        governance_blocks = 0
        best_score = 0.0
        current_score = 0.0
        halt_reason: Optional[str] = None

        for i in range(1, self._config.max_iterations + 1):
            # ── Governance Gate ──────────────────────────────────
            blocked, block_reason = self._governance_check()
            if blocked:
                governance_blocks += 1
                self._results.append(IterationResult(
                    iteration=i, task_id="", success=False,
                    score=current_score, score_delta=0.0,
                    halt_reason=block_reason, governance_blocked=True,
                    duration_seconds=0.0,
                ))
                if "circuit" in (block_reason or "").lower():
                    self._state = LoopState.HALTED
                    halt_reason = block_reason
                    break
                continue

            # ── Task Provision ───────────────────────────────────
            task_id = self._provider(i)
            if task_id is None:
                self._state = LoopState.COMPLETED
                break

            # ── Execute ─────────────────────────────────────────
            start = time.monotonic()
            try:
                self._limiter.record()
                success, score, detail = self._executor(task_id, i)
            except Exception as exc:
                success, score, detail = False, current_score, {"error": str(exc)}
            duration = time.monotonic() - start

            # ── Score Delta & Rollback Decision ──────────────────
            score_delta = score - current_score
            rolled_back = False
            snapshot_id: Optional[str] = None

            if score_delta < self._config.min_score_delta:
                score = current_score
                score_delta = 0.0
                success = False
                rolled_back = True
                detail = dict(detail)
                detail["rolled_back"] = True

                # Trigger version graph rollback if enabled
                if self._rollback is not None:
                    rb_result: RollbackResult = self._rollback.rollback_to_last_good()
                    detail["rollback_result"] = rb_result.to_dict()

            # ── Version Graph: record this iteration ─────────────
            if self._graph is not None and not rolled_back:
                node = self._graph.add_node(
                    score=score,
                    metadata={
                        "task_id": task_id,
                        "iteration": i,
                        "success": success,
                        "goal": detail.get("goal", ""),
                    },
                )
                snapshot_id = node.snapshot_id

            # ── Circuit Breaker ──────────────────────────────────
            if success:
                self._breaker.record_success()
                iterations_succeeded += 1
                current_score = score
                if current_score > best_score:
                    best_score = current_score
            else:
                self._breaker.record_failure()
                iterations_failed += 1

            iterations_run += 1
            self._results.append(IterationResult(
                iteration=i,
                task_id=task_id,
                success=success,
                score=current_score,
                score_delta=score_delta,
                halt_reason="score_rollback" if rolled_back else None,
                governance_blocked=False,
                duration_seconds=duration,
                snapshot_id=snapshot_id,
                detail=detail,
            ))

        else:
            if self._state == LoopState.RUNNING:
                self._state = LoopState.HALTED
                halt_reason = f"max_iterations ({self._config.max_iterations}) reached"

        if self._state == LoopState.RUNNING:
            self._state = LoopState.COMPLETED

        return LoopReport(
            state=self._state,
            iterations_run=iterations_run,
            iterations_succeeded=iterations_succeeded,
            iterations_failed=iterations_failed,
            governance_blocks=governance_blocks,
            best_score=best_score,
            final_score=current_score,
            results=list(self._results),
            halt_reason=halt_reason,
            version_graph=self._graph,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------


    def _governance_check(self) -> tuple[bool, Optional[str]]:
        if not self._breaker.allow():
            return True, f"circuit_breaker_{self._breaker.state.value}"
        if not self._limiter.allow():
            return True, "rate_limit_exceeded"
        if not self._health.is_healthy():
            return True, "health_check_failed"
        return False, None


EvolutionLoop = AutonomyLoop
