from __future__ import annotations

from typing import Any

from memory.store import ExperienceStore


class ExperienceRetrieval:
    """Retrieve simple task-matched experience hints for planning."""

    def __init__(self, store: ExperienceStore | None = None) -> None:
        self.store = store or ExperienceStore()

    def summarize_for_task(self, task: str) -> dict[str, Any]:
        entries = self.store.load()
        similar = self._similar_entries(task, entries)
        tool_stats = self.store.get_tool_stats(entries)
        similar_tool_scores = self._similar_tool_scores(similar)

        best_tool, best_score = self._best_tool(similar_tool_scores)
        failed_tool, failed_score = self._failed_tool(similar_tool_scores)
        preferred_tools = self._preferred_tools(tool_stats)
        avoided_tools = self._avoided_tools(tool_stats)

        summary_lines = []
        if best_tool is not None:
            summary_lines.append(f"- Best tool: {best_tool} (score {best_score:.2f})")
        else:
            summary_lines.append("- Best tool: none")
        if failed_tool is not None:
            summary_lines.append(f"- Failed tool: {failed_tool} (score {failed_score:.2f})")
        else:
            summary_lines.append("- Failed tool: none")
        if preferred_tools:
            summary_lines.append(f"- Preferred tools: {', '.join(preferred_tools[:3])}")
        if avoided_tools:
            summary_lines.append(f"- Avoid tools: {', '.join(avoided_tools[:3])}")

        return {
            "memory_hit": bool(similar),
            "similar_count": len(similar),
            "best_tool": best_tool,
            "best_score": best_score,
            "failed_tool": failed_tool,
            "failed_score": failed_score,
            "preferred_tools": preferred_tools,
            "avoided_tools": avoided_tools,
            "tool_stats": tool_stats,
            "summary": "\n".join(summary_lines),
        }

    def _similar_entries(
        self,
        task: str,
        entries: list[dict[str, Any]],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            candidate_task = entry.get("task")
            if not isinstance(candidate_task, str) or not candidate_task.strip():
                continue
            similarity = self._similarity(task, candidate_task)
            if similarity >= 0.2:
                scored.append((similarity, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        left_normalized = left.strip().casefold()
        right_normalized = right.strip().casefold()
        if not left_normalized or not right_normalized:
            return 0.0
        if left_normalized == right_normalized:
            return 1.0
        if left_normalized in right_normalized or right_normalized in left_normalized:
            return 0.85
        left_words = {word for word in left_normalized.split() if word}
        right_words = {word for word in right_normalized.split() if word}
        if not left_words or not right_words:
            return 0.0
        overlap = len(left_words & right_words)
        return overlap / max(len(left_words), len(right_words))

    @staticmethod
    def _similar_tool_scores(entries: list[dict[str, Any]]) -> dict[str, list[float]]:
        scores: dict[str, list[float]] = {}
        for entry in entries:
            tool = entry.get("tool")
            score = entry.get("score")
            if not isinstance(tool, str) or not isinstance(score, (int, float)):
                continue
            scores.setdefault(tool, []).append(float(score))
        return scores

    @staticmethod
    def _best_tool(tool_scores: dict[str, list[float]]) -> tuple[str | None, float]:
        ranked = [
            (tool, sum(scores) / len(scores))
            for tool, scores in tool_scores.items()
            if scores and (sum(scores) / len(scores)) >= 0.6
        ]
        if not ranked:
            return None, 0.0
        best_tool, best_score = max(ranked, key=lambda item: item[1])
        return best_tool, best_score

    @staticmethod
    def _failed_tool(tool_scores: dict[str, list[float]]) -> tuple[str | None, float]:
        ranked = [
            (tool, sum(scores) / len(scores))
            for tool, scores in tool_scores.items()
            if scores and (sum(scores) / len(scores)) < 0.5
        ]
        if not ranked:
            return None, 0.0
        failed_tool, failed_score = min(ranked, key=lambda item: item[1])
        return failed_tool, failed_score

    @staticmethod
    def _preferred_tools(tool_stats: dict[str, dict[str, int]]) -> list[str]:
        ranked: list[tuple[float, str]] = []
        for tool, stats in tool_stats.items():
            success_count = int(stats.get("success_count", 0))
            fail_count = int(stats.get("fail_count", 0))
            total = success_count + fail_count
            if total == 0:
                continue
            ranked.append((success_count / total, tool))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [tool for _, tool in ranked]

    @staticmethod
    def _avoided_tools(tool_stats: dict[str, dict[str, int]]) -> list[str]:
        avoided: list[str] = []
        for tool, stats in tool_stats.items():
            success_count = int(stats.get("success_count", 0))
            fail_count = int(stats.get("fail_count", 0))
            if fail_count > max(success_count, 1):
                avoided.append(tool)
        return avoided
