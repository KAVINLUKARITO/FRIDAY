"""Model selector — routes tasks to the appropriate model — Phase 4.

Deterministic selection based on complexity.
No external calls. Registry is static (in-process config).
"""
from __future__ import annotations
from typing import Dict, List, Optional

from aiworker.meta.models import ModelProfile, SelectionResult, TaskComplexity
from aiworker.meta.task_classifier import classify


# ── Default Model Registry ───────────────────────────────────────────────────
_COMPLEXITY_ORDER = [
    TaskComplexity.TRIVIAL,
    TaskComplexity.SIMPLE,
    TaskComplexity.MODERATE,
    TaskComplexity.COMPLEX,
    TaskComplexity.CRITICAL,
]

DEFAULT_MODELS: List[ModelProfile] = [
    ModelProfile(
        model_id="claude-haiku-4-5",
        display_name="Claude Haiku 4.5",
        max_complexity=TaskComplexity.SIMPLE,
        cost_rank=1,
        speed_rank=1,
        quality_rank=3,
    ),
    ModelProfile(
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        max_complexity=TaskComplexity.COMPLEX,
        cost_rank=2,
        speed_rank=2,
        quality_rank=2,
    ),
    ModelProfile(
        model_id="claude-opus-4-6",
        display_name="Claude Opus 4.6",
        max_complexity=TaskComplexity.CRITICAL,
        cost_rank=3,
        speed_rank=3,
        quality_rank=1,
    ),
]


class ModelSelector:
    """Select the cheapest model that can handle the task complexity.

    Args:
        models: Ordered list of ModelProfile (cheapest first).
    """

    def __init__(self, models: Optional[List[ModelProfile]] = None) -> None:
        self._models = models or list(DEFAULT_MODELS)
        # Sort by cost (ascending) then quality (ascending = cheaper first)
        self._models.sort(key=lambda m: (m.cost_rank, -m.quality_rank))

    def select(
        self,
        task_id: str,
        goal: str,
        risk_level: str = "low",
        plan_complexity: float = 0.0,
        num_files: int = 1,
    ) -> SelectionResult:
        """Select the cheapest capable model for this task.

        Args:
            task_id: Unique task identifier.
            goal: Goal text.
            risk_level: Risk level string.
            plan_complexity: Float [0,1] from planner.
            num_files: Number of files touched.

        Returns:
            :class:`SelectionResult` with chosen model and reason.
        """
        complexity = classify(goal, risk_level, plan_complexity, num_files)
        complexity_rank = _COMPLEXITY_ORDER.index(complexity)

        for model in self._models:
            model_rank = _COMPLEXITY_ORDER.index(model.max_complexity)
            if model_rank >= complexity_rank:
                return SelectionResult(
                    task_id=task_id,
                    complexity=complexity,
                    selected_model=model,
                    reason=(
                        f"Task complexity '{complexity.value}' matched to "
                        f"'{model.display_name}' (cheapest capable model)."
                    ),
                    confidence=1.0 - (model.cost_rank / (len(self._models) + 1)),
                )

        # Fallback: most capable model
        best = max(self._models, key=lambda m: m.quality_rank == 1)
        return SelectionResult(
            task_id=task_id,
            complexity=complexity,
            selected_model=best,
            reason="Fallback to most capable model (no exact match).",
            confidence=0.5,
        )
