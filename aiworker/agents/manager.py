"""Multi-agent coordinator and activity tracker."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading
from typing import Any, Sequence

from aiworker.agents.coder_agent import CoderAgent
from aiworker.agents.critic_agent import CriticAgent
from aiworker.agents.planner_agent import PlannerAgent
from aiworker.agents.research_agent import ResearchAgent


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentManager:
    """Coordinates planner, research, coder, and critic roles."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._planner = PlannerAgent()
        self._researcher = ResearchAgent()
        self._coder = CoderAgent()
        self._critic = CriticAgent()
        self._activity: dict[str, Any] = {
            "last_cycle_at": None,
            "active_role": "idle",
            "agents": {
                "planner": {"status": "idle", "work_units": 0},
                "research": {"status": "idle", "work_units": 0},
                "coder": {"status": "idle", "work_units": 0},
                "critic": {"status": "idle", "work_units": 0},
            },
        }

    def _mark(self, role: str, status: str, work_units: int | None = None) -> None:
        with self._lock:
            self._activity["active_role"] = role if status == "running" else "idle"
            self._activity["last_cycle_at"] = _utcnow_iso()
            agent_state = dict(self._activity["agents"][role])
            agent_state["status"] = status
            if work_units is not None:
                agent_state["work_units"] = int(work_units)
            self._activity["agents"][role] = agent_state

    def coordinate(self, *, goal: str, allowed_files: Sequence[str]) -> dict[str, Any]:
        self._mark("research", "running")
        research = self._researcher.run(goal=goal, allowed_files=allowed_files)
        self._mark("research", "completed", work_units=len(research["findings"]))

        self._mark("planner", "running")
        plan = self._planner.run(
            goal=goal,
            allowed_files=allowed_files,
            research_notes=research["findings"],
        )
        self._mark("planner", "completed", work_units=len(plan["steps"]))

        self._mark("coder", "running")
        code = self._coder.run(plan)
        self._mark("coder", "completed", work_units=len(code["actions"]))

        self._mark("critic", "running")
        critique = self._critic.run(code)
        self._mark("critic", "completed", work_units=len(critique["concerns"]))

        return {
            "research": research,
            "plan": plan,
            "code": code,
            "critique": critique,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._activity)

    def reset(self) -> None:
        with self._lock:
            self._activity = {
                "last_cycle_at": None,
                "active_role": "idle",
                "agents": {
                    "planner": {"status": "idle", "work_units": 0},
                    "research": {"status": "idle", "work_units": 0},
                    "coder": {"status": "idle", "work_units": 0},
                    "critic": {"status": "idle", "work_units": 0},
                },
            }


agent_manager = AgentManager()
