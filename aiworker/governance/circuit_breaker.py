"""Circuit breaker for the self-modification pipeline.

Implements the circuit breaker pattern to halt processing after a
configurable number of consecutive failures.  This prevents a
runaway loop of failing change attempts from wasting resources or
causing damage.

State machine::

    CLOSED  ──(failure threshold reached)──>  OPEN
    OPEN    ──(recovery_window elapsed)──>    HALF_OPEN
    HALF_OPEN ──(success)──>                  CLOSED
    HALF_OPEN ──(failure)──>                  OPEN

The breaker is purely in-memory and deterministic — given the same
sequence of success/failure signals it always reaches the same state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CircuitState = Literal["closed", "open", "half_open"]


@dataclass(frozen=True)
class CircuitStatus:
    """Snapshot of the circuit breaker's current state.

    Attributes:
        state: One of ``"closed"``, ``"open"``, or ``"half_open"``.
        consecutive_failures: Number of failures since last success.
        total_failures: Lifetime failure count.
        total_successes: Lifetime success count.
        failure_threshold: Failures needed to trip the breaker.
        can_proceed: ``True`` if the pipeline is allowed to execute.
    """

    state: CircuitState
    consecutive_failures: int
    total_failures: int
    total_successes: int
    failure_threshold: int
    can_proceed: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dictionary."""
        return {
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "failure_threshold": self.failure_threshold,
            "can_proceed": self.can_proceed,
        }


class CircuitBreaker:
    """In-memory circuit breaker for the change pipeline.

    Args:
        failure_threshold: Number of consecutive failures before the
            circuit opens.  Must be >= 1.
        recovery_after: Number of explicit :meth:`tick` calls (or
            successes from other operations) before a tripped breaker
            transitions from ``open`` to ``half_open``.  Must be >= 1.

    Raises:
        ValueError: If *failure_threshold* or *recovery_after* is < 1.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_after: int = 1,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(
                f"failure_threshold must be >= 1, got {failure_threshold}"
            )
        if recovery_after < 1:
            raise ValueError(
                f"recovery_after must be >= 1, got {recovery_after}"
            )

        self._failure_threshold: int = failure_threshold
        self._recovery_after: int = recovery_after

        self._state: CircuitState = "closed"
        self._consecutive_failures: int = 0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._ticks_since_open: int = 0

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def can_proceed(self) -> bool:
        """Whether the pipeline is allowed to execute.

        Returns ``True`` when the circuit is ``closed`` or
        ``half_open`` (probe attempt).
        """
        return self._state in ("closed", "half_open")

    def status(self) -> CircuitStatus:
        """Return an immutable snapshot of the breaker's state."""
        return CircuitStatus(
            state=self._state,
            consecutive_failures=self._consecutive_failures,
            total_failures=self._total_failures,
            total_successes=self._total_successes,
            failure_threshold=self._failure_threshold,
            can_proceed=self.can_proceed,
        )

    def record_success(self) -> CircuitStatus:
        """Signal a successful operation.

        Resets consecutive failures and transitions the circuit back to
        ``closed`` from any state.

        Returns:
            Updated :class:`CircuitStatus`.
        """
        self._total_successes += 1
        self._consecutive_failures = 0
        self._state = "closed"
        self._ticks_since_open = 0
        return self.status()

    def record_failure(self) -> CircuitStatus:
        """Signal a failed operation.

        Increments the consecutive failure counter.  If the threshold
        is reached (or the breaker was ``half_open``), the circuit
        transitions to ``open``.

        Returns:
            Updated :class:`CircuitStatus`.
        """
        self._total_failures += 1
        self._consecutive_failures += 1

        if self._state == "half_open":
            # Probe failed — re-open immediately.
            self._state = "open"
            self._ticks_since_open = 0
        elif self._consecutive_failures >= self._failure_threshold:
            self._state = "open"
            self._ticks_since_open = 0

        return self.status()

    def tick(self) -> CircuitStatus:
        """Advance the recovery timer by one unit.

        Call this periodically (or after each rejected request) to
        allow the breaker to transition from ``open`` to ``half_open``
        after ``recovery_after`` ticks.

        Has no effect when the circuit is ``closed`` or ``half_open``.

        Returns:
            Updated :class:`CircuitStatus`.
        """
        if self._state == "open":
            self._ticks_since_open += 1
            if self._ticks_since_open >= self._recovery_after:
                self._state = "half_open"
        return self.status()

    def reset(self) -> CircuitStatus:
        """Force the breaker back to ``closed`` and zero all counters.

        Intended for administrative override — use sparingly.

        Returns:
            Updated :class:`CircuitStatus`.
        """
        self._state = "closed"
        self._consecutive_failures = 0
        self._ticks_since_open = 0
        return self.status()
