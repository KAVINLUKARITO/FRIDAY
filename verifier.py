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


class Verifier:
    """Verify execution results against concrete success rules."""

    def verify(
        self,
        action: ValidatedAction,
        result: ExecutionResult,
    ) -> VerificationResult:
        _ = action
        reason = "verification completed"
        status = VerificationStatus.UNVERIFIED

        if result.timed_out:
            status = VerificationStatus.FAILURE
            reason = "execution timed out"
        elif not result.success:
            status = VerificationStatus.FAILURE
            reason = result.error or "execution failed"
        elif result.output is None:
            status = VerificationStatus.UNVERIFIED
            reason = "null output"
        elif result.output == "" or result.output == []:
            status = VerificationStatus.UNVERIFIED
            reason = "empty output"
        else:
            status = VerificationStatus.SUCCESS
            reason = "execution verified"

        if not reason:
            reason = "verification result unavailable"

        return VerificationResult(
            status=status,
            reason=reason,
            verified_at=datetime.now(timezone.utc),
        )
