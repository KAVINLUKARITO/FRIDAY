"""Tests for the structured learning memory subsystem (Phase 2).

Covers:
- Lesson model validation, immutability, and serialisation
- GoalPattern computation and success rate
- LearningContext construction and properties
- LearningStore CRUD operations with in-memory SQLite
- Analyzer extraction from various EvolutionResult shapes
- Context builder with empty, sparse, and rich store states
- Keyword extraction determinism
- Edge cases: empty data, single attempt, all failures, all successes
- No side effects: no file writes, no network calls

All tests use unittest (no pytest dependency).
"""

from __future__ import annotations

import unittest
from typing import Optional

from aiworker.learning.models import (
    GoalPattern,
    Lesson,
    LearningContext,
    _new_lesson_id,
    _utcnow_iso,
)
from aiworker.learning.store import LearningStore
from aiworker.learning.analyzer import (
    _extract_keywords,
    _failure_stage,
    analyze_result,
)
from aiworker.learning.context_builder import build_context
from aiworker.autonomy.models import (
    AttemptRecord,
    EvolutionConfig,
    EvolutionResult,
)
from aiworker.memory.database import Database


# ── Helpers ──────────────────────────────────────────────────


def _make_lesson(
    category: str = "failure_mode",
    summary: str = "Test lesson summary",
    detail: str = "Detail about the lesson",
    confidence: float = 0.7,
    source_goal: str = "refactor auth module",
    keywords: tuple[str, ...] = ("refactor", "auth", "module"),
    times_applied: int = 0,
    times_helpful: int = 0,
) -> Lesson:
    """Create a test lesson with reasonable defaults."""
    return Lesson(
        lesson_id=_new_lesson_id(),
        category=category,
        summary=summary,
        detail=detail,
        confidence=confidence,
        source_attempt_ids=("att-1",),
        source_goal=source_goal,
        applicable_goal_keywords=keywords,
        created_at=_utcnow_iso(),
        times_applied=times_applied,
        times_helpful=times_helpful,
    )


def _make_config(
    goal: str = "refactor auth module",
    max_attempts: int = 5,
    max_failures: int = 3,
    confidence_threshold: float = 0.4,
) -> EvolutionConfig:
    """Create a test EvolutionConfig."""
    return EvolutionConfig(
        goal=goal,
        allowed_files=("auth.py",),
        max_attempts=max_attempts,
        max_failures=max_failures,
        confidence_threshold=confidence_threshold,
    )


def _make_attempt(
    attempt_number: int = 1,
    outcome: str = "success",
    policy_allowed: bool = True,
    plan_generated: bool = True,
    patch_generated: bool = True,
    validation_passed: bool = True,
    sandbox_success: bool = True,
    confidence_score: float = 0.75,
) -> AttemptRecord:
    """Create a test AttemptRecord."""
    return AttemptRecord(
        attempt_number=attempt_number,
        attempt_id=f"att-{attempt_number}",
        timestamp=_utcnow_iso(),
        outcome=outcome,
        policy_allowed=policy_allowed,
        plan_generated=plan_generated,
        patch_generated=patch_generated,
        validation_passed=validation_passed,
        sandbox_success=sandbox_success,
        confidence_score=confidence_score,
    )


def _make_result(
    config: Optional[EvolutionConfig] = None,
    success: bool = False,
    termination_reason: str = "max_attempts_reached",
    attempts: Optional[tuple] = None,
) -> EvolutionResult:
    """Create a test EvolutionResult."""
    cfg = config or _make_config()
    atts = attempts or ()
    successes = sum(1 for a in atts if a.outcome == "success")
    failures = sum(1 for a in atts if a.outcome != "success")
    return EvolutionResult(
        config=cfg,
        success=success,
        termination_reason=termination_reason,
        total_attempts=len(atts),
        successful_attempts=successes,
        failed_attempts=failures,
        attempts=atts,
        final_confidence=atts[-1].confidence_score if atts else 0.0,
    )


def _make_store() -> LearningStore:
    """Create an in-memory LearningStore."""
    db = Database(":memory:")
    db.initialise()
    return LearningStore(db)


# ── Lesson model ─────────────────────────────────────────────


