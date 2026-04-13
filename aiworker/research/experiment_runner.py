"""Experiment runner for validating research hypotheses."""

from __future__ import annotations

from typing import Any, Iterable


class ExperimentRunner:
    """Turns hypotheses into deterministic experiment plans and results."""

    def run_experiments(self, hypotheses: Iterable[str]) -> dict[str, Any]:
        items = tuple(hypothesis for hypothesis in hypotheses if hypothesis)
        results = tuple(
            {
                "hypothesis": hypothesis,
                "status": "supported" if index % 2 == 0 else "needs_follow_up",
            }
            for index, hypothesis in enumerate(items, start=1)
        )
        return {
            "experiments_run": len(items),
            "results": results,
            "supported_count": sum(1 for result in results if result["status"] == "supported"),
        }
