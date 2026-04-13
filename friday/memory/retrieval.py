from __future__ import annotations

from collections import Counter
from typing import Any

from friday.memory.episodic import Episode, EpisodicMemory


class RetrievalEngine:
    """Query episodic memory for task-aware planning hints."""

    def __init__(self, episodic: EpisodicMemory) -> None:
        self.episodic = episodic

    def get_context_for_task(self, task: str) -> dict[str, Any]:
        similar = self.episodic.get_similar_tasks(task, limit=5)
        if not similar:
            return {
                "similar_past_tasks": [],
                "recommended_tools": [],
                "known_pitfalls": [],
                "estimated_steps": 0,
                "confidence": 0.0,
            }

        task_words = self._task_words(task)
        similarities = [self._episode_similarity(task_words, episode) for episode in similar]
        completed = [episode for episode in similar if episode.status == "completed"]
        tool_counter = Counter(
            tool
            for episode in completed
            for tool in episode.tools_used
        )
        known_pitfalls = []
        for episode in similar:
            if episode.status != "completed":
                known_pitfalls.extend(episode.lessons)
        deduped_pitfalls = list(dict.fromkeys(known_pitfalls))
        estimated_steps = round(sum(episode.steps_taken for episode in similar) / len(similar))

        return {
            "similar_past_tasks": [
                {
                    "task": episode.task,
                    "status": episode.status,
                    "tools_used": episode.tools_used,
                    "lessons": episode.lessons,
                    "success_rate": episode.success_rate,
                }
                for episode in similar
            ],
            "recommended_tools": [tool for tool, _ in tool_counter.most_common(5)],
            "known_pitfalls": deduped_pitfalls,
            "estimated_steps": estimated_steps,
            "confidence": max(similarities) if similarities else 0.0,
        }

    def get_recommended_first_action(self, task: str) -> str | None:
        similar = self.episodic.get_similar_tasks(task, limit=5)
        completed = [episode for episode in similar if episode.status == "completed" and episode.tools_used]
        if not completed:
            return None
        best = max(completed, key=lambda episode: (episode.success_rate, episode.timestamp))
        return best.tools_used[0]

    def summarize_memory(self) -> str:
        stats = self.episodic.get_stats()
        common_tools = ", ".join(stats.get("most_used_tools", [])[:3]) or "none yet"
        success_rate = float(stats.get("avg_success_rate", 0.0)) * 100.0
        recent_lessons = []
        for episode in self.episodic.get_recent_episodes(limit=5):
            recent_lessons.extend(episode.lessons)
        common_lessons = ", ".join(list(dict.fromkeys(recent_lessons))[:3]) or "no lessons recorded yet"
        return (
            f"Friday has completed {stats.get('total_episodes', 0)} tasks. "
            f"Most used tools: {common_tools}. "
            f"Success rate: {success_rate:.0f}%. "
            f"Common lessons: {common_lessons}"
        )

    @staticmethod
    def _task_words(task: str) -> set[str]:
        return {word.strip(".,!?:;").lower() for word in task.split() if word.strip()}

    def _episode_similarity(self, task_words: set[str], episode: Episode) -> float:
        episode_words = self._task_words(episode.task)
        if not task_words or not episode_words:
            return 0.0
        matches = len(task_words & episode_words)
        return matches / max(len(task_words), len(episode_words))