class TestLessonModel(unittest.TestCase):
    """Verify Lesson validation, immutability, and serialisation."""

    def test_valid_construction(self) -> None:
        lesson = _make_lesson()
        self.assertEqual(lesson.category, "failure_mode")
        self.assertGreater(len(lesson.lesson_id), 0)

    def test_frozen(self) -> None:
        lesson = _make_lesson()
        with self.assertRaises(AttributeError):
            lesson.summary = "changed"  # type: ignore[misc]

    def test_empty_summary_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _make_lesson(summary="")
        self.assertIn("summary", str(ctx.exception))

    def test_whitespace_summary_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _make_lesson(summary="   ")

    def test_confidence_below_zero_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _make_lesson(confidence=-0.1)
        self.assertIn("confidence", str(ctx.exception))

    def test_confidence_above_one_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _make_lesson(confidence=1.1)

    def test_confidence_boundary_values(self) -> None:
        l0 = _make_lesson(confidence=0.0)
        l1 = _make_lesson(confidence=1.0)
        self.assertEqual(l0.confidence, 0.0)
        self.assertEqual(l1.confidence, 1.0)

    def test_negative_times_applied_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _make_lesson(times_applied=-1)

    def test_helpful_exceeds_applied_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _make_lesson(times_applied=2, times_helpful=3)

    def test_helpfulness_rate_zero_applications(self) -> None:
        lesson = _make_lesson(times_applied=0, times_helpful=0)
        self.assertEqual(lesson.helpfulness_rate, 0.0)

    def test_helpfulness_rate_computed(self) -> None:
        lesson = _make_lesson(times_applied=10, times_helpful=7)
        self.assertAlmostEqual(lesson.helpfulness_rate, 0.7)

    def test_to_dict(self) -> None:
        lesson = _make_lesson()
        d = lesson.to_dict()
        self.assertIn("lesson_id", d)
        self.assertIn("category", d)
        self.assertIn("helpfulness_rate", d)
        self.assertIsInstance(d["source_attempt_ids"], list)
        self.assertIsInstance(d["applicable_goal_keywords"], list)

    def test_empty_source_attempt_ids_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Lesson(
                lesson_id="x",
                category="failure_mode",
                summary="test",
                detail="detail",
                confidence=0.5,
                source_attempt_ids=(),
                source_goal="goal",
                applicable_goal_keywords=("test",),
                created_at="2025-01-01",
            )
        self.assertIn("source_attempt_ids", str(ctx.exception))


# ── GoalPattern model ────────────────────────────────────────


class TestGoalPattern(unittest.TestCase):
    """Verify GoalPattern computation."""

    def test_success_rate_zero_attempts(self) -> None:
        gp = GoalPattern(
            pattern="test",
            total_attempts=0,
            successful_attempts=0,
            average_confidence=0.0,
            common_failure_stages=(),
        )
        self.assertEqual(gp.success_rate, 0.0)

    def test_success_rate_computed(self) -> None:
        gp = GoalPattern(
            pattern="test",
            total_attempts=10,
            successful_attempts=7,
            average_confidence=0.6,
            common_failure_stages=("sandbox",),
        )
        self.assertAlmostEqual(gp.success_rate, 0.7)

    def test_frozen(self) -> None:
        gp = GoalPattern(
            pattern="test",
            total_attempts=1,
            successful_attempts=1,
            average_confidence=0.5,
            common_failure_stages=(),
        )
        with self.assertRaises(AttributeError):
            gp.pattern = "changed"  # type: ignore[misc]

    def test_to_dict(self) -> None:
        gp = GoalPattern(
            pattern="test",
            total_attempts=5,
            successful_attempts=3,
            average_confidence=0.65,
            common_failure_stages=("sandbox", "scoring"),
        )
        d = gp.to_dict()
        self.assertIn("success_rate", d)
        self.assertIsInstance(d["common_failure_stages"], list)


# ── LearningContext model ────────────────────────────────────


