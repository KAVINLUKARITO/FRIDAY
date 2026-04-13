"""# FILE: aiworker/agent/multi_agent.py — Coordinated multi-role AIWorker execution."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Optional

from aiworker.agent.goal_decomposer import GoalDecomposer
from aiworker.autonomy.controller import EvolutionController
from aiworker.orchestration.queue import TaskQueue


class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    LEARNER = "learner"
    ORCHESTRATOR = "orchestrator"


@dataclass(frozen=True)
class AgentMessage:
    """Immutable message passed between agent roles."""

    message_id: str
    from_role: AgentRole
    to_role: AgentRole
    payload: dict[str, Any]
    timestamp: str
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "from_role": self.from_role.value,
            "to_role": self.to_role.value,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }


class AgentBus:
    """Role-addressed FIFO message bus backed by TaskQueue ordering."""

    def __init__(self) -> None:
        self._queue = TaskQueue()
        self._messages: dict[str, AgentMessage] = {}
        self._task_by_message: dict[str, str] = {}
        self._pending_by_role: dict[AgentRole, list[str]] = {
            role: [] for role in AgentRole
        }

    def post(self, message: AgentMessage) -> None:
        task = self._queue.add_task(message.message_id)
        self._messages[message.message_id] = message
        self._task_by_message[message.message_id] = task.task_id
        self._pending_by_role[message.to_role].append(message.message_id)

    def poll(self, role: AgentRole, timeout: float = 0.0) -> Optional[AgentMessage]:
        del timeout
        pending = self._pending_by_role[role]
        if not pending:
            return None
        return self._messages[pending[0]]

    def ack(self, message_id: str) -> None:
        task_id = self._task_by_message.pop(message_id, None)
        message = self._messages.pop(message_id, None)
        if task_id is not None:
            self._queue.mark_processed(task_id)
        if message is not None:
            self._pending_by_role[message.to_role] = [
                mid for mid in self._pending_by_role[message.to_role] if mid != message_id
            ]

    def pending_count(self, role: AgentRole) -> int:
        return len(self._pending_by_role[role])


class AgentPool:
    """Pool of specialised controllers coordinated through a simple bus."""

    def __init__(self, bus: Optional[AgentBus] = None) -> None:
        self._bus = bus or AgentBus()
        self._controllers: dict[AgentRole, EvolutionController] = {}

    def register(self, role: AgentRole, controller: EvolutionController) -> None:
        self._controllers[role] = controller

    def _clone_controller(
        self,
        controller: EvolutionController,
        goal: str,
        allowed_files: tuple[str, ...],
    ) -> EvolutionController:
        return EvolutionController(
            config=replace(controller.config, goal=goal, allowed_files=allowed_files),
            policy_engine=controller.policy_engine,
            patch_generator=controller.patch_generator,
            workspace_path=controller.workspace_path,
            database=controller.database,
            audit_log=controller.audit_log,
        )

    @staticmethod
    def _select_overall_result(results: list[Any]) -> Any:
        for result in results:
            if not getattr(result, "success", False):
                return result
        return results[-1]

    def run_goal(
        self,
        goal: str,
        allowed_files: tuple[str, ...],
    ) -> dict[AgentRole, Any]:
        results: dict[AgentRole, Any] = {}
        planner_controller = self._controllers.get(AgentRole.PLANNER)
        planner_backend = None
        if planner_controller is not None:
            planner_backend = getattr(planner_controller.patch_generator, "backend", None)
        decomposer = GoalDecomposer(planner_backend)
        sub_goals = decomposer.decompose(goal, allowed_files)

        coder = self._controllers.get(AgentRole.CODER)
        if coder is not None:
            coder_results = decomposer.execute_sequence(
                sub_goals=sub_goals,
                controller_factory=lambda goal: self._clone_controller(
                    coder,
                    goal=goal,
                    allowed_files=allowed_files,
                ),
                stop_on_failure=True,
            )
            if coder_results:
                results[AgentRole.CODER] = self._select_overall_result(coder_results)

        if planner_controller is not None and results:
            results[AgentRole.PLANNER] = next(iter(results.values()))
        for role in (
            AgentRole.REVIEWER,
            AgentRole.TESTER,
            AgentRole.LEARNER,
            AgentRole.ORCHESTRATOR,
        ):
            if role in self._controllers and results:
                results[role] = next(iter(results.values()))

        return results

    def status(self) -> dict[str, Any]:
        return {
            role.value: {
                "registered": role in self._controllers,
                "pending_messages": self._bus.pending_count(role),
            }
            for role in AgentRole
        }
