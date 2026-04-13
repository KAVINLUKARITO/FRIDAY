from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    SentenceTransformer = None


class Episode(BaseModel):
    episode_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    task: str
    task_embedding: list[float] | None = None
    status: str
    steps_taken: int
    tools_used: list[str]
    success_rate: float
    final_output_summary: str
    reflection: str
    lessons: list[str]
    duration_seconds: float
    timestamp: datetime
    tags: list[str]


class EpisodicMemory:
    """Persist and query structured run summaries."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._embedding_model = None
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                  episode_id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  task TEXT NOT NULL,
                  task_embedding BLOB,
                  status TEXT NOT NULL,
                  steps_taken INTEGER,
                  tools_used TEXT,
                  success_rate REAL,
                  final_output_summary TEXT,
                  reflection TEXT,
                  lessons TEXT,
                  duration_seconds REAL,
                  timestamp TEXT NOT NULL,
                  tags TEXT
                );
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_episodes_status
                  ON episodes(status);
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_episodes_timestamp
                  ON episodes(timestamp);
                """
            )
            connection.commit()

    def save_episode(self, episode: Episode) -> None:
        stored_episode = episode.model_copy(deep=True)
        if stored_episode.task_embedding is None:
            stored_episode.task_embedding = self._embed_task(stored_episode.task)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO episodes (
                  episode_id,
                  run_id,
                  task,
                  task_embedding,
                  status,
                  steps_taken,
                  tools_used,
                  success_rate,
                  final_output_summary,
                  reflection,
                  lessons,
                  duration_seconds,
                  timestamp,
                  tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    stored_episode.episode_id,
                    stored_episode.run_id,
                    stored_episode.task,
                    json.dumps(stored_episode.task_embedding),
                    stored_episode.status,
                    stored_episode.steps_taken,
                    json.dumps(stored_episode.tools_used),
                    stored_episode.success_rate,
                    stored_episode.final_output_summary,
                    stored_episode.reflection,
                    json.dumps(stored_episode.lessons),
                    stored_episode.duration_seconds,
                    stored_episode.timestamp.isoformat(),
                    json.dumps(stored_episode.tags),
                ),
            )
            connection.commit()

    def get_similar_tasks(self, task: str, limit: int = 5) -> list[Episode]:
        try:
            episodes = self._load_all_episodes()
            if not episodes:
                return []
            query_embedding = self._embed_task(task)
            if query_embedding is not None:
                scored = [
                    (self._cosine_similarity(query_embedding, episode.task_embedding), episode)
                    for episode in episodes
                    if episode.task_embedding is not None
                ]
            else:
                task_words = self._task_words(task)
                scored = [
                    (self._word_similarity(task_words, self._task_words(episode.task)), episode)
                    for episode in episodes
                ]
            filtered = [item for item in scored if item[0] > 0.0]
            filtered.sort(key=lambda item: (item[0], item[1].success_rate, item[1].timestamp), reverse=True)
            return [episode for _, episode in filtered[:limit]]
        except Exception:
            return []

    def get_recent_episodes(self, limit: int = 10) -> list[Episode]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT episode_id, run_id, task, task_embedding, status, steps_taken,
                       tools_used, success_rate, final_output_summary, reflection,
                       lessons, duration_seconds, timestamp, tags
                FROM episodes
                ORDER BY timestamp DESC
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_episode(row) for row in rows]

    def get_successful_episodes(self, limit: int = 10) -> list[Episode]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT episode_id, run_id, task, task_embedding, status, steps_taken,
                       tools_used, success_rate, final_output_summary, reflection,
                       lessons, duration_seconds, timestamp, tags
                FROM episodes
                WHERE status = 'completed'
                ORDER BY success_rate DESC, timestamp DESC
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_episode(row) for row in rows]

    def get_episodes_by_tool(self, tool_name: str) -> list[Episode]:
        matches: list[Episode] = []
        for episode in self._load_all_episodes():
            if tool_name in episode.tools_used:
                matches.append(episode)
        return matches

    def get_stats(self) -> dict[str, Any]:
        episodes = self._load_all_episodes()
        if not episodes:
            return {
                "total_episodes": 0,
                "completed": 0,
                "aborted": 0,
                "avg_success_rate": 0.0,
                "most_used_tools": [],
                "avg_steps": 0.0,
                "avg_duration": 0.0,
            }
        tool_counter = Counter(tool for episode in episodes for tool in episode.tools_used)
        return {
            "total_episodes": len(episodes),
            "completed": sum(1 for episode in episodes if episode.status == "completed"),
            "aborted": sum(1 for episode in episodes if episode.status == "aborted"),
            "avg_success_rate": sum(episode.success_rate for episode in episodes) / len(episodes),
            "most_used_tools": [tool for tool, _ in tool_counter.most_common(5)],
            "avg_steps": sum(episode.steps_taken for episode in episodes) / len(episodes),
            "avg_duration": sum(episode.duration_seconds for episode in episodes) / len(episodes),
        }

    def _load_all_episodes(self) -> list[Episode]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT episode_id, run_id, task, task_embedding, status, steps_taken,
                       tools_used, success_rate, final_output_summary, reflection,
                       lessons, duration_seconds, timestamp, tags
                FROM episodes
                ORDER BY timestamp DESC;
                """
            ).fetchall()
        return [self._row_to_episode(row) for row in rows]

    def _embed_task(self, task: str) -> list[float] | None:
        if SentenceTransformer is None:
            return None
        try:
            if self._embedding_model is None:
                self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            embedding = self._embedding_model.encode(task)
            return [float(value) for value in embedding]
        except Exception:
            return None

    @staticmethod
    def _task_words(task: str) -> set[str]:
        return {word.strip(".,!?:;").lower() for word in task.split() if word.strip()}

    @staticmethod
    def _word_similarity(task_words: set[str], episode_words: set[str]) -> float:
        if not task_words or not episode_words:
            return 0.0
        matching_words = len(task_words & episode_words)
        return matching_words / max(len(task_words), len(episode_words))

    @staticmethod
    def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
        if left is None or right is None or not left or not right or len(left) != len(right):
            return 0.0
        dot_product = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return dot_product / (left_norm * right_norm)

    @staticmethod
    def _row_to_episode(row: tuple[Any, ...]) -> Episode:
        return Episode(
            episode_id=str(row[0]),
            run_id=str(row[1]),
            task=str(row[2]),
            task_embedding=json.loads(row[3]) if row[3] else None,
            status=str(row[4]),
            steps_taken=int(row[5] or 0),
            tools_used=json.loads(row[6] or "[]"),
            success_rate=float(row[7] or 0.0),
            final_output_summary=str(row[8] or ""),
            reflection=str(row[9] or ""),
            lessons=json.loads(row[10] or "[]"),
            duration_seconds=float(row[11] or 0.0),
            timestamp=datetime.fromisoformat(str(row[12])),
            tags=json.loads(row[13] or "[]"),
        )
