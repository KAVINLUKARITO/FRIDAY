from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from aiworker.pipeline.state import AgentState


class RunMetrics(BaseModel):
    run_id: str
    score: float = Field(ge=0.0, le=1.0)
    steps_completed: int
    steps_planned: int
    retries: int
    replans: int
    terminal_status: str
    duration_seconds: float
    timestamp: datetime


class EvaluationEngine:
    def __init__(self, metrics_path: Path | str = Path("runtime") / "metrics.jsonl") -> None:
        self.metrics_path = Path(metrics_path)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

    def score(self, state: AgentState) -> RunMetrics:
        completion_ratio = state.steps_completed / max(1, state.steps_planned)
        verification_pass_rate = state.verified_successes / max(1, state.total_executions)
        retry_overhead = min(0.5, state.retries * 0.05)
        raw_score = max(0.0, min(1.0, (completion_ratio * 0.6) + (verification_pass_rate * 0.4) - retry_overhead))

        if state.terminal_status == "ABORTED":
            raw_score = min(raw_score, 0.2)
        if state.terminal_status == "STEP_LIMIT_REACHED":
            raw_score = min(raw_score, 0.3)

        completed_at = state.completed_at or datetime.now(timezone.utc)
        metrics = RunMetrics(
            run_id=state.run_id,
            score=round(raw_score, 4),
            steps_completed=state.steps_completed,
            steps_planned=state.steps_planned,
            retries=state.retries,
            replans=state.replans,
            terminal_status=state.terminal_status,
            duration_seconds=max(0.0, (completed_at - state.started_at).total_seconds()),
            timestamp=datetime.now(timezone.utc),
        )
        self._persist(metrics)
        return metrics

    def get_summary(self, last_n: int = 10) -> list[RunMetrics]:
        if not self.metrics_path.exists():
            return []
        lines = self.metrics_path.read_text(encoding="utf-8").splitlines()[-last_n:]
        return [RunMetrics.model_validate(json.loads(line)) for line in lines if line.strip()]

    def _persist(self, metrics: RunMetrics) -> None:
        with self.metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(metrics.model_dump_json() + "\n")
