from __future__ import annotations

from datetime import datetime, timedelta, timezone

from friday.memory.episodic import Episode, EpisodicMemory
from friday.reflection import ReflectionEngine
from planner import AgentState
from storage import StepRecord


def _record(
    tool_name: str,
    status: str,
    duration: float = 0.1,
    error: str | None = None,
    output_summary: str = "output",
) -> StepRecord:
    return StepRecord(
        run_id="run-1",
        step_number=1,
        tool_name=tool_name,
        parameters={"path": "."},
        reason="reason",
        verification_status=status,
        output_summary=output_summary,
        error=error,
        duration_seconds=duration,
        timestamp=datetime.now(timezone.utc),
    )


def test_reflect_on_completed_run_extracts_clean_run_tag(db_path) -> None:
    engine = ReflectionEngine(EpisodicMemory(db_path))
    state = AgentState(run_id="run-1", task="list files", status="completed")
    episode = engine.reflect(state, [_record("list_files", "SUCCESS")])

    assert "clean_run" in episode.tags


def test_reflect_on_aborted_run_extracts_failed_tag(db_path) -> None:
    engine = ReflectionEngine(EpisodicMemory(db_path))
    state = AgentState(run_id="run-1", task="list files", status="aborted")
    episode = engine.reflect(state, [_record("list_files", "FAILURE", error="boom")])

    assert "failed" in episode.tags


def test_reflect_with_retries_greater_than_zero_adds_replan_lesson(db_path) -> None:
    engine = ReflectionEngine(EpisodicMemory(db_path))
    state = AgentState(run_id="run-1", task="list files", status="completed", replans=1)
    episode = engine.reflect(state, [_record("list_files", "SUCCESS")])

    assert any("replan" in lesson.lower() for lesson in episode.lessons)


def test_reflect_with_timeout_adds_timeout_lesson(db_path) -> None:
    engine = ReflectionEngine(EpisodicMemory(db_path))
    state = AgentState(run_id="run-1", task="http get", status="aborted")
    episode = engine.reflect(state, [_record("http_get", "FAILURE", error="execution timed out")])

    assert any("timeout" in lesson.lower() for lesson in episode.lessons)


def test_success_rate_computed_correctly_from_step_records(db_path) -> None:
    engine = ReflectionEngine(EpisodicMemory(db_path))
    state = AgentState(run_id="run-1", task="mixed", status="completed")
    episode = engine.reflect(
        state,
        [
            _record("list_files", "SUCCESS"),
            _record("read_file", "FAILURE"),
            _record("write_file", "SUCCESS"),
        ],
    )

    assert round(episode.success_rate, 2) == 0.67


def test_episode_saved_to_memory_after_reflect(db_path) -> None:
    memory = EpisodicMemory(db_path)
    engine = ReflectionEngine(memory)
    state = AgentState(run_id="run-1", task="list files", status="completed")
    engine.reflect(state, [_record("list_files", "SUCCESS")])

    assert len(memory.get_recent_episodes(limit=10)) == 1


def test_get_performance_trend_returns_improving_when_recent_exceeds_overall(db_path) -> None:
    memory = EpisodicMemory(db_path)
    base = datetime.now(timezone.utc)
    for index in range(6):
        episode = Episode(
            run_id=f"run-{index}",
            task=f"task {index}",
            status="completed",
            steps_taken=1,
            tools_used=["list_files"],
            success_rate=0.2 if index == 0 else 1.0,
            final_output_summary="ok",
            reflection="ok",
            lessons=[],
            duration_seconds=1.0,
            timestamp=base + timedelta(seconds=index),
            tags=[],
        )
        memory.save_episode(episode)
    trend = ReflectionEngine(memory).get_performance_trend(last_n=6)

    assert trend["trend"] == "improving"


def test_get_performance_trend_returns_stable_for_consistent_runs(db_path) -> None:
    memory = EpisodicMemory(db_path)
    for index in range(5):
        memory.save_episode(
            Episode(
                run_id=f"run-{index}",
                task=f"task {index}",
                status="completed",
                steps_taken=1,
                tools_used=["list_files"],
                success_rate=0.8,
                final_output_summary="ok",
                reflection="ok",
                lessons=[],
                duration_seconds=1.0,
                timestamp=datetime.now(timezone.utc) + timedelta(seconds=index),
                tags=[],
            )
        )
    trend = ReflectionEngine(memory).get_performance_trend(last_n=5)

    assert trend["trend"] == "stable"


def test_get_performance_trend_returns_degrading_appropriately(db_path) -> None:
    memory = EpisodicMemory(db_path)
    base = datetime.now(timezone.utc)
    for index in range(6):
        memory.save_episode(
            Episode(
                run_id=f"run-{index}",
                task=f"task {index}",
                status="completed",
                steps_taken=1,
                tools_used=["list_files"],
                success_rate=1.0 if index == 0 else 0.1,
                final_output_summary="ok",
                reflection="ok",
                lessons=[],
                duration_seconds=1.0,
                timestamp=base + timedelta(seconds=index),
                tags=[],
            )
        )
    trend = ReflectionEngine(memory).get_performance_trend(last_n=6)

    assert trend["trend"] == "degrading"
