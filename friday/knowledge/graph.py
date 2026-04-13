from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from friday.memory.episodic import Episode


class KnowledgeNode(BaseModel):
    node_id: str = Field(default_factory=lambda: str(uuid4()))
    node_type: str
    label: str
    properties: dict[str, Any]
    confidence: float
    created_at: datetime
    updated_at: datetime
    observation_count: int


class KnowledgeEdge(BaseModel):
    edge_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    target_id: str
    relation: str
    weight: float
    created_at: datetime


class KnowledgeGraph:
    """SQLite-backed graph of tools, lessons, and task patterns."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kg_nodes (
                  node_id TEXT PRIMARY KEY,
                  node_type TEXT NOT NULL,
                  label TEXT NOT NULL,
                  properties TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  observation_count INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kg_edges (
                  edge_id TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL,
                  target_id TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  weight REAL NOT NULL DEFAULT 1.0,
                  created_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON kg_nodes(node_type);"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges(source_id);"
            )
            connection.commit()

    def add_or_update_node(self, node_type: str, label: str, properties: dict) -> KnowledgeNode:
        now = datetime.now(timezone.utc)
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT node_id, properties, observation_count, created_at
                FROM kg_nodes
                WHERE node_type = ? AND label = ?;
                """,
                (node_type, label),
            ).fetchone()
            if row is None:
                node = KnowledgeNode(
                    node_type=node_type,
                    label=label,
                    properties=dict(properties),
                    confidence=0.1,
                    created_at=now,
                    updated_at=now,
                    observation_count=1,
                )
                connection.execute(
                    """
                    INSERT INTO kg_nodes (
                      node_id, node_type, label, properties, confidence,
                      created_at, updated_at, observation_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        node.node_id,
                        node.node_type,
                        node.label,
                        json.dumps(node.properties, sort_keys=True),
                        node.confidence,
                        node.created_at.isoformat(),
                        node.updated_at.isoformat(),
                        node.observation_count,
                    ),
                )
                connection.commit()
                return node

            existing_properties = json.loads(str(row[1]))
            observation_count = int(row[2]) + 1
            merged_properties = self._merge_properties(existing_properties, properties, observation_count)
            confidence = min(1.0, observation_count / 10.0)
            connection.execute(
                """
                UPDATE kg_nodes
                SET properties = ?, confidence = ?, updated_at = ?, observation_count = ?
                WHERE node_id = ?;
                """,
                (
                    json.dumps(merged_properties, sort_keys=True),
                    confidence,
                    now.isoformat(),
                    observation_count,
                    str(row[0]),
                ),
            )
            connection.commit()
            return KnowledgeNode(
                node_id=str(row[0]),
                node_type=node_type,
                label=label,
                properties=merged_properties,
                confidence=confidence,
                created_at=datetime.fromisoformat(str(row[3])),
                updated_at=now,
                observation_count=observation_count,
            )

    def add_or_update_edge(self, source_label: str, target_label: str, relation: str) -> KnowledgeEdge:
        source = self._ensure_node_for_label(source_label)
        target = self._ensure_node_for_label(target_label)
        now = datetime.now(timezone.utc)
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT edge_id, weight, created_at
                FROM kg_edges
                WHERE source_id = ? AND target_id = ? AND relation = ?;
                """,
                (source.node_id, target.node_id, relation),
            ).fetchone()
            if row is None:
                edge = KnowledgeEdge(
                    source_id=source.node_id,
                    target_id=target.node_id,
                    relation=relation,
                    weight=0.1,
                    created_at=now,
                )
                connection.execute(
                    """
                    INSERT INTO kg_edges (edge_id, source_id, target_id, relation, weight, created_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (
                        edge.edge_id,
                        edge.source_id,
                        edge.target_id,
                        edge.relation,
                        edge.weight,
                        edge.created_at.isoformat(),
                    ),
                )
                connection.commit()
                return edge

            weight = min(1.0, float(row[1]) + 0.1)
            connection.execute(
                """
                UPDATE kg_edges
                SET weight = ?
                WHERE edge_id = ?;
                """,
                (weight, str(row[0])),
            )
            connection.commit()
            return KnowledgeEdge(
                edge_id=str(row[0]),
                source_id=source.node_id,
                target_id=target.node_id,
                relation=relation,
                weight=weight,
                created_at=datetime.fromisoformat(str(row[2])),
            )

    def learn_from_episode(self, episode: Episode) -> None:
        self.add_or_update_node(
            "task_pattern",
            episode.task,
            {"status": episode.status, "success_rate": episode.success_rate},
        )
        for tool_name in episode.tools_used:
            self.add_or_update_node(
                "tool",
                tool_name,
                {"success_rate": episode.success_rate, "last_status": episode.status},
            )
        for lesson in episode.lessons:
            self.add_or_update_node("lesson", lesson[:100], {})

        if episode.tools_used:
            self.add_or_update_edge(episode.task, episode.tools_used[0], "SOLVES")
        if episode.status == "completed":
            for tool_a, tool_b in zip(episode.tools_used, episode.tools_used[1:]):
                self.add_or_update_edge(tool_a, tool_b, "FOLLOWS")
        if episode.tools_used:
            last_tool = episode.tools_used[-1]
            for lesson in episode.lessons:
                self.add_or_update_edge(last_tool, lesson[:100], "CAUSES")

    def get_tool_insights(self, tool_name: str) -> dict[str, Any]:
        tool_node = self._get_node("tool", tool_name)
        if tool_node is None:
            return {
                "tool_name": tool_name,
                "observation_count": 0,
                "confidence": 0.0,
                "avg_success_rate": 0.0,
                "commonly_follows": [],
                "commonly_precedes": [],
                "associated_lessons": [],
            }

        properties = tool_node.properties
        outgoing = self._get_edges_for_node(tool_node.node_id, direction="out")
        incoming = self._get_edges_for_node(tool_node.node_id, direction="in")
        follows = [self._label_for_node_id(edge.source_id) for edge in incoming if edge.relation == "FOLLOWS"]
        precedes = [self._label_for_node_id(edge.target_id) for edge in outgoing if edge.relation == "FOLLOWS"]
        associated_lessons = [self._label_for_node_id(edge.target_id) for edge in outgoing if edge.relation == "CAUSES"]
        return {
            "tool_name": tool_name,
            "observation_count": tool_node.observation_count,
            "confidence": tool_node.confidence,
            "avg_success_rate": float(properties.get("avg_success_rate", properties.get("success_rate", 0.0))),
            "commonly_follows": [label for label in follows if label],
            "commonly_precedes": [label for label in precedes if label],
            "associated_lessons": [label for label in associated_lessons if label],
        }

    def get_recommended_sequence(self, task_keywords: list[str]) -> list[str]:
        if not task_keywords:
            return []
        keyword_set = {keyword.lower() for keyword in task_keywords}
        with sqlite3.connect(self.db_path) as connection:
            task_rows = connection.execute(
                """
                SELECT node_id, label
                FROM kg_nodes
                WHERE node_type = 'task_pattern';
                """
            ).fetchall()
        matching_task_ids = [
            str(node_id)
            for node_id, label in task_rows
            if keyword_set & {word.lower() for word in str(label).split()}
        ]
        if not matching_task_ids:
            return []

        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT source_id, target_id, relation, weight
                FROM kg_edges;
                """
            ).fetchall()
        tool_scores: Counter[str] = Counter()
        follow_scores: Counter[str] = Counter()
        for source_id, target_id, relation, weight in rows:
            if relation == "SOLVES" and str(source_id) in matching_task_ids:
                target_label = self._label_for_node_id(str(target_id))
                if target_label:
                    tool_scores[target_label] += float(weight)
            if relation == "FOLLOWS":
                source_label = self._label_for_node_id(str(source_id))
                target_label = self._label_for_node_id(str(target_id))
                if source_label and target_label:
                    follow_scores[f"{source_label}|{target_label}"] += float(weight)

        if not tool_scores:
            return []
        ordered = [tool for tool, _ in tool_scores.most_common()]
        if ordered:
            first_tool = ordered[0]
            for pair, _ in follow_scores.most_common():
                source_label, target_label = pair.split("|", 1)
                if source_label == first_tool and target_label not in ordered:
                    ordered.append(target_label)
        return ordered

    def summarize(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as connection:
            node_rows = connection.execute(
                "SELECT node_type, label, observation_count FROM kg_nodes;"
            ).fetchall()
            edge_count = connection.execute(
                "SELECT COUNT(*) FROM kg_edges;"
            ).fetchone()
        tool_counter = Counter(label for node_type, label, _ in node_rows if node_type == "tool")
        lesson_counter = Counter(label for node_type, label, _ in node_rows if node_type == "lesson")
        return {
            "total_nodes": len(node_rows),
            "total_edges": int(edge_count[0] if edge_count else 0),
            "tool_count": sum(1 for node_type, _, _ in node_rows if node_type == "tool"),
            "lesson_count": sum(1 for node_type, _, _ in node_rows if node_type == "lesson"),
            "top_tools": [label for label, _ in tool_counter.most_common(5)],
            "top_lessons": [label for label, _ in lesson_counter.most_common(5)],
        }

    @staticmethod
    def _merge_properties(existing: dict[str, Any], incoming: dict[str, Any], observation_count: int) -> dict[str, Any]:
        merged = dict(existing)
        for key, value in incoming.items():
            if key == "success_rate":
                previous_avg = float(existing.get("avg_success_rate", existing.get("success_rate", value)))
                previous_count = max(observation_count - 1, 1)
                merged["avg_success_rate"] = ((previous_avg * previous_count) + float(value)) / observation_count
                merged["success_rate"] = float(value)
            else:
                merged[key] = value
        return merged

    def _ensure_node_for_label(self, label: str) -> KnowledgeNode:
        existing = self._get_node_by_label(label)
        if existing is not None:
            return existing
        inferred_type = "lesson" if " " in label else "tool"
        return self.add_or_update_node(inferred_type, label, {})

    def _get_node(self, node_type: str, label: str) -> KnowledgeNode | None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT node_id, node_type, label, properties, confidence,
                       created_at, updated_at, observation_count
                FROM kg_nodes
                WHERE node_type = ? AND label = ?;
                """,
                (node_type, label),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def _get_node_by_label(self, label: str) -> KnowledgeNode | None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT node_id, node_type, label, properties, confidence,
                       created_at, updated_at, observation_count
                FROM kg_nodes
                WHERE label = ?
                ORDER BY observation_count DESC
                LIMIT 1;
                """,
                (label,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def _get_edges_for_node(self, node_id: str, direction: str) -> list[KnowledgeEdge]:
        column = "source_id" if direction == "out" else "target_id"
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT edge_id, source_id, target_id, relation, weight, created_at
                FROM kg_edges
                WHERE {column} = ?;
                """,
                (node_id,),
            ).fetchall()
        return [self._row_to_edge(row) for row in rows]

    def _label_for_node_id(self, node_id: str) -> str | None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT label FROM kg_nodes WHERE node_id = ?;",
                (node_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _row_to_node(row: tuple[Any, ...]) -> KnowledgeNode:
        return KnowledgeNode(
            node_id=str(row[0]),
            node_type=str(row[1]),
            label=str(row[2]),
            properties=json.loads(str(row[3])),
            confidence=float(row[4]),
            created_at=datetime.fromisoformat(str(row[5])),
            updated_at=datetime.fromisoformat(str(row[6])),
            observation_count=int(row[7]),
        )

    @staticmethod
    def _row_to_edge(row: tuple[Any, ...]) -> KnowledgeEdge:
        return KnowledgeEdge(
            edge_id=str(row[0]),
            source_id=str(row[1]),
            target_id=str(row[2]),
            relation=str(row[3]),
            weight=float(row[4]),
            created_at=datetime.fromisoformat(str(row[5])),
        )
