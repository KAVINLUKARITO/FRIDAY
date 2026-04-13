"""Benchmark registry and evaluator — Phase 5.

All benchmarks are deterministic. Scoring uses explicit rules.
No LLM calls, no randomness, no filesystem writes.
"""
from __future__ import annotations
import time
import uuid
from typing import Callable, Dict, List, Optional

from aiworker.experiment.models import BenchmarkResult, BenchmarkTask


# ── Standard Benchmark Definitions ──────────────────────────────────────────
STANDARD_BENCHMARKS: List[BenchmarkTask] = [
    BenchmarkTask(
        benchmark_id="bm-type-hints",
        name="Type Hint Coverage",
        description="All public functions must have complete type annotations.",
        skill_area="typing",
        input_spec="Count public functions with and without type hints.",
        pass_criteria="100% of public functions annotated.",
        difficulty="beginner",
    ),
    BenchmarkTask(
        benchmark_id="bm-test-coverage",
        name="Test Coverage",
        description="Unit test coverage must exceed 80%.",
        skill_area="testing",
        input_spec="Run test suite and measure line coverage.",
        pass_criteria="Coverage >= 80%.",
        difficulty="beginner",
    ),
    BenchmarkTask(
        benchmark_id="bm-error-handling",
        name="Error Handling",
        description="All public functions must handle and document failure modes.",
        skill_area="error_handling",
        input_spec="Check for try/except, raises in docstrings, custom exceptions.",
        pass_criteria="No unhandled bare exceptions in public API.",
        difficulty="intermediate",
    ),
    BenchmarkTask(
        benchmark_id="bm-dep-injection",
        name="Dependency Injection",
        description="Modules must accept dependencies via __init__, not import them internally.",
        skill_area="design_pattern",
        input_spec="Check for hardcoded imports inside methods vs constructor injection.",
        pass_criteria="All external dependencies injected.",
        difficulty="intermediate",
    ),
    BenchmarkTask(
        benchmark_id="bm-thread-safety",
        name="Thread Safety",
        description="Shared state must be protected with appropriate primitives.",
        skill_area="concurrency",
        input_spec="Check for unprotected shared mutable state.",
        pass_criteria="All shared state protected or made immutable.",
        difficulty="advanced",
    ),
]

_BENCHMARK_INDEX: Dict[str, BenchmarkTask] = {
    b.benchmark_id: b for b in STANDARD_BENCHMARKS
}

# Evaluator type: (task, attempt_code) -> (score [0,1], notes)
EvaluatorFn = Callable[[BenchmarkTask, str], tuple[float, str]]


def _default_evaluator(task: BenchmarkTask, attempt_code: str) -> tuple[float, str]:
    """Simple heuristic evaluator when no custom evaluator is registered."""
    code = attempt_code.strip()
    score = 0.0
    notes_parts = []

    if not code:
        return 0.0, "Empty submission"

    # Heuristics per skill area
    skill = task.skill_area
    if skill == "typing":
        has_hints = "->" in code or ": " in code
        score = 0.9 if has_hints else 0.1
        notes_parts.append("Type hints detected" if has_hints else "No type hints found")
    elif skill == "testing":
        has_tests = "def test_" in code or "assert " in code
        score = 0.85 if has_tests else 0.1
        notes_parts.append("Tests detected" if has_tests else "No tests found")
    elif skill == "error_handling":
        has_handling = "try:" in code or "except" in code or "raise" in code
        score = 0.8 if has_handling else 0.1
        notes_parts.append("Error handling detected" if has_handling else "No error handling")
    elif skill == "design_pattern":
        has_di = "def __init__" in code and "self." in code
        score = 0.75 if has_di else 0.2
        notes_parts.append("Constructor injection detected" if has_di else "No DI pattern")
    elif skill == "concurrency":
        has_sync = "Lock()" in code or "RLock()" in code or "threading" in code
        score = 0.8 if has_sync else 0.1
        notes_parts.append("Synchronisation detected" if has_sync else "No thread safety")
    else:
        score = 0.5
        notes_parts.append(f"Generic evaluation for skill: {skill}")

    # Penalty for short submissions
    if len(code) < 50:
        score *= 0.5
        notes_parts.append("Submission very short — penalised")

    score = max(0.0, min(1.0, score))
    return round(score, 4), "; ".join(notes_parts)


class BenchmarkRegistry:
    """Registry of benchmarks and their evaluators."""

    def __init__(self) -> None:
        self._benchmarks = dict(_BENCHMARK_INDEX)
        self._evaluators: Dict[str, EvaluatorFn] = {}

    def get(self, benchmark_id: str) -> Optional[BenchmarkTask]:
        return self._benchmarks.get(benchmark_id)

    def all_benchmarks(self) -> List[BenchmarkTask]:
        return list(self._benchmarks.values())

    def register_evaluator(self, benchmark_id: str, fn: EvaluatorFn) -> None:
        self._evaluators[benchmark_id] = fn

    def evaluate(
        self, benchmark_id: str, attempt_code: str
    ) -> BenchmarkResult:
        """Score an attempt against a benchmark.

        Args:
            benchmark_id: Which benchmark to evaluate against.
            attempt_code: The submitted code string.

        Returns:
            :class:`BenchmarkResult` with score and notes.
        """
        task = self._benchmarks.get(benchmark_id)
        if task is None:
            return BenchmarkResult(
                benchmark_id=benchmark_id,
                attempt_id=str(uuid.uuid4()),
                score=0.0,
                passed=False,
                notes=f"Unknown benchmark: {benchmark_id}",
                duration_seconds=0.0,
            )
        evaluator = self._evaluators.get(benchmark_id, _default_evaluator)
        start = time.monotonic()
        score, notes = evaluator(task, attempt_code)
        duration = time.monotonic() - start
        passed = score >= (task.max_score * 0.7)  # 70% threshold

        return BenchmarkResult(
            benchmark_id=benchmark_id,
            attempt_id=str(uuid.uuid4()),
            score=score,
            passed=passed,
            notes=notes,
            duration_seconds=duration,
        )
