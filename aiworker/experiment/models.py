"""Data models for self-evaluation and experiment tracking — Phase 5."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ExperimentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class BenchmarkTask:
    """A deterministic coding benchmark with an expected outcome."""
    benchmark_id: str
    name: str
    description: str
    skill_area: str
    input_spec: str      # what the implementation must do
    pass_criteria: str   # how to judge success
    difficulty: str      # beginner / intermediate / advanced
    max_score: float = 1.0


@dataclass(frozen=True)
class BenchmarkResult:
    benchmark_id: str
    attempt_id: str
    score: float         # [0, max_score]
    passed: bool
    notes: str
    duration_seconds: float

    def to_dict(self) -> dict:
        return {
            "benchmark_id": self.benchmark_id,
            "attempt_id": self.attempt_id,
            "score": self.score,
            "passed": self.passed,
            "notes": self.notes,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass(frozen=True)
class Variant:
    """One arm of an A/B experiment."""
    variant_id: str
    name: str
    strategy: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Experiment:
    """A controlled A/B experiment comparing two strategies."""
    experiment_id: str
    name: str
    hypothesis: str
    variant_a: Variant
    variant_b: Variant
    status: ExperimentStatus = ExperimentStatus.PENDING
    results_a: List[BenchmarkResult] = field(default_factory=list)
    results_b: List[BenchmarkResult] = field(default_factory=list)
    winner: Optional[str] = None      # "a" | "b" | "tie" | None

    def mean_score(self, results: List[BenchmarkResult]) -> float:
        if not results:
            return 0.0
        return sum(r.score for r in results) / len(results)

    def conclude(self) -> str:
        """Determine winner based on mean scores. Deterministic."""
        score_a = self.mean_score(self.results_a)
        score_b = self.mean_score(self.results_b)
        if abs(score_a - score_b) < 0.01:
            self.winner = "tie"
        elif score_a > score_b:
            self.winner = "a"
        else:
            self.winner = "b"
        self.status = ExperimentStatus.COMPLETED
        return self.winner

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "status": self.status.value,
            "variant_a": self.variant_a.variant_id,
            "variant_b": self.variant_b.variant_id,
            "score_a": round(self.mean_score(self.results_a), 4),
            "score_b": round(self.mean_score(self.results_b), 4),
            "winner": self.winner,
            "results_a_count": len(self.results_a),
            "results_b_count": len(self.results_b),
        }