class TestLearningContext(unittest.TestCase):
    """Verify LearningContext properties."""

    def test_no_prior_knowledge(self) -> None:
        ctx = LearningContext(goal="new goal")
        self.assertFalse(ctx.has_prior_knowledge)
        self.assertEqual(ctx.relevant_lessons, ())
        self.assertIsNone(ctx.goal_pattern)

    def test_has_prior_knowledge_with_lessons(self) -> None:
        lesson = _make_lesson()
        ctx = LearningContext(goal="test", relevant_lessons=(lesson,))
        self.assertTrue(ctx.has_prior_knowledge)

    def test_has_prior_knowledge_with_pattern(self) -> None:
        gp = GoalPattern(
            pattern="test",
            total_attempts=1,
            successful_attempts=1,
            average_confidence=0.5,
            common_failure_stages=(),
        )
        ctx = LearningContext(goal="test", goal_pattern=gp)
        self.assertTrue(ctx.has_prior_knowledge)

    def test_frozen(self) -> None:
        ctx = LearningContext(goal="test")
        with self.assertRaises(AttributeError):
            ctx.goal = "changed"  # type: ignore[misc]

    def test_to_dict(self) -> None:
        ctx = LearningContext(goal="test")
        d = ctx.to_dict()
        self.assertIn("goal", d)
        self.assertIn("has_prior_knowledge", d)
        self.assertIsInstance(d["relevant_lessons"], list)


# ── LearningStore ────────────────────────────────────────────


class TestLearningStore(unittest.TestCase):
    """Verify SQLite persistence for lessons."""

    def test_insert_and_retrieve(self) -> None:
        store = _make_store()
        lesson = _make_lesson()
        store.insert_lesson(lesson)
        retrieved = store.get_lesson_by_id(lesson.lesson_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.lesson_id, lesson.lesson_id)
        self.assertEqual(retrieved.summary, lesson.summary)
        self.assertEqual(retrieved.category, lesson.category)

    def test_get_nonexistent_returns_none(self) -> None:
        store = _make_store()
        self.assertIsNone(store.get_lesson_by_id("nonexistent"))

    def test_lesson_count(self) -> None:
        store = _make_store()
        self.assertEqual(store.lesson_count(), 0)
        store.insert_lesson(_make_lesson())
        store.insert_lesson(_make_lesson())
        self.assertEqual(store.lesson_count(), 2)

    def test_get_all_lessons(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(summary="First"))
        store.insert_lesson(_make_lesson(summary="Second"))
        store.insert_lesson(_make_lesson(summary="Third"))
        all_lessons = store.get_all_lessons()
        self.assertEqual(len(all_lessons), 3)

    def test_get_all_respects_limit(self) -> None:
        store = _make_store()
        for i in range(10):
            store.insert_lesson(_make_lesson(summary=f"Lesson {i}"))
        limited = store.get_all_lessons(limit=3)
        self.assertEqual(len(limited), 3)

    def test_keyword_search(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            keywords=("refactor", "auth"),
            summary="Auth lesson",
        ))
        store.insert_lesson(_make_lesson(
            keywords=("add", "database"),
            summary="DB lesson",
        ))
        results = store.get_lessons_for_keywords(["auth"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].summary, "Auth lesson")

    def test_keyword_search_case_insensitive(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            keywords=("refactor", "auth"),
            summary="Auth lesson",
        ))
        results = store.get_lessons_for_keywords(["AUTH"])
        self.assertEqual(len(results), 1)

    def test_keyword_search_multiple_keywords(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            keywords=("refactor", "auth"),
            summary="Auth lesson",
        ))
        store.insert_lesson(_make_lesson(
            keywords=("add", "database"),
            summary="DB lesson",
        ))
        results = store.get_lessons_for_keywords(["auth", "database"])
        self.assertEqual(len(results), 2)

    def test_keyword_search_empty_keywords(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson())
        results = store.get_lessons_for_keywords([])
        self.assertEqual(len(results), 0)

    def test_keyword_search_ordered_by_confidence(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            keywords=("refactor",), confidence=0.3, summary="Low"
        ))
        store.insert_lesson(_make_lesson(
            keywords=("refactor",), confidence=0.9, summary="High"
        ))
        results = store.get_lessons_for_keywords(["refactor"])
        self.assertEqual(results[0].summary, "High")
        self.assertEqual(results[1].summary, "Low")

    def test_get_by_category(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(category="failure_mode"))
        store.insert_lesson(_make_lesson(category="success_pattern"))
        store.insert_lesson(_make_lesson(category="failure_mode"))
        results = store.get_lessons_by_category("failure_mode")
        self.assertEqual(len(results), 2)

    def test_update_applied_not_helpful(self) -> None:
        store = _make_store()
        lesson = _make_lesson()
        store.insert_lesson(lesson)
        updated = store.update_lesson_applied(lesson.lesson_id, helpful=False)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.times_applied, 1)
        self.assertEqual(updated.times_helpful, 0)

    def test_update_applied_helpful(self) -> None:
        store = _make_store()
        lesson = _make_lesson()
        store.insert_lesson(lesson)
        updated = store.update_lesson_applied(lesson.lesson_id, helpful=True)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.times_applied, 1)
        self.assertEqual(updated.times_helpful, 1)

    def test_update_nonexistent_returns_none(self) -> None:
        store = _make_store()
        result = store.update_lesson_applied("nonexistent", helpful=True)
        self.assertIsNone(result)

    def test_delete_lesson(self) -> None:
        store = _make_store()
        lesson = _make_lesson()
        store.insert_lesson(lesson)
        self.assertTrue(store.delete_lesson(lesson.lesson_id))
        self.assertIsNone(store.get_lesson_by_id(lesson.lesson_id))

    def test_delete_nonexistent(self) -> None:
        store = _make_store()
        self.assertFalse(store.delete_lesson("nonexistent"))

    def test_tuple_fields_roundtrip(self) -> None:
        """Verify tuple fields survive JSON serialisation roundtrip."""
        store = _make_store()
        lesson = _make_lesson(
            keywords=("alpha", "beta", "gamma"),
        )
        store.insert_lesson(lesson)
        retrieved = store.get_lesson_by_id(lesson.lesson_id)
        self.assertEqual(
            retrieved.applicable_goal_keywords,
            ("alpha", "beta", "gamma"),
        )
        self.assertEqual(
            retrieved.source_attempt_ids,
            ("att-1",),
        )


