"""Unified governance policy engine.

Combines the audit log, circuit breaker, rate limiter, and system
health check into a single pre-flight gate.  Before any change
attempt enters the pipeline, :meth:`PolicyEngine.evaluate` runs all
governance checks and returns an immutable :class:`PolicyDecision`.

The policy engine **never modifies the workspace or database**.  It
only reads state and emits audit events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from aiworker.governance.audit import AuditLog
from aiworker.governance.circuit_breaker import CircuitBreaker
from aiworker.governance.rate_limiter import RateLimiter
from aiworker.monitor.status import get_system_status

@dataclass(frozen=True)
class PolicyDecision:
    """Immutable result of a governance policy evaluation.

    Attributes:
        allowed: ``True`` if all governance checks passed.
        reasons: List of human-readable reasons for denial (empty when
            ``allowed`` is ``True``).
        circuit_state: Current circuit breaker state string.
        rate_limit_remaining: How many attempts remain in the current
            rate-limit window.
        health_ok: Whether the system health check passed (or was
            skipped).
    """

    allowed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    circuit_state: str = "closed"
    rate_limit_remaining: int = 0
    health_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "circuit_state": self.circuit_state,
            "rate_limit_remaining": self.rate_limit_remaining,
            "health_ok": self.health_ok,
        }


class PolicyEngine:
    """Unified governance gate for the self-modification pipeline.

    Aggregates four independent checks:

    1. **Circuit breaker** — blocks execution after consecutive
       failures.
    2. **Rate limiter** — enforces a maximum attempt frequency.
    3. **Health check** — optionally blocks execution when the host
       system is unhealthy (uses :mod:`aiworker.monitor.status`).
    4. **Audit logging** — records every policy evaluation.

    The engine is stateful but never writes to disk or database.

    Args:
        audit_log: Shared :class:`AuditLog` instance for event recording.
        circuit_breaker: A :class:`CircuitBreaker` instance.
        rate_limiter: A :class:`RateLimiter` instance.
        health_check_enabled: If ``True``, system health is checked
            before allowing execution.  Defaults to ``False`` so the
            module works without ``psutil`` installed.
    """

    def __init__(
        self,
        audit_log: AuditLog,
        circuit_breaker: CircuitBreaker,
        rate_limiter: RateLimiter,
        health_check_enabled: bool = False,
    ) -> None:
        self.audit_log: AuditLog = audit_log
        self.circuit_breaker: CircuitBreaker = circuit_breaker
        self.rate_limiter: RateLimiter = rate_limiter
        self.health_check_enabled: bool = health_check_enabled

    def _check_health(self) -> tuple[bool, str]:
      """Run the system health check if enabled."""

      if not self.health_check_enabled:
         return True, "Health check disabled"


      try:
        status = get_system_status(cpu_interval=None)
           
        if status.is_healthy:
           return True, "System healthy"
             
        detail_parts: list[str] = []

        if status.cpu_percent >= 90.0:
           detail_parts.append(f"CPU {status.cpu_percent:.1f}%")

        if status.memory_percent >= 90.0:
           detail_parts.append(f"Memory {status.memory_percent:.1f}%")

        if status.disk_usage_percent >= 95.0:
           detail_parts.append(f"Disk {status.disk_usage_percent:.1f}%")

        return False, "Unhealthy: " + ", ".join(detail_parts)

      except Exception as exc:    
        return True, f"Health check failed (fail-open): {exc}"

    def evaluate(
        self,
        attempt_id: Optional[str] = None,
    ) -> PolicyDecision:
        """Run all governance checks and return a decision.

        Checks are evaluated in order: circuit breaker, rate limiter,
        health.  All checks run regardless of earlier failures so the
        audit log captures a complete picture.

        Args:
            attempt_id: Optional correlation ID for audit events.

        Returns:
            A :class:`PolicyDecision` describing whether the attempt
            may proceed and why.
        """
        denial_reasons: list[str] = []

        # 1. Circuit breaker
        cb_status = self.circuit_breaker.status()
        if not cb_status.can_proceed:
            reason = (
                f"Circuit breaker is {cb_status.state} "
                f"({cb_status.consecutive_failures} consecutive failures)"
            )
            denial_reasons.append(reason)
            self.audit_log.emit(
                category="circuit_breaker",
                severity="warning",
                action="blocked",
                detail=reason,
                attempt_id=attempt_id,
            )

        # 2. Rate limiter
        rl_status = self.rate_limiter.check()
        if not rl_status.allowed:
            reason = (
                f"Rate limit exceeded: {rl_status.current_count}/"
                f"{rl_status.max_attempts} attempts in "
                f"{rl_status.window_seconds}s window"
            )
            denial_reasons.append(reason)
            self.audit_log.emit(
                category="rate_limit",
                severity="warning",
                action="blocked",
                detail=reason,
                attempt_id=attempt_id,
            )

        # 3. Health check
        health_ok, health_detail = self._check_health()
        if not health_ok:
            denial_reasons.append(health_detail)
            self.audit_log.emit(
                category="health_check",
                severity="warning",
                action="blocked",
                detail=health_detail,
                attempt_id=attempt_id,
            )

        allowed = len(denial_reasons) == 0

        # Record the overall policy decision
        rl_remaining = max(0, rl_status.max_attempts - rl_status.current_count)
        self.audit_log.emit(
            category="policy",
            severity="info" if allowed else "warning",
            action="allowed" if allowed else "denied",
            detail="All governance checks passed" if allowed
            else "; ".join(denial_reasons),
            metadata={
                "circuit_state": cb_status.state,
                "rate_limit_remaining": rl_remaining,
                "health_ok": health_ok,
            },
            attempt_id=attempt_id,
        )

        return PolicyDecision(
            allowed=allowed,
            reasons=tuple(denial_reasons),
            circuit_state=cb_status.state,
            rate_limit_remaining=rl_remaining,
            health_ok=health_ok,
        )

    def record_outcome(
        self,
        success: bool,
        attempt_id: Optional[str] = None,
    ) -> None:
        """Record the outcome of a change attempt.

        Updates the circuit breaker and consumes a rate-limit slot.
        Emits an audit event for the outcome.

        Args:
            success: Whether the change attempt succeeded.
            attempt_id: Optional correlation ID.
        """
        # Consume rate-limit slot
        self.rate_limiter.acquire()

        if success:
            self.circuit_breaker.record_success()
            self.audit_log.emit(
                category="lifecycle",
                severity="info",
                action="attempt_succeeded",
                detail="Change attempt completed successfully",
                attempt_id=attempt_id,
            )
        else:
            self.circuit_breaker.record_failure()
            self.audit_log.emit(
                category="lifecycle",
                severity="warning",
                action="attempt_failed",
                detail="Change attempt failed",
                attempt_id=attempt_id,
            )
