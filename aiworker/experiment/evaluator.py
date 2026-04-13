"""Self-evaluation engine — runs benchmarks and tracks skill progress — Phase 5.

Combines BenchmarkRegistry + SkillRepository + ExperimentTracker
into a unified self-evaluation pipeline.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from aiworker.experiment.benchmark import BenchmarkRegistry, STANDARD_BENCHMARKS
from aiworker.experiment.models import BenchmarkResult, BenchmarkTask
from aiworker.learning.skill_store import SkillDatabase, SkillRepository
from aiworker.learning.models import Skill
from aiworker.monitor.telemetry import telemetry


class SelfEvaluator:
    """Runs benchmarks and updates skill mastery based on results.

    Args:
        registry: BenchmarkRegistry with registered benchmarks.
        skill_db: SkillDatabase for persisting mastery scores.
    """

    def __init__(
        self,
        registry: Optional[BenchmarkRegistry] = None,
        skill_db: Optional[SkillDatabase] = None,
    ) -> None:
        self._registry = registry or BenchmarkRegistry()
        self._skill_db = skill_db or SkillDatabase(":memory:")
        self._skill_repo = SkillRepository(self._skill_db)
        self._skill_db.initialise()
        self._ensure_skills()
        telemetry.attach_skill_repository(self._skill_repo)

    def evaluate_all(self, attempt_code: str) -> List[BenchmarkResult]:
        """Run all standard benchmarks against the submitted code."""
        results = []
        for bm in self._registry.all_benchmarks():
            result = self._registry.evaluate(bm.benchmark_id, attempt_code)
            self._update_skill(bm, result)
            results.append(result)
        return results

    def evaluate_one(
        self, benchmark_id: str, attempt_code: str
    ) -> BenchmarkResult:
        """Run a single benchmark and update corresponding skill."""
        result = self._registry.evaluate(benchmark_id, attempt_code)
        bm = self._registry.get(benchmark_id)
        if bm:
            self._update_skill(bm, result)
        return result

    def skill_summary(self) -> Dict[str, float]:
        """Return a dict of skill_name -> mastery_score."""
        skills = self._skill_repo.get_all_skills()
        return {s.name: s.mastery_score for s in skills}

    def overall_mastery(self) -> float:
        """Mean mastery across all tracked skills. Range [0,1]."""
        skills = self._skill_repo.get_all_skills()
        if not skills:
            return 0.0
        return sum(s.mastery_score for s in skills) / len(skills)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_skills(self) -> None:
        """Seed skill records for all standard benchmarks."""
        existing = {s.skill_id for s in self._skill_repo.get_all_skills()}
        for bm in STANDARD_BENCHMARKS:
            skill_id = f"skill-{bm.skill_area}"
            if skill_id not in existing:
                self._skill_repo.upsert_skill(Skill(
                    skill_id=skill_id,
                    name=bm.skill_area.replace("_", " ").title(),
                    description=bm.description,
                    category=bm.skill_area,
                ))
                existing.add(skill_id)

    def _update_skill(self, bm: BenchmarkTask, result: BenchmarkResult) -> None:
        skill_id = f"skill-{bm.skill_area}"
        self._skill_repo.record_attempt(
            skill_id=skill_id,
            success=result.passed,
            score=result.score,
        )