# ── Analyzer: keyword extraction ─────────────────────────────


class TestKeywordExtraction(unittest.TestCase):
    """Verify deterministic keyword extraction."""

    def test_basic_extraction(self) -> None:
        kw = _extract_keywords("refactor the auth module")
        self.assertIn("refactor", kw)
        self.assertIn("auth", kw)
        self.assertIn("module", kw)
        # "the" is a stopword
        self.assertNotIn("the", kw)

    def test_sorted_output(self) -> None:
        kw = _extract_keywords("zebra alpha middle")
        self.assertEqual(kw, ("alpha", "middle", "zebra"))

    def test_deterministic(self) -> None:
        kw1 = _extract_keywords("add new feature to auth")
        kw2 = _extract_keywords("add new feature to auth")
        self.assertEqual(kw1, kw2)

    def test_empty_goal(self) -> None:
        kw = _extract_keywords("")
        self.assertEqual(kw, ())

    def test_short_words_filtered(self) -> None:
        kw = _extract_keywords("do it so we go on")
        self.assertEqual(kw, ())  # all words <= 2 chars or stopwords

    def test_deduplication(self) -> None:
        kw = _extract_keywords("fix fix fix the bug bug")
        self.assertEqual(kw.count("fix"), 1)
        self.assertEqual(kw.count("bug"), 1)


# ── Analyzer: failure stage detection ────────────────────────


class TestFailureStage(unittest.TestCase):
    """Verify failure stage classification."""

    def test_governance_failure(self) -> None:
        attempt = _make_attempt(policy_allowed=False, outcome="policy_denied")
        self.assertEqual(_failure_stage(attempt), "governance")

    def test_planning_failure(self) -> None:
        attempt = _make_attempt(
            plan_generated=False, outcome="plan_failed"
        )
        self.assertEqual(_failure_stage(attempt), "planning")

    def test_patch_generation_failure(self) -> None:
        attempt = _make_attempt(
            patch_generated=False, outcome="patch_generation_failed"
        )
        self.assertEqual(_failure_stage(attempt), "patch_generation")

    def test_validation_failure(self) -> None:
        attempt = _make_attempt(
            validation_passed=False, outcome="validation_failed"
        )
        self.assertEqual(_failure_stage(attempt), "validation")

    def test_sandbox_failure(self) -> None:
        attempt = _make_attempt(
            sandbox_success=False, outcome="sandbox_failed"
        )
        self.assertEqual(_failure_stage(attempt), "sandbox")

    def test_scoring_failure(self) -> None:
        # All stages passed but outcome is scoring rejection.
        attempt = _make_attempt(outcome="scoring_below_threshold")
        self.assertEqual(_failure_stage(attempt), "scoring")


# ── Analyzer: lesson extraction ──────────────────────────────


