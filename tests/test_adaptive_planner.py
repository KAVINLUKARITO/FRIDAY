from __future__ import annotations

from dataclasses import dataclass

from friday.planner import AdaptivePlanner
from planner import AgentState


@dataclass
class RetrievalDouble:
    context: dict

    def get_context_for_task(self, task: str) -> dict:
        return dict(self.context)


def test_plan_returns_memory_guided_action_when_confidence_high() -> None:
    planner = AdaptivePlanner(
        RetrievalDouble(
            {
                "similar_past_tasks": [],
                "recommended_tools": ["read_file"],
                "known_pitfalls": [],
                "estimated_steps": 1,
                "confidence": 0.9,
            }
        )
    )

    action = planner.plan(AgentState(run_id="run-1", task="read the file"))

    assert action["tool_name"] == "read_file"
    assert "memory-guided" in str(action["reason"])


def test_plan_falls_back_to_rule_based_when_confidence_low() -> None:
    planner = AdaptivePlanner(
        RetrievalDouble(
            {
                "similar_past_tasks": [],
                "recommended_tools": ["read_file"],
                "known_pitfalls": [],
                "estimated_steps": 1,
                "confidence": 0.2,
            }
        )
    )

    action = planner.plan(AgentState(run_id="run-1", task="list files"))

    assert action["tool_name"] == "list_files"


def test_plan_appends_known_pitfalls_to_reason() -> None:
    planner = AdaptivePlanner(
        RetrievalDouble(
            {
                "similar_past_tasks": [],
                "recommended_tools": [],
                "known_pitfalls": ["verify path exists first"],
                "estimated_steps": 1,
                "confidence": 0.0,
            }
        )
    )

    action = planner.plan(AgentState(run_id="run-1", task="read file"))

    assert "known pitfalls" in str(action["reason"])


def test_replan_uses_memory_when_similar_failure_found() -> None:
    planner = AdaptivePlanner(
        RetrievalDouble(
            {
                "similar_past_tasks": [
                    {
                        "task": "http get example",
                        "status": "completed",
                        "tools_used": ["http_get"],
                        "lessons": ["timeout avoided by retrying http_get"],
                        "success_rate": 1.0,
                    }
                ],
                "recommended_tools": ["http_get"],
                "known_pitfalls": [],
                "estimated_steps": 1,
                "confidence": 0.8,
            }
        )
    )

    action = planner.replan(AgentState(run_id="run-1", task="http get example"), "timeout")

    assert action["tool_name"] == "http_get"
    assert "failure" in str(action["reason"])


def test_replan_falls_back_to_default_when_no_memory_match() -> None:
    planner = AdaptivePlanner(
        RetrievalDouble(
            {
                "similar_past_tasks": [],
                "recommended_tools": [],
                "known_pitfalls": [],
                "estimated_steps": 1,
                "confidence": 0.0,
            }
        )
    )

    action = planner.replan(AgentState(run_id="run-1", task="write result"), "boom")

    assert action["tool_name"] == "write_file"


def test_get_confidence_returns_float_between_zero_and_one() -> None:
    planner = AdaptivePlanner(
        RetrievalDouble(
            {
                "similar_past_tasks": [],
                "recommended_tools": [],
                "known_pitfalls": [],
                "estimated_steps": 0,
                "confidence": 0.42,
            }
        )
    )

    confidence = planner.get_confidence("list files")

    assert isinstance(confidence, float)
    assert 0.0 <= confidence <= 1.0
