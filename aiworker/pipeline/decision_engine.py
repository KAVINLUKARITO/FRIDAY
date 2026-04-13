from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from aiworker.pipeline.state import AgentState
from aiworker.pipeline.verifier import VerificationResult


class Decision(BaseModel):
    action: Literal["CONTINUE", "RETRY", "REPLAN", "ABORTED", "STEP_LIMIT_REACHED"]
    attempt_number: int
    replan_count: int
    reason: str = Field(min_length=1)


class DecisionEngine:
    def __init__(self, max_retries: int = 3, max_replans: int = 2, step_limit: int = 20, sleep_func=time.sleep) -> None:
        self.max_retries = max_retries
        self.max_replans = max_replans
        self.step_limit = step_limit
        self.sleep_func = sleep_func

    def decide(self, result: VerificationResult, state: AgentState) -> Decision:
        if state.terminal_status in {"ABORTED", "STEP_LIMIT_REACHED"}:
            return Decision(
                action=state.terminal_status,
                attempt_number=state.current_action_retries,
                replan_count=state.replans,
                reason=f"terminal state already reached: {state.terminal_status}",
            )

        if state.steps_taken >= self.step_limit:
            state.finish("STEP_LIMIT_REACHED")
            return Decision(
                action="STEP_LIMIT_REACHED",
                attempt_number=state.current_action_retries,
                replan_count=state.replans,
                reason="step limit reached",
            )

        if result.status == "SUCCESS":
            state.verified_successes += 1
            state.mark_completed()
            return Decision(
                action="CONTINUE",
                attempt_number=state.current_action_retries,
                replan_count=state.replans,
                reason=result.reason,
            )

        if state.current_action_retries < self.max_retries:
            state.mark_retry()
            delay = 2 ** (state.current_action_retries - 1)
            self.sleep_func(delay)
            return Decision(
                action="RETRY",
                attempt_number=state.current_action_retries,
                replan_count=state.replans,
                reason=result.reason,
            )

        if state.replans < self.max_replans:
            state.current_action_retries = 0
            return Decision(
                action="REPLAN",
                attempt_number=state.current_action_retries,
                replan_count=state.replans + 1,
                reason=result.reason,
            )

        state.finish("ABORTED")
        return Decision(
            action="ABORTED",
            attempt_number=state.current_action_retries,
            replan_count=state.replans,
            reason="maximum replans exceeded",
        )
