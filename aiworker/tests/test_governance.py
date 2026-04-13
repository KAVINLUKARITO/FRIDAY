"""Tests for the governance & audit trail module (Milestone 10).

Covers:
- Audit event immutability and creation
- AuditLog append-only semantics and filtering
- CircuitBreaker state machine transitions
- CircuitBreaker threshold and recovery
- RateLimiter sliding-window enforcement
- RateLimiter clock injection for deterministic testing
- PolicyEngine combined evaluation
- PolicyEngine audit trail completeness
- PolicyEngine health-gated execution
- All governance components have no side effects
"""

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from aiworker.governance.audit import (
    AuditEvent,
    AuditLog,
    create_event,
)
from aiworker.governance.circuit_breaker import CircuitBreaker, CircuitStatus
from aiworker.governance.rate_limiter import RateLimiter, RateLimitStatus
from aiworker.governance.policy import PolicyDecision, PolicyEngine


# ── AuditEvent ───────────────────────────────────────────────

class TestAuditEvent:
    """Verify AuditEvent immutability and serialisation."""

    def test_event_frozen(self) -> None:
        event = create_event("validation", "info", "test", "detail")
        with pytest.raises(AttributeError):
            event.action = "modified"  # type: ignore[misc]

    def test_event_has_uuid(self) -> None:
        event = create_event("validation", "info", "test", "detail")
        assert len(event.event_id) == 36  # UUID4 format

    def test_event_has_timestamp(self) -> None:
        event = create_event("validation", "info", "test", "detail")
        assert "T" in event.timestamp  # ISO-8601

    def test_event_to_dict(self) -> None:
        event = create_event(
            "sandbox", "warning", "timeout", "Sandbox timed out",
            metadata={"duration": 120},
            attempt_id="att-1",
        )
        d = event.to_dict()
        assert d["category"] == "sandbox"
        assert d["severity"] == "warning"
        assert d["action"] == "timeout"
        assert d["metadata"]["duration"] == 120
        assert d["attempt_id"] == "att-1"

    def test_event_default_metadata_empty(self) -> None:
        event = create_event("validation", "info", "test", "detail")
        assert event.metadata == {}
        assert event.attempt_id is None

    def test_events_have_unique_ids(self) -> None:
        ids = {create_event("validation", "info", "t", "d").event_id for _ in range(100)}
        assert len(ids) == 100


# ── AuditLog ─────────────────────────────────────────────────

class TestAuditLog:
    """Verify append-only semantics, filtering, and querying."""

    def test_empty_log(self) -> None:
        log = AuditLog()
        assert log.count == 0
        assert log.all_events() == ()

    def test_record_appends(self) -> None:
        log = AuditLog()
        e = create_event("validation", "info", "passed", "OK")
        log.record(e)
        assert log.count == 1
        assert log.all_events()[0] is e

    def test_emit_creates_and_records(self) -> None:
        log = AuditLog()
        e = log.emit("sandbox", "error", "failed", "Crashed")
        assert log.count == 1
        assert e.category == "sandbox"
        assert e.severity == "error"

    def test_insertion_order_preserved(self) -> None:
        log = AuditLog()
        e1 = log.emit("validation", "info", "a", "first")
        e2 = log.emit("sandbox", "info", "b", "second")
        e3 = log.emit("approval", "info", "c", "third")
        events = log.all_events()
        assert events == (e1, e2, e3)

    def test_all_events_returns_immutable_copy(self) -> None:
        log = AuditLog()
        log.emit("validation", "info", "a", "first")
        events = log.all_events()
        assert isinstance(events, tuple)

    def test_filter_by_category(self) -> None:
        log = AuditLog()
        log.emit("validation", "info", "a", "first")
        log.emit("sandbox", "info", "b", "second")
        log.emit("validation", "warning", "c", "third")
        results = log.filter_by_category("validation")
        assert len(results) == 2
        assert all(e.category == "validation" for e in results)

    def test_filter_by_severity(self) -> None:
        log = AuditLog()
        log.emit("validation", "info", "a", "ok")
        log.emit("sandbox", "error", "b", "bad")
        log.emit("approval", "critical", "c", "very bad")
        results = log.filter_by_severity("error")
        assert len(results) == 1
        assert results[0].action == "b"

    def test_filter_by_attempt(self) -> None:
        log = AuditLog()
        log.emit("validation", "info", "a", "ok", attempt_id="att-1")
        log.emit("sandbox", "info", "b", "ok", attempt_id="att-2")
        log.emit("approval", "info", "c", "ok", attempt_id="att-1")
        results = log.filter_by_attempt("att-1")
        assert len(results) == 2

    def test_last_n(self) -> None:
        log = AuditLog()
        for i in range(10):
            log.emit("validation", "info", f"action-{i}", f"detail-{i}")
        last3 = log.last_n(3)
        assert len(last3) == 3
        assert last3[0].action == "action-7"
        assert last3[2].action == "action-9"

    def test_last_n_exceeding_count(self) -> None:
        log = AuditLog()
        log.emit("validation", "info", "a", "only one")
        assert len(log.last_n(100)) == 1

    def test_errors_and_critical(self) -> None:
        log = AuditLog()
        log.emit("validation", "info", "a", "ok")
        log.emit("sandbox", "error", "b", "bad")
        log.emit("approval", "critical", "c", "terrible")
        log.emit("policy", "warning", "d", "hmm")
        results = log.errors_and_critical()
        assert len(results) == 2
        assert {e.severity for e in results} == {"error", "critical"}


