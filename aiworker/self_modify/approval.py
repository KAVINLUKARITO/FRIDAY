"""Approval gate for controlled self-modification.

Determines whether a validated patch may be applied to the real
workspace.  **No patch is ever auto-approved.**  The caller must
supply an explicit ``approved`` flag; this module only decides
whether the result *qualifies* for approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from aiworker.execution.runner import ExecutionResult
from aiworker.self_modify.change_request import ChangeRequest


@dataclass(frozen=True)
class ApprovalDecision:
    """Immutable outcome of the approval gate.

    Attributes:
        eligible: ``True`` if the change meets all automated criteria
            and *could* be approved (but still requires explicit human
            confirmation).
        requires_manual_review: ``True`` when the risk level is
            ``"high"`` — a human must explicitly approve.
        reason: Human-readable explanation for the decision.
    """

    eligible: bool
    requires_manual_review: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dictionary."""
        return {
            "eligible": self.eligible,
            "requires_manual_review": self.requires_manual_review,
            "reason": self.reason,
        }


def evaluate_approval(
    change_request: ChangeRequest,
    sandbox_result: ExecutionResult,
    *,
    explicit_approval: bool = False,
) -> ApprovalDecision:
    """Evaluate whether a patch qualifies for approval.

    Rules (applied in order):

    1. If ``sandbox_result.success`` is ``False`` the patch is
       **rejected** outright — it did not pass sandbox execution.
    2. If ``change_request.tests_required`` is ``True`` and
       ``sandbox_result.tests_failed > 0`` the patch is **rejected**.
    3. If ``change_request.risk_level`` is ``"high"`` the patch
       **requires manual review** regardless of test outcome.
    4. If none of the above rejection rules fire, the patch is
       **eligible** for approval but still requires the caller to
       supply ``explicit_approval=True``.

    Args:
        change_request: The original change constraints.
        sandbox_result: The result from running the patch in the
            hardened sandbox.
        explicit_approval: An external approval signal (e.g. from a
            human reviewer).  Even when ``eligible`` is ``True``, the
            patch is not considered approved unless this is set.

    Returns:
        An :class:`ApprovalDecision` describing the outcome.
    """
    # Rule 1 — sandbox must succeed
    if not sandbox_result.success:
        return ApprovalDecision(
            eligible=False,
            requires_manual_review=False,
            reason=(
                "Sandbox execution failed: "
                + (sandbox_result.error or "unknown error")
            ),
        )

    # Rule 2 — required tests must pass
    if change_request.tests_required and sandbox_result.tests_failed > 0:
        return ApprovalDecision(
            eligible=False,
            requires_manual_review=False,
            reason=(
                f"{sandbox_result.tests_failed} test(s) failed and "
                f"tests_required is True"
            ),
        )

    # Rule 3 — high risk requires manual review
    if change_request.risk_level == "high":
        return ApprovalDecision(
            eligible=explicit_approval,
            requires_manual_review=True,
            reason=(
                "Risk level is high — manual approval required"
                if not explicit_approval
                else "Risk level is high — manually approved"
            ),
        )

    # Rule 4 — eligible, awaiting explicit approval
    if not explicit_approval:
        return ApprovalDecision(
            eligible=True,
            requires_manual_review=False,
            reason="Eligible for approval — awaiting explicit confirmation",
        )

    return ApprovalDecision(
        eligible=True,
        requires_manual_review=False,
        reason="Approved",
    )
