"""# FILE: aiworker/agent/self_improver.py — Safe self-improvement orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from aiworker.autonomy.models import EvolutionConfig
from aiworker.config import AIWorkerConfig


SELF_IMPROVEMENT_GOALS = [
    ("Add type hints to all public functions", "aiworker/planning/planner.py"),
    ("Increase test coverage to 100%", "aiworker/scoring/calculator.py"),
    ("Add structured logging to all public methods", "aiworker/execution/runner.py"),
    ("Refactor to use dependency injection", "aiworker/orchestration/orchestrator.py"),
    ("Add input validation to all public methods", "aiworker/memory/repository.py"),
]

AIWORKER_SAFE_FILES = (
    "aiworker/planning/planner.py",
    "aiworker/planning/simulator.py",
    "aiworker/scoring/calculator.py",
    "aiworker/scoring/metrics.py",
    "aiworker/memory/repository.py",
    "aiworker/orchestration/orchestrator.py",
    "aiworker/execution/runner.py",
    "aiworker/advisory/advisor.py",
    "aiworker/advisory/prompt_builder.py",
)


@dataclass
class SelfImprover:
    """Run AIWorker against its own safe modules under strict constraints."""

    config: AIWorkerConfig
    controller_factory: Callable[[EvolutionConfig], Any]
    _seen_targets: set[str] = field(default_factory=set)

    def run_improvement_cycle(
        self,
        goal: str,
        target_file: str,
        dry_run: bool = True,
    ) -> Any:
        if target_file not in AIWORKER_SAFE_FILES:
            raise ValueError("target_file is not in AIWORKER_SAFE_FILES")
        if any(target_file.startswith(prefix) for prefix in self.config.self_modify_forbidden):
            raise ValueError("target_file is forbidden for self-modification")

        effective_dry_run = dry_run or target_file not in self._seen_targets
        config = EvolutionConfig(
            goal=goal,
            allowed_files=(target_file,),
            max_attempts=self.config.max_attempts,
            max_failures=self.config.max_failures,
            confidence_threshold=self.config.confidence_threshold,
            max_lines_changed=min(self.config.max_lines_changed, 30),
            tests_required=True,
            risk_level="low",
            dry_run=effective_dry_run,
            sandbox_timeout=self.config.sandbox_timeout,
        )
        controller = self.controller_factory(config)
        result = controller.run()
        self._seen_targets.add(target_file)
        return result

    def run_benchmark_triggered_improvements(
        self,
        evaluator: Any,
    ) -> list[Any]:
        results: list[Any] = []
        evaluations = evaluator.evaluate_all("")
        for skill in evaluations:
            mastery_score = getattr(skill, "mastery_score", 1.0)
            skill_name = str(getattr(skill, "name", "")).lower()
            if mastery_score >= 0.5:
                continue
            for goal, target_file in SELF_IMPROVEMENT_GOALS:
                if skill_name and skill_name in goal.lower():
                    results.append(
                        self.run_improvement_cycle(
                            goal=goal,
                            target_file=target_file,
                            dry_run=True,
                        )
                    )
                    break
        return results