# ── CircuitBreaker: construction ─────────────────────────────

class TestCircuitBreakerConstruction:
    """Verify construction and initial state."""

    def test_initial_state_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == "closed"
        assert cb.can_proceed is True

    def test_initial_status(self) -> None:
        cb = CircuitBreaker(failure_threshold=5)
        s = cb.status()
        assert s.state == "closed"
        assert s.consecutive_failures == 0
        assert s.total_failures == 0
        assert s.total_successes == 0
        assert s.failure_threshold == 5
        assert s.can_proceed is True

    def test_invalid_threshold(self) -> None:
        with pytest.raises(ValueError, match="failure_threshold"):
            CircuitBreaker(failure_threshold=0)

    def test_invalid_recovery(self) -> None:
        with pytest.raises(ValueError, match="recovery_after"):
            CircuitBreaker(recovery_after=0)

    def test_status_frozen(self) -> None:
        cb = CircuitBreaker()
        s = cb.status()
        with pytest.raises(AttributeError):
            s.state = "open"  # type: ignore[misc]

    def test_status_to_dict(self) -> None:
        cb = CircuitBreaker()
        d = cb.status().to_dict()
        assert "state" in d
        assert "can_proceed" in d


# ── CircuitBreaker: state transitions ────────────────────────

class TestCircuitBreakerTransitions:
    """Verify the closed → open → half_open → closed state machine."""

    def test_failures_trip_breaker(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"  # not yet
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_proceed is False

    def test_success_resets_from_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == "closed"
        s = cb.status()
        assert s.consecutive_failures == 0

    def test_tick_transitions_open_to_half_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_after=2)
        cb.record_failure()
        assert cb.state == "open"
        cb.tick()
        assert cb.state == "open"  # not enough ticks
        cb.tick()
        assert cb.state == "half_open"
        assert cb.can_proceed is True

    def test_success_in_half_open_closes(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_after=1)
        cb.record_failure()
        cb.tick()
        assert cb.state == "half_open"
        cb.record_success()
        assert cb.state == "closed"

    def test_failure_in_half_open_reopens(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_after=1)
        cb.record_failure()
        cb.tick()
        assert cb.state == "half_open"
        cb.record_failure()
        assert cb.state == "open"

    def test_tick_no_effect_when_closed(self) -> None:
        cb = CircuitBreaker()
        cb.tick()
        assert cb.state == "closed"

    def test_reset_forces_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb.status().consecutive_failures == 0

    def test_total_counts_accumulate(self) -> None:
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        cb.record_success()
        s = cb.status()
        assert s.total_successes == 3
        assert s.total_failures == 1


# ── CircuitBreaker: determinism ──────────────────────────────

