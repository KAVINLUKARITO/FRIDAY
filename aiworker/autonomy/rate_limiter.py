"""Sliding-window rate limiter for the autonomy loop.

Prevents rapid mutation by limiting how many iterations can run
within a configurable time window. No threads, no randomness.
"""
from __future__ import annotations
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class RateLimiterConfig:
    max_calls: int = 10
    window_seconds: float = 60.0


class RateLimitExceeded(Exception):
    """Raised when rate limit would be exceeded."""


class RateLimiter:
    def __init__(self, config: RateLimiterConfig | None = None) -> None:
        self._config = config or RateLimiterConfig()
        self._timestamps: Deque[float] = deque()

    def allow(self) -> bool:
        """Return True if a call is allowed right now."""
        self._evict()
        return len(self._timestamps) < self._config.max_calls

    def record(self) -> None:
        """Record that a call occurred now. Raises RateLimitExceeded if over limit."""
        self._evict()
        if len(self._timestamps) >= self._config.max_calls:
            raise RateLimitExceeded(
                f"Rate limit: {self._config.max_calls} calls per "
                f"{self._config.window_seconds}s exceeded."
            )
        self._timestamps.append(time.monotonic())

    def remaining(self) -> int:
        """Return calls remaining in current window."""
        self._evict()
        return max(0, self._config.max_calls - len(self._timestamps))

    def to_dict(self) -> dict:
        self._evict()
        return {
            "calls_in_window": len(self._timestamps),
            "max_calls": self._config.max_calls,
            "window_seconds": self._config.window_seconds,
            "remaining": self.remaining(),
        }

    def _evict(self) -> None:
        cutoff = time.monotonic() - self._config.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
