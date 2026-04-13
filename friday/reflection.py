from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from planner import AgentState
from storage import StepRecord

from friday.memory.episodic import Episode, EpisodicMemory


class ReflectionEngine:
    """Analyze completed runs and extract deterministic lessons."""

    def __init__(self, episodic: EpisodicMemory) -> None:
        self.episodic = episodic

    def reflect(self, state: AgentState, history: list[StepRecord]) -> Episode:
        steps_taken = len(history)
        success_count = sum(1 for record in history if record.verification_status == "SUCCESS")
        _failure_count = sum(1 for record in history if record.verification_status == "FAILURE")
        _unverified_count = sum(1 for record in history if record.verification_status == "UNVERIFIED")
        success_rate = (success_count / steps_taken) if steps_taken else 0.0
        tools_used = [record.tool_name for record in history]
        total_duration = sum(record.duration_seconds for record in history)
        last_output_summary = (history[-1].output_summary if history else "")[:300]

        failure_tools = [record.tool_name for record in history if record.verification_status == "FAILURE"]
        most_common_failure_tool = Counter(failure_tools).most_common(1)[0][0] if failure_tools else None
        timed_out = any((record.error or "").lower().find("timed out") >= 0 for record in history)

        lessons: list[str] = []
        if success_rate < 0.5:
            lessons.append(
                f"Task '{state.task}' had low success rate consider different tool order"
            )
        if state.replans > 0:
            lessons.append(
                f"Required {state.replans} replan(s) initial plan was insufficient"
            )
        if timed_out:
            lessons.append(
                "Execution timeouts detected reduce scope or increase timeout"
            )
        if state.status == "completed" and state.retries == 0:
            lessons.append(
                "Clean run with zero retries this approach works well"
            )
        if most_common_failure_tool:
            lessons.append(
                f"Tool '{most_common_failure_tool}' failed repeatedly verify parameters"
            )

        reflection = (
            f"Run {state.run_id}: {state.status} in "
            f"{steps_taken} steps. "
            f"Success rate: {success_rate:.0%}. "
            f"Tools: {', '.join(tools_used) if tools_used else 'none'}. "
            f"Lessons: {len(lessons)} extracted."
        )

        tags: list[str] = []
        if any(tool in {"read_file", "write_file", "list_files"} for tool in tools_used):
            tags.append("file_ops")
        if "http_get" in tools_used:
            tags.append("http")
        if "parse_csv" in tools_used:
            tags.append("data")
        if state.status == "aborted":
            tags.append("failed")
        if state.status == "completed" and state.retries == 0:
            tags.append("clean_run")

        episode = Episode(
            run_id=state.run_id,
            task=state.task,
            status=state.status,
            steps_taken=steps_taken,
            tools_used=tools_used,
            success_rate=success_rate,
            final_output_summary=last_output_summary,
            reflection=reflection,
            lessons=lessons,
            duration_seconds=total_duration,
            timestamp=datetime.now(timezone.utc),
            tags=tags,
        )
        self.episodic.save_episode(episode)
        return episode

    def get_performance_trend(self, last_n: int = 20) -> dict[str, Any]:
        episodes = self.episodic.get_recent_episodes(limit=last_n)
        if not episodes:
            return {
                "trend": "stable",
                "avg_success_rate_recent": 0.0,
                "avg_success_rate_overall": 0.0,
                "most_common_failure": None,
                "best_performing_tool": None,
                "recommendation": "Run more tasks so Friday can learn from experience.",
            }

        recent_slice = episodes[:5]
        avg_success_rate_recent = sum(episode.success_rate for episode in recent_slice) / len(recent_slice)
        avg_success_rate_overall = sum(episode.success_rate for episode in episodes) / len(episodes)
        if avg_success_rate_recent > avg_success_rate_overall + 0.1:
            trend = "improving"
            recommendation = "Recent runs are stronger. Keep using the successful patterns Friday has learned."
        elif avg_success_rate_recent < avg_success_rate_overall - 0.1:
            trend = "degrading"
            recommendation = "Recent runs are weaker. Review repeated failures and simplify first-step tool choice."
        else:
            trend = "stable"
            recommendation = "Performance is stable. Continue collecting episodes to strengthen memory-guided planning."

        failure_counter = Counter()
        tool_scores: dict[str, list[float]] = {}
        for episode in episodes:
            if episode.status != "completed":
                for lesson in episode.lessons:
                    failure_counter[lesson] += 1
            for tool in episode.tools_used:
                tool_scores.setdefault(tool, []).append(episode.success_rate)

        best_performing_tool = None
        if tool_scores:
            best_performing_tool = max(
                tool_scores,
                key=lambda tool: (sum(tool_scores[tool]) / len(tool_scores[tool]), len(tool_scores[tool])),
            )

        return {
            "trend": trend,
            "avg_success_rate_recent": avg_success_rate_recent,
            "avg_success_rate_overall": avg_success_rate_overall,
            "most_common_failure": failure_counter.most_common(1)[0][0] if failure_counter else None,
            "best_performing_tool": best_performing_tool,
            "recommendation": recommendation,
        }