class TestCircuitBreakerDeterminism:
    """Verify identical sequences produce identical states."""

    def test_deterministic_100_runs(self) -> None:
        results = []
        for _ in range(100):
            cb = CircuitBreaker(failure_threshold=2, recovery_after=1)
            cb.record_failure()
            cb.record_failure()
            cb.tick()
            cb.record_success()
            results.append(cb.status().to_dict())
        first = results[0]
        for r in results[1:]:
            assert r == first


# ── RateLimiter: construction ────────────────────────────────

class TestRateLimiterConstruction:
    """Verify construction and parameter validation."""

    def test_initial_state_allowed(self) -> None:
        rl = RateLimiter(max_attempts=5, window_seconds=60.0)
        s = rl.check()
        assert s.allowed is True
        assert s.current_count == 0

    def test_invalid_max_attempts(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            RateLimiter(max_attempts=0)

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError, match="window_seconds"):
            RateLimiter(window_seconds=0)

    def test_status_frozen(self) -> None:
        rl = RateLimiter()
        s = rl.check()
        with pytest.raises(AttributeError):
            s.allowed = False  # type: ignore[misc]

    def test_status_to_dict(self) -> None:
        rl = RateLimiter()
        d = rl.check().to_dict()
        assert "allowed" in d
        assert "seconds_until_available" in d


# ── RateLimiter: enforcement ─────────────────────────────────

class TestRateLimiterEnforcement:
    """Verify sliding-window rate limiting with injected clock."""

    def test_allows_up_to_max(self) -> None:
        t = [0.0]
        clock = lambda: t[0]
        rl = RateLimiter(max_attempts=3, window_seconds=60.0, clock=clock)
        rl.acquire()
        rl.acquire()
        s = rl.acquire()
        assert s.current_count == 3
        assert s.allowed is False  # next would be blocked

    def test_blocks_after_max(self) -> None:
        t = [0.0]
        clock = lambda: t[0]
        rl = RateLimiter(max_attempts=2, window_seconds=60.0, clock=clock)
        rl.acquire()
        rl.acquire()
        s = rl.check()
        assert s.allowed is False
        assert s.current_count == 2

    def test_window_expiry_frees_slots(self) -> None:
        t = [0.0]
        clock = lambda: t[0]
        rl = RateLimiter(max_attempts=2, window_seconds=10.0, clock=clock)
        rl.acquire()  # at t=0
        t[0] = 5.0
        rl.acquire()  # at t=5
        s = rl.check()
        assert s.allowed is False

        t[0] = 11.0  # first slot (t=0) expired, second (t=5) still active
        s = rl.check()
        assert s.allowed is True
        assert s.current_count == 1  # only t=5 slot remains

    def test_seconds_until_available(self) -> None:
        t = [0.0]
        clock = lambda: t[0]
        rl = RateLimiter(max_attempts=1, window_seconds=10.0, clock=clock)
        rl.acquire()  # at t=0
        t[0] = 3.0
        s = rl.check()
        assert s.allowed is False
        assert abs(s.seconds_until_available - 7.0) < 0.01

    def test_reset_clears_all(self) -> None:
        t = [0.0]
        clock = lambda: t[0]
        rl = RateLimiter(max_attempts=1, window_seconds=60.0, clock=clock)
        rl.acquire()
        assert rl.check().allowed is False
        rl.reset()
        assert rl.check().allowed is True
        assert rl.check().current_count == 0

    def test_check_does_not_consume_slot(self) -> None:
        t = [0.0]
        clock = lambda: t[0]
        rl = RateLimiter(max_attempts=1, window_seconds=60.0, clock=clock)
        for _ in range(100):
            s = rl.check()
            assert s.allowed is True
        assert rl.check().current_count == 0


# ── PolicyEngine: evaluation ─────────────────────────────────

