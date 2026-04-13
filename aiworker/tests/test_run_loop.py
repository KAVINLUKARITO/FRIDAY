"""Unit tests for the autonomous run loop."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from aiworker.autonomy.controller import EvolutionController
from aiworker.autonomy.models import EvolutionConfig
from aiworker.autonomy.run_loop import run_loop
from aiworker.governance.audit import AuditLog
from aiworker.governance.circuit_breaker import CircuitBreaker
from aiworker.governance.policy import PolicyDecision, PolicyEngine
from aiworker.governance.rate_limiter import RateLimiter
from aiworker.memory.database import Database


class _PatchGenerator:
    def __init__(self, patch_text: str | None) -> None:
        self.patch_text = patch_text

    def generate(self, plan, goal, allowed_files, seed=None):  # noqa: ANN001, ANN201
        del plan, goal, allowed_files, seed
        return self.patch_text


class _StubPolicyEngine:
    def __init__(self, decisions: list[PolicyDecision]) -> None:
        self.decisions = list(decisions)
        self.recorded: list[tuple[bool, str | None]] = []
        self.audit_log = AuditLog()

    def evaluate(self, attempt_id=None):  # noqa: ANN001, ANN201
        if self.decisions:
            return self.decisions.pop(0)
        return PolicyDecision(allowed=True)

    def record_outcome(self, success, attempt_id=None):  # noqa: ANN001, ANN201
        self.recorded.append((success, attempt_id))


class _EngineResult:
    def __init__(self, success: bool, reason: str = "ok") -> None:
        self.validation_passed = True
        self.sandbox_result = type(
            "SandboxResult",
            (),
            {"success": success, "tests_passed": 1, "tests_failed": 0},
        )()
        self.approved = success
        self.reason = reason


def _controller(
    policy_engine,
    patch_text: str | None = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-print('a')\n+print('b')\n",
    database: Database | None = None,
) -> EvolutionController:
    config = EvolutionConfig(
        goal="fix app",
        allowed_files=("app.py",),
        max_attempts=3,
        max_failures=2,
        confidence_threshold=0.4,
    )
    return EvolutionController(
        config=config,
        policy_engine=policy_engine,
        patch_generator=_PatchGenerator(patch_text),
        workspace_path=".",
        database=database,
        audit_log=policy_engine.audit_log,
    )


class RunLoopTests(unittest.TestCase):
    def test_returns_circuit_breaker_open_when_policy_denies_open_circuit(self) -> None:
        policy = _StubPolicyEngine(
            [PolicyDecision(allowed=False, reasons=("circuit open",), circuit_state="open")]
        )
        result = run_loop(_controller(policy))
        self.assertFalse(result.success)
        self.assertEqual(result.termination_reason, "circuit_breaker_open")
        self.assertEqual(result.attempts[0].outcome, "policy_denied")

    def test_retries_rate_limited_attempts_until_max_failures(self) -> None:
        policy = _StubPolicyEngine(
            [
                PolicyDecision(
                    allowed=False,
                    reasons=("Rate limit exceeded: 1/1 attempts in 60s window",),
                    circuit_state="closed",
                ),
                PolicyDecision(
                    allowed=False,
                    reasons=("Rate limit exceeded: 1/1 attempts in 60s window",),
                    circuit_state="closed",
                ),
            ]
        )
        result = run_loop(_controller(policy))
        self.assertEqual(result.termination_reason, "max_failures_reached")
        self.assertEqual(len(policy.recorded), 0)

    def test_records_patch_generation_failure(self) -> None:
        policy = _StubPolicyEngine([PolicyDecision(allowed=True)])
        result = run_loop(_controller(policy, patch_text=None))
        self.assertEqual(result.attempts[0].outcome, "patch_generation_failed")
        self.assertEqual(policy.recorded[0][0], False)

    def test_calls_engine_with_explicit_approval_and_stores_lessons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = Database(f"{tmpdir}/aiworker.db")
            database.initialise()
            audit_log = AuditLog()
            policy = PolicyEngine(
                audit_log=audit_log,
                circuit_breaker=CircuitBreaker(),
                rate_limiter=RateLimiter(),
                health_check_enabled=False,
            )
            controller = _controller(policy, database=database)
            calls: list[bool] = []

            with patch("aiworker.autonomy.run_loop.process_change_request") as process_mock, patch(
                "aiworker.autonomy.run_loop.analyze_result"
            ) as analyze_mock:
                process_mock.side_effect = lambda **kwargs: calls.append(kwargs["explicit_approval"]) or _EngineResult(True)
                analyze_mock.return_value = []
                result = run_loop(controller)

            self.assertTrue(result.success)
            self.assertEqual(calls, [True])
            self.assertEqual(result.termination_reason, "success")

    def test_analyzes_failures_after_loop_exhaustion(self) -> None:
        policy = _StubPolicyEngine([PolicyDecision(allowed=True), PolicyDecision(allowed=True)])
        controller = _controller(policy, patch_text=None)
        with patch("aiworker.autonomy.run_loop.analyze_result") as analyze_mock:
            analyze_mock.return_value = []
            result = run_loop(controller)
        self.assertFalse(result.success)
        self.assertEqual(result.termination_reason, "max_failures_reached")
        analyze_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
