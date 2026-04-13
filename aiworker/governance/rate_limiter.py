"""Sliding-window rate limiter for change attempts.

Prevents the self-modification pipeline from executing more than a
configurable number of change attempts within a rolling time window.

The limiter is purely in-memory and uses monotonic time for
window calculations so it is unaffected by wall-clock adjustments.

No persistence, no threading, no external calls.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitStatus:
    """Snapshot of the rate limiter's current state.

    Attributes:
        allowed: Whether a new attempt is permitted right now.
        current_count: Number of attempts in the current window.
        max_attempts: Maximum attempts allowed per window.
        window_seconds: Length of the sliding window in seconds.
        seconds_until_available: Seconds until the next slot opens
            (``0.0`` when ``allowed`` is ``True``).
    """

    allowed: bool
    current_count: int
    max_attempts: int
    window_seconds: float
    seconds_until_available: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dictionary."""
        return {
            "allowed": self.allowed,
            "current_count": self.current_count,
            "max_attempts": self.max_attempts,
            "window_seconds": self.window_seconds,
            "seconds_until_available": round(self.seconds_until_available, 3),
        }


class RateLimiter:
    """In-memory sliding-window rate limiter.

    Args:
        max_attempts: Maximum number of attempts allowed within
            *window_seconds*.  Must be >= 1.
        window_seconds: Length of the sliding window in seconds.
            Must be > 0.
        clock: Optional callable returning the current monotonic time
            (defaults to :func:`time.monotonic`).  Injected for
            deterministic testing.

    Raises:
        ValueError: If parameters are out of range.
    """

    def __init__(
        self,
        max_attempts: int = 10,
        window_seconds: float = 60.0,
        clock: object = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(
                f"max_attempts must be >= 1, got {max_attempts}"
            )
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )

        self._max_attempts: int = max_attempts
        self._window_seconds: float = window_seconds
        self._clock = clock if callable(clock) else time.monotonic
        self._timestamps: deque[float] = deque()

    def _purge_expired(self, now: float) -> None:
        """Remove timestamps older than the sliding window."""
        cutoff = now - self._window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def check(self) -> RateLimitStatus:
        """Check whether a new attempt is allowed without consuming a slot.

        Returns:
            A :class:`RateLimitStatus` describing the current state.
        """
        now = self._clock()
        self._purge_expired(now)

        current = len(self._timestamps)
        allowed = current < self._max_attempts

        if allowed:
            seconds_until = 0.0
        elif self._timestamps:
            earliest = self._timestamps[0]
            seconds_until = max(
                0.0, (earliest + self._window_seconds) - now
            )
        else:
            seconds_until = 0.0

        return RateLimitStatus(
            allowed=allowed,
            current_count=current,
            max_attempts=self._max_attempts,
            window_seconds=self._window_seconds,
            seconds_until_available=seconds_until,
        )

    def acquire(self) -> RateLimitStatus:
        """Attempt to consume a rate-limit slot.

        If the limit has not been reached, records the current time and
        returns ``allowed=True``.  Otherwise returns ``allowed=False``
        without recording anything.

        Returns:
            A :class:`RateLimitStatus` reflecting the state *after*
            the acquisition attempt.
        """
        now = self._clock()
        self._purge_expired(now)

        if len(self._timestamps) < self._max_attempts:
            self._timestamps.append(now)

        return self.check()

    def reset(self) -> RateLimitStatus:
        """Clear all recorded timestamps.

        Returns:
            A fresh :class:`RateLimitStatus`.
        """
        self._timestamps.clear()
        return self.check()