class TestPolicyEvaluation:
    """Verify PolicyEngine combines all checks correctly."""

    @staticmethod
    def _make_engine(
        failure_threshold: int = 3,
        max_attempts: int = 10,
        health_enabled: bool = False,
    ) -> PolicyEngine:
        t = [0.0]
        return PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(failure_threshold=failure_threshold),
            rate_limiter=RateLimiter(
                max_attempts=max_attempts,
                window_seconds=60.0,
                clock=lambda: t[0],
            ),
            health_check_enabled=health_enabled,
        )

    def test_all_clear_allows(self) -> None:
        engine = self._make_engine()
        decision = engine.evaluate()
        assert decision.allowed is True
        assert decision.reasons == ()
        assert decision.circuit_state == "closed"

    def test_circuit_open_blocks(self) -> None:
        engine = self._make_engine(failure_threshold=2)
        engine.circuit_breaker.record_failure()
        engine.circuit_breaker.record_failure()
        decision = engine.evaluate()
        assert decision.allowed is False
        assert any("Circuit breaker" in r for r in decision.reasons)

    def test_rate_limit_blocks(self) -> None:
        engine = self._make_engine(max_attempts=1)
        engine.rate_limiter.acquire()
        decision = engine.evaluate()
        assert decision.allowed is False
        assert any("Rate limit" in r for r in decision.reasons)

    def test_multiple_denials_reported(self) -> None:
        engine = self._make_engine(failure_threshold=1, max_attempts=1)
        engine.circuit_breaker.record_failure()
        engine.rate_limiter.acquire()
        decision = engine.evaluate()
        assert decision.allowed is False
        assert len(decision.reasons) == 2

    def test_decision_frozen(self) -> None:
        engine = self._make_engine()
        decision = engine.evaluate()
        with pytest.raises(AttributeError):
            decision.allowed = False  # type: ignore[misc]

    def test_decision_to_dict(self) -> None:
        engine = self._make_engine()
        d = engine.evaluate().to_dict()
        assert "allowed" in d
        assert "reasons" in d
        assert isinstance(d["reasons"], list)

    def test_rate_limit_remaining_correct(self) -> None:
        engine = self._make_engine(max_attempts=5)
        engine.rate_limiter.acquire()
        engine.rate_limiter.acquire()
        decision = engine.evaluate()
        assert decision.rate_limit_remaining == 3


# ── PolicyEngine: audit trail ────────────────────────────────

class TestPolicyAuditTrail:
    """Verify evaluate() and record_outcome() emit audit events."""

    @staticmethod
    def _make_engine() -> PolicyEngine:
        t = [0.0]
        return PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(failure_threshold=3),
            rate_limiter=RateLimiter(
                max_attempts=10,
                window_seconds=60.0,
                clock=lambda: t[0],
            ),
        )

    def test_evaluate_emits_policy_event(self) -> None:
        engine = self._make_engine()
        engine.evaluate(attempt_id="att-1")
        events = engine.audit_log.filter_by_category("policy")
        assert len(events) == 1
        assert events[0].attempt_id == "att-1"
        assert events[0].action == "allowed"

    def test_denied_evaluate_emits_multiple_events(self) -> None:
        engine = self._make_engine()
        # Trip the circuit breaker
        for _ in range(3):
            engine.circuit_breaker.record_failure()
        engine.evaluate(attempt_id="att-2")
        cb_events = engine.audit_log.filter_by_category("circuit_breaker")
        policy_events = engine.audit_log.filter_by_category("policy")
        assert len(cb_events) == 1
        assert cb_events[0].action == "blocked"
        assert len(policy_events) == 1
        assert policy_events[0].action == "denied"

    def test_record_outcome_success(self) -> None:
        engine = self._make_engine()
        engine.record_outcome(success=True, attempt_id="att-3")
        events = engine.audit_log.filter_by_category("lifecycle")
        assert len(events) == 1
        assert events[0].action == "attempt_succeeded"
        assert engine.circuit_breaker.state == "closed"

    def test_record_outcome_failure(self) -> None:
        engine = self._make_engine()
        engine.record_outcome(success=False, attempt_id="att-4")
        events = engine.audit_log.filter_by_category("lifecycle")
        assert len(events) == 1
        assert events[0].action == "attempt_failed"
        assert engine.circuit_breaker.status().consecutive_failures == 1

    def test_full_lifecycle_audit_trail(self) -> None:
        """Simulate: evaluate → succeed → evaluate → fail → fail → fail → evaluate (blocked)."""
        engine = self._make_engine()

        # First attempt: allowed
        d1 = engine.evaluate(attempt_id="a1")
        assert d1.allowed is True
        engine.record_outcome(success=True, attempt_id="a1")

        # Three failures
        for i in range(3):
            d = engine.evaluate(attempt_id=f"f{i}")
            engine.record_outcome(success=False, attempt_id=f"f{i}")

        # Next attempt: circuit should be open
        d_blocked = engine.evaluate(attempt_id="blocked")
        assert d_blocked.allowed is False

        # Verify audit trail is complete
        total = engine.audit_log.count
        assert total >= 9  # at least 4 evaluate + 4 outcome + 1 blocked


