from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel

from executor import ExecutionResult
from validator import ValidatedAction


class VerificationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNVERIFIED = "UNVERIFIED"


class VerificationResult(BaseModel):
    status: VerificationStatus
    reason: str
    verified_at: datetime
    agent_name: str
    tool_name: str


class Verifier:
    """Verify execution outputs against shared result rules."""

    def verify(self, action: ValidatedAction, result: ExecutionResult) -> VerificationResult:
        if result.timed_out:
            reason = "execution timed out"
            status = VerificationStatus.FAILURE
        elif not result.success:
            reason = result.error or "execution failed"
            status = VerificationStatus.FAILURE
        elif result.output is None:
            reason = "null output"
            status = VerificationStatus.UNVERIFIED
        elif result.output in ("", [], {}):
            reason = "empty output"
            status = VerificationStatus.UNVERIFIED
        else:
            reason = "execution verified"
            status = VerificationStatus.SUCCESS

        if not reason:
            reason = "verification result unavailable"

        return VerificationResult(
            status=status,
            reason=reason,
            verified_at=datetime.now(timezone.utc),
            agent_name=action.agent_name,
            tool_name=action.tool_name,
        )
