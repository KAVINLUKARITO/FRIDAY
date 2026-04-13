"""Circuit breaker for the autonomy loop.

States:
  CLOSED    normal operation, failures counted
  OPEN      all calls rejected immediately
  HALF_OPEN one trial call allowed; success -> CLOSED, failure -> OPEN
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    recovery_timeout: float = 60.0
    success_threshold: int = 1


class CircuitBreakerOpen(Exception):
    """Raised when circuit is OPEN."""


class CircuitBreaker:
    def __init__(self, config: Optional[CircuitBreakerConfig] = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state: BreakerState = BreakerState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._opened_at: Optional[float] = None

    @property
    def state(self) -> BreakerState:
        self._maybe_recover()
        return self._state

    def allow(self) -> bool:
        self._maybe_recover()
        return self._state in (BreakerState.CLOSED, BreakerState.HALF_OPEN)

    def record_success(self) -> None:
        self._maybe_recover()
        if self._state == BreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._close()
        elif self._state == BreakerState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        self._maybe_recover()
        if self._state == BreakerState.HALF_OPEN:
            self._open()
            return
        self._failure_count += 1
        if self._failure_count >= self._config.failure_threshold:
            self._open()

    def reset(self) -> None:
        self._close()

    def to_dict(self) -> dict:
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "opened_at": self._opened_at,
        }

    def _open(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = time.monotonic()
        self._success_count = 0

    def _close(self) -> None:
        self._state = BreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None

    def _maybe_recover(self) -> None:
        if self._state == BreakerState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self._config.recovery_timeout:
                self._state = BreakerState.HALF_OPEN
                self._success_count = 0