# ── PolicyEngine: health check integration ───────────────────

class TestPolicyHealthCheck:
    """Verify health-gated execution."""

    def test_health_disabled_always_passes(self) -> None:
        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(),
            rate_limiter=RateLimiter(),
            health_check_enabled=False,
        )
        decision = engine.evaluate()
        assert decision.health_ok is True

    def test_health_enabled_healthy_passes(self) -> None:
        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(),
            rate_limiter=RateLimiter(),
            health_check_enabled=True,
        )
        mock_status = MagicMock()
        mock_status.is_healthy = True
        mock_status.cpu_percent = 30.0
        mock_status.memory_percent = 40.0
        mock_status.disk_usage_percent = 50.0

        with patch("aiworker.governance.policy.get_system_status", return_value=mock_status):
            decision = engine.evaluate()
        assert decision.health_ok is True
        assert decision.allowed is True

    def test_health_enabled_unhealthy_blocks(self) -> None:
        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(),
            rate_limiter=RateLimiter(),
            health_check_enabled=True,
        )
        mock_status = MagicMock()
        mock_status.is_healthy = False
        mock_status.cpu_percent = 95.0
        mock_status.memory_percent = 92.0
        mock_status.disk_usage_percent = 50.0

        with patch("aiworker.governance.policy.get_system_status", return_value=mock_status):
            decision = engine.evaluate()
        assert decision.health_ok is False
        assert decision.allowed is False
        assert any("Unhealthy" in r for r in decision.reasons)

    def test_health_check_failure_fails_open(self) -> None:
        """If the monitor module raises, execution is allowed (fail-open)."""
        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(),
            rate_limiter=RateLimiter(),
            health_check_enabled=True,
        )
        with patch(
            "aiworker.governance.policy.get_system_status",
            side_effect=ImportError("psutil not available"),
        ):
            decision = engine.evaluate()
        assert decision.health_ok is True
        assert decision.allowed is True


# ── PolicyEngine: record_outcome updates components ──────────

class TestRecordOutcome:
    """Verify record_outcome correctly updates breaker and limiter."""

    def test_success_resets_breaker(self) -> None:
        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(failure_threshold=3),
            rate_limiter=RateLimiter(),
        )
        engine.record_outcome(success=False)
        engine.record_outcome(success=False)
        assert engine.circuit_breaker.status().consecutive_failures == 2
        engine.record_outcome(success=True)
        assert engine.circuit_breaker.status().consecutive_failures == 0

    def test_failure_increments_breaker(self) -> None:
        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(failure_threshold=5),
            rate_limiter=RateLimiter(),
        )
        for _ in range(4):
            engine.record_outcome(success=False)
        assert engine.circuit_breaker.status().consecutive_failures == 4

    def test_outcome_consumes_rate_slot(self) -> None:
        t = [0.0]
        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(),
            rate_limiter=RateLimiter(
                max_attempts=3,
                window_seconds=60.0,
                clock=lambda: t[0],
            ),
        )
        engine.record_outcome(success=True)
        engine.record_outcome(success=True)
        engine.record_outcome(success=True)
        s = engine.rate_limiter.check()
        assert s.current_count == 3
        assert s.allowed is False


# ── No side effects ──────────────────────────────────────────

class TestNoSideEffects:
    """Verify governance module has no filesystem or database side effects."""

    def test_no_file_writes(self) -> None:
        import os
        import tempfile

        workspace = tempfile.mkdtemp()
        before = os.listdir(workspace)

        engine = PolicyEngine(
            audit_log=AuditLog(),
            circuit_breaker=CircuitBreaker(),
            rate_limiter=RateLimiter(),
        )
        engine.evaluate()
        engine.record_outcome(success=True)
        engine.record_outcome(success=False)
        engine.evaluate()

        after = os.listdir(workspace)
        assert before == after
        os.rmdir(workspace)
