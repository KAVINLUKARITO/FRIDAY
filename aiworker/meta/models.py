"""Data models for meta-reasoning and model selection — Phase 4."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"       # < 5 lines, low risk, well-known pattern
    SIMPLE = "simple"         # small change, low risk
    MODERATE = "moderate"     # multi-step, medium risk
    COMPLEX = "complex"       # architectural, high risk
    CRITICAL = "critical"     # touches core, requires best model


@dataclass(frozen=True)
class ModelProfile:
    """Profile of a candidate model for task routing."""
    model_id: str
    display_name: str
    max_complexity: TaskComplexity
    cost_rank: int            # 1=cheapest, higher=more expensive
    speed_rank: int           # 1=fastest
    quality_rank: int         # 1=highest quality
    supports_code: bool = True

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "max_complexity": self.max_complexity.value,
            "cost_rank": self.cost_rank,
            "speed_rank": self.speed_rank,
            "quality_rank": self.quality_rank,
        }


@dataclass(frozen=True)
class SelectionResult:
    """Result of model selection for a task."""
    task_id: str
    complexity: TaskComplexity
    selected_model: ModelProfile
    reason: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "complexity": self.complexity.value,
            "selected_model": self.selected_model.to_dict(),
            "reason": self.reason,
            "confidence": self.confidence,
        }