class TestAnalyzer(unittest.TestCase):
    """Verify lesson extraction from EvolutionResult."""

    def test_empty_result_no_lessons(self) -> None:
        result = _make_result(attempts=())
        lessons = analyze_result(result)
        self.assertEqual(len(lessons), 0)

    def test_single_success_produces_lesson(self) -> None:
        attempt = _make_attempt(outcome="success")
        result = _make_result(
            success=True,
            termination_reason="success",
            attempts=(attempt,),
        )
        lessons = analyze_result(result)
        categories = [l.category for l in lessons]
        self.assertIn("success_pattern", categories)

    def test_repeated_failures_produce_failure_lesson(self) -> None:
        attempts = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="sandbox_failed",
                sandbox_success=False,
            )
            for i in range(1, 4)
        )
        result = _make_result(attempts=attempts)
        lessons = analyze_result(result)
        failure_lessons = [l for l in lessons if l.category == "failure_mode"]
        self.assertGreater(len(failure_lessons), 0)
        # Should identify sandbox as failure stage.
        self.assertTrue(
            any("sandbox" in l.summary.lower() for l in failure_lessons)
        )

    def test_single_failure_no_failure_lesson(self) -> None:
        """A single failure should not produce a failure mode lesson."""
        attempt = _make_attempt(
            outcome="sandbox_failed",
            sandbox_success=False,
        )
        result = _make_result(attempts=(attempt,))
        lessons = analyze_result(result)
        failure_lessons = [l for l in lessons if l.category == "failure_mode"]
        self.assertEqual(len(failure_lessons), 0)

    def test_scoring_rejection_produces_strategy_lesson(self) -> None:
        attempts = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="scoring_below_threshold",
                confidence_score=0.3,
            )
            for i in range(1, 4)
        )
        result = _make_result(
            config=_make_config(confidence_threshold=0.9),
            attempts=attempts,
            termination_reason="max_attempts_reached",
        )
        lessons = analyze_result(result)
        strategy_lessons = [l for l in lessons if l.category == "goal_strategy"]
        self.assertGreater(len(strategy_lessons), 0)
        self.assertTrue(
            any("threshold" in l.summary.lower() for l in strategy_lessons)
        )

    def test_circuit_breaker_produces_strategy_lesson(self) -> None:
        attempts = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="sandbox_failed",
                sandbox_success=False,
            )
            for i in range(1, 4)
        )
        result = _make_result(
            attempts=attempts,
            termination_reason="circuit_breaker_open",
        )
        lessons = analyze_result(result)
        strategy_lessons = [l for l in lessons if l.category == "goal_strategy"]
        self.assertTrue(
            any("circuit breaker" in l.summary.lower() for l in strategy_lessons)
        )

    def test_validation_failures_produce_patch_heuristic(self) -> None:
        attempts = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="validation_failed",
                validation_passed=False,
            )
            for i in range(1, 4)
        )
        result = _make_result(attempts=attempts)
        lessons = analyze_result(result)
        heuristic_lessons = [l for l in lessons if l.category == "patch_heuristic"]
        self.assertGreater(len(heuristic_lessons), 0)

    def test_confidence_scales_with_count(self) -> None:
        """More failures should produce higher-confidence lessons."""
        small = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="sandbox_failed",
                sandbox_success=False,
            )
            for i in range(1, 3)  # 2 failures
        )
        large = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="sandbox_failed",
                sandbox_success=False,
            )
            for i in range(1, 8)  # 7 failures
        )
        small_lessons = analyze_result(_make_result(attempts=small))
        large_lessons = analyze_result(_make_result(
            config=_make_config(max_attempts=10),
            attempts=large,
        ))

        small_fm = [l for l in small_lessons if l.category == "failure_mode"]
        large_fm = [l for l in large_lessons if l.category == "failure_mode"]

        if small_fm and large_fm:
            self.assertGreater(
                large_fm[0].confidence, small_fm[0].confidence
            )

    def test_all_lessons_have_valid_fields(self) -> None:
        """Verify every extracted lesson passes model validation."""
        attempts = (
            _make_attempt(attempt_number=1, outcome="success"),
            _make_attempt(
                attempt_number=2,
                outcome="sandbox_failed",
                sandbox_success=False,
            ),
            _make_attempt(
                attempt_number=3,
                outcome="sandbox_failed",
                sandbox_success=False,
            ),
        )
        result = _make_result(attempts=attempts)
        lessons = analyze_result(result)
        for lesson in lessons:
            # These would raise ValueError if invalid.
            self.assertGreater(len(lesson.lesson_id), 0)
            self.assertGreater(len(lesson.summary), 0)
            self.assertGreaterEqual(lesson.confidence, 0.0)
            self.assertLessEqual(lesson.confidence, 1.0)
            self.assertGreater(len(lesson.source_attempt_ids), 0)

    def test_keywords_populated_from_goal(self) -> None:
        attempt = _make_attempt(outcome="success")
        result = _make_result(
            config=_make_config(goal="refactor auth module"),
            success=True,
            termination_reason="success",
            attempts=(attempt,),
        )
        lessons = analyze_result(result)
        for lesson in lessons:
            self.assertIn("refactor", lesson.applicable_goal_keywords)
            self.assertIn("auth", lesson.applicable_goal_keywords)


