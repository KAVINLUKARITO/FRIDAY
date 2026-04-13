from __future__ import annotations

from datetime import datetime, timezone

from friday.knowledge.graph import KnowledgeGraph
from friday.memory.episodic import Episode


def _episode() -> Episode:
    return Episode(
        run_id="run-1",
        task="list files and read sample",
        status="completed",
        steps_taken=2,
        tools_used=["list_files", "read_file"],
        success_rate=1.0,
        final_output_summary="output",
        reflection="reflection",
        lessons=["always check path exists first"],
        duration_seconds=1.0,
        timestamp=datetime.now(timezone.utc),
        tags=["file_ops", "clean_run"],
    )


def test_add_or_update_node_creates_new_node_correctly(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    node = graph.add_or_update_node("tool", "list_files", {"success_rate": 1.0})

    assert node.label == "list_files"
    assert node.observation_count == 1


def test_add_or_update_node_increments_observation_count_on_repeat(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.add_or_update_node("tool", "list_files", {"success_rate": 1.0})
    node = graph.add_or_update_node("tool", "list_files", {"success_rate": 0.5})

    assert node.observation_count == 2


def test_confidence_increases_with_observation_count(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    first = graph.add_or_update_node("tool", "list_files", {})
    second = graph.add_or_update_node("tool", "list_files", {})

    assert second.confidence > first.confidence


def test_confidence_never_exceeds_one(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    node = None
    for _ in range(20):
        node = graph.add_or_update_node("tool", "list_files", {})

    assert node is not None
    assert node.confidence == 1.0


def test_add_or_update_edge_creates_edge_with_weight_point_one(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.add_or_update_node("tool", "list_files", {})
    graph.add_or_update_node("tool", "read_file", {})
    edge = graph.add_or_update_edge("list_files", "read_file", "FOLLOWS")

    assert edge.weight == 0.1


def test_add_or_update_edge_increments_weight_on_repeat(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.add_or_update_node("tool", "list_files", {})
    graph.add_or_update_node("tool", "read_file", {})
    graph.add_or_update_edge("list_files", "read_file", "FOLLOWS")
    edge = graph.add_or_update_edge("list_files", "read_file", "FOLLOWS")

    assert edge.weight == 0.2


def test_weight_never_exceeds_one(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.add_or_update_node("tool", "list_files", {})
    graph.add_or_update_node("tool", "read_file", {})
    edge = None
    for _ in range(20):
        edge = graph.add_or_update_edge("list_files", "read_file", "FOLLOWS")

    assert edge is not None
    assert edge.weight == 1.0


def test_learn_from_episode_creates_tool_nodes(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.learn_from_episode(_episode())

    summary = graph.summarize()

    assert summary["tool_count"] >= 2


def test_learn_from_episode_creates_follows_edges_for_tool_pairs(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.learn_from_episode(_episode())

    insights = graph.get_tool_insights("list_files")

    assert "read_file" in insights["commonly_precedes"]


def test_get_tool_insights_returns_correct_data_for_known_tool(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.learn_from_episode(_episode())

    insights = graph.get_tool_insights("list_files")

    assert insights["tool_name"] == "list_files"
    assert insights["observation_count"] >= 1


def test_get_tool_insights_returns_empty_data_for_unknown_tool(db_path) -> None:
    graph = KnowledgeGraph(db_path)

    insights = graph.get_tool_insights("missing_tool")

    assert insights["observation_count"] == 0


def test_summarize_returns_correct_node_and_edge_counts(db_path) -> None:
    graph = KnowledgeGraph(db_path)
    graph.learn_from_episode(_episode())

    summary = graph.summarize()

    assert summary["total_nodes"] >= 3
    assert summary["total_edges"] >= 2
