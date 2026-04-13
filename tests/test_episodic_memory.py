from __future__ import annotations

from datetime import datetime, timedelta, timezone

from friday.memory.episodic import Episode, EpisodicMemory


def _episode(task: str, status: str = "completed", tools: list[str] | None = None, success_rate: float = 1.0) -> Episode:
    return Episode(
        run_id=f"run-{task}",
        task=task,
        status=status,
        steps_taken=2,
        tools_used=tools or ["list_files"],
        success_rate=success_rate,
        final_output_summary="output",
        reflection="reflection",
        lessons=["lesson one"],
        duration_seconds=1.5,
        timestamp=datetime.now(timezone.utc),
        tags=["file_ops"],
    )


def test_save_episode_persists_and_retrieves_correctly(db_path) -> None:
    memory = EpisodicMemory(db_path)
    episode = _episode("list files in workspace")
    memory.save_episode(episode)

    recent = memory.get_recent_episodes(limit=1)

    assert recent[0].run_id == episode.run_id
    assert recent[0].task == episode.task


def test_get_similar_tasks_returns_highest_scoring_match_first(db_path) -> None:
    memory = EpisodicMemory(db_path)
    memory.save_episode(_episode("list files in workspace"))
    memory.save_episode(_episode("read sample text"))

    matches = memory.get_similar_tasks("list files", limit=2)

    assert matches[0].task == "list files in workspace"


def test_get_similar_tasks_returns_empty_for_empty_memory(db_path) -> None:
    memory = EpisodicMemory(db_path)
    assert memory.get_similar_tasks("list files") == []


def test_get_recent_episodes_respects_limit(db_path) -> None:
    memory = EpisodicMemory(db_path)
    base = datetime.now(timezone.utc)
    for index in range(3):
        episode = _episode(f"task {index}")
        episode.timestamp = base + timedelta(seconds=index)
        memory.save_episode(episode)

    recent = memory.get_recent_episodes(limit=2)

    assert len(recent) == 2
    assert recent[0].task == "task 2"


def test_get_successful_episodes_filters_by_status_completed(db_path) -> None:
    memory = EpisodicMemory(db_path)
    memory.save_episode(_episode("success", status="completed", success_rate=1.0))
    memory.save_episode(_episode("failed", status="aborted", success_rate=0.0))

    successful = memory.get_successful_episodes(limit=10)

    assert [episode.task for episode in successful] == ["success"]


def test_get_episodes_by_tool_filters_correctly(db_path) -> None:
    memory = EpisodicMemory(db_path)
    memory.save_episode(_episode("files", tools=["list_files"]))
    memory.save_episode(_episode("http", tools=["http_get"]))

    matches = memory.get_episodes_by_tool("http_get")

    assert [episode.task for episode in matches] == ["http"]


def test_get_stats_returns_correct_totals_and_averages(db_path) -> None:
    memory = EpisodicMemory(db_path)
    memory.save_episode(_episode("task one", success_rate=1.0, tools=["list_files", "read_file"]))
    memory.save_episode(_episode("task two", status="aborted", success_rate=0.0, tools=["http_get"]))

    stats = memory.get_stats()

    assert stats["total_episodes"] == 2
    assert stats["completed"] == 1
    assert stats["aborted"] == 1
    assert stats["avg_success_rate"] == 0.5


def test_success_rate_stored_and_retrieved_as_float(db_path) -> None:
    memory = EpisodicMemory(db_path)
    episode = _episode("task", success_rate=0.75)
    memory.save_episode(episode)

    loaded = memory.get_recent_episodes(limit=1)[0]

    assert isinstance(loaded.success_rate, float)
    assert loaded.success_rate == 0.75