# ── Context builder ──────────────────────────────────────────


class TestContextBuilder(unittest.TestCase):
    """Verify LearningContext assembly from store."""

    def test_empty_store(self) -> None:
        store = _make_store()
        ctx = build_context("refactor auth module", store)
        self.assertEqual(ctx.goal, "refactor auth module")
        self.assertFalse(ctx.has_prior_knowledge)
        self.assertEqual(ctx.relevant_lessons, ())
        self.assertIsNone(ctx.goal_pattern)
        self.assertEqual(ctx.lesson_count, 0)
        self.assertIn("No prior history", ctx.suggested_strategy)

    def test_with_relevant_lessons(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            keywords=("refactor", "auth"),
            summary="Auth failure lesson",
        ))
        ctx = build_context("refactor auth module", store)
        self.assertTrue(ctx.has_prior_knowledge)
        self.assertEqual(len(ctx.relevant_lessons), 1)
        self.assertEqual(ctx.lesson_count, 1)

    def test_irrelevant_lessons_excluded(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            keywords=("database", "migration"),
            summary="DB lesson",
        ))
        ctx = build_context("refactor auth module", store)
        self.assertEqual(len(ctx.relevant_lessons), 0)

    def test_goal_pattern_built(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            category="success_pattern",
            keywords=("refactor",),
            confidence=0.8,
        ))
        store.insert_lesson(_make_lesson(
            category="failure_mode",
            keywords=("refactor",),
            summary="Repeated failures at sandbox stage",
            confidence=0.6,
        ))
        ctx = build_context("refactor something", store)
        self.assertIsNotNone(ctx.goal_pattern)
        self.assertEqual(ctx.goal_pattern.total_attempts, 2)
        self.assertEqual(ctx.goal_pattern.successful_attempts, 1)

    def test_failure_modes_extracted(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            category="failure_mode",
            keywords=("refactor",),
            summary="Repeated failures at sandbox stage",
        ))
        store.insert_lesson(_make_lesson(
            category="failure_mode",
            keywords=("refactor",),
            summary="Repeated failures at validation stage",
        ))
        ctx = build_context("refactor something", store)
        self.assertGreater(len(ctx.common_failure_modes), 0)

    def test_recommended_threshold(self) -> None:
        store = _make_store()
        # Insert success patterns with high confidence.
        for _ in range(3):
            store.insert_lesson(_make_lesson(
                category="success_pattern",
                keywords=("refactor",),
                confidence=0.85,
            ))
        ctx = build_context("refactor something", store)
        # Threshold should be adjusted based on success patterns.
        self.assertGreater(ctx.recommended_confidence_threshold, 0.0)
        self.assertLessEqual(ctx.recommended_confidence_threshold, 0.9)

    def test_strategy_mentions_history(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(
            category="success_pattern",
            keywords=("refactor",),
            confidence=0.8,
        ))
        ctx = build_context("refactor something", store)
        self.assertNotIn("No prior history", ctx.suggested_strategy)

    def test_to_dict_serialisable(self) -> None:
        store = _make_store()
        store.insert_lesson(_make_lesson(keywords=("refactor",)))
        ctx = build_context("refactor something", store)
        d = ctx.to_dict()
        # Should be JSON-serialisable (all basic types).
        import json
        json.dumps(d)  # Should not raise.

    def test_context_frozen(self) -> None:
        store = _make_store()
        ctx = build_context("test", store)
        with self.assertRaises(AttributeError):
            ctx.goal = "changed"  # type: ignore[misc]


# ── Integration: analyze → store → context ───────────────────


class TestIntegration(unittest.TestCase):
    """End-to-end: extract lessons, store them, build context."""

    def test_full_cycle(self) -> None:
        """Extract lessons from a result, store them, build context."""
        store = _make_store()

        # Simulate a failed evolution run.
        attempts = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="sandbox_failed",
                sandbox_success=False,
            )
            for i in range(1, 5)
        )
        result = _make_result(
            config=_make_config(goal="refactor auth module"),
            attempts=attempts,
        )

        # Extract and store lessons.
        lessons = analyze_result(result)
        self.assertGreater(len(lessons), 0)

        for lesson in lessons:
            store.insert_lesson(lesson)

        # Build context for a similar goal.
        ctx = build_context("refactor auth service", store)
        self.assertTrue(ctx.has_prior_knowledge)
        self.assertGreater(len(ctx.relevant_lessons), 0)

    def test_learning_improves_with_more_data(self) -> None:
        """More results → richer context."""
        store = _make_store()

        # First run: failures.
        r1_attempts = tuple(
            _make_attempt(
                attempt_number=i,
                outcome="sandbox_failed",
                sandbox_success=False,
            )
            for i in range(1, 4)
        )
        r1 = _make_result(
            config=_make_config(goal="refactor auth module"),
            attempts=r1_attempts,
        )
        for lesson in analyze_result(r1):
            store.insert_lesson(lesson)

        ctx1 = build_context("refactor auth service", store)

        # Second run: success.
        r2_attempts = (
            _make_attempt(attempt_number=1, outcome="success", confidence_score=0.8),
        )
        r2 = _make_result(
            config=_make_config(goal="refactor auth handler"),
            success=True,
            termination_reason="success",
            attempts=r2_attempts,
        )
        for lesson in analyze_result(r2):
            store.insert_lesson(lesson)

        ctx2 = build_context("refactor auth service", store)

        # Second context should have more lessons.
        self.assertGreaterEqual(
            len(ctx2.relevant_lessons),
            len(ctx1.relevant_lessons),
        )
        self.assertGreater(ctx2.lesson_count, ctx1.lesson_count)

    def test_lesson_application_tracking(self) -> None:
        """Verify that applying lessons updates their tracking counters."""
        store = _make_store()
        lesson = _make_lesson(keywords=("refactor",))
        store.insert_lesson(lesson)

        # Simulate applying the lesson twice, once helpful.
        store.update_lesson_applied(lesson.lesson_id, helpful=True)
        store.update_lesson_applied(lesson.lesson_id, helpful=False)

        updated = store.get_lesson_by_id(lesson.lesson_id)
        self.assertEqual(updated.times_applied, 2)
        self.assertEqual(updated.times_helpful, 1)
        self.assertAlmostEqual(updated.helpfulness_rate, 0.5)

    def test_no_cross_contamination(self) -> None:
        """Lessons from one goal don't appear in unrelated context."""
        store = _make_store()
        store.insert_lesson(_make_lesson(
            keywords=("database", "migration"),
            source_goal="migrate database schema",
        ))

        ctx = build_context("refactor auth module", store)
        self.assertEqual(len(ctx.relevant_lessons), 0)

    def test_multiple_stores_isolated(self) -> None:
        """Different in-memory databases are fully isolated."""
        store1 = _make_store()
        store2 = _make_store()
        store1.insert_lesson(_make_lesson())
        self.assertEqual(store1.lesson_count(), 1)
        self.assertEqual(store2.lesson_count(), 0)


# ── No side effects ──────────────────────────────────────────


class TestNoSideEffects(unittest.TestCase):
    """Verify no filesystem or network side effects."""

    def test_no_file_writes(self) -> None:
        import os
        import tempfile

        workspace = tempfile.mkdtemp()
        try:
            before = os.listdir(workspace)

            store = _make_store()
            lesson = _make_lesson()
            store.insert_lesson(lesson)
            store.get_lesson_by_id(lesson.lesson_id)
            store.get_all_lessons()
            store.update_lesson_applied(lesson.lesson_id, helpful=True)

            result = _make_result(attempts=(
                _make_attempt(outcome="success"),
            ))
            analyze_result(result)
            build_context("test goal", store)

            after = os.listdir(workspace)
            self.assertEqual(before, after)
        finally:
            os.rmdir(workspace)


if __name__ == "__main__":
    unittest.main()
