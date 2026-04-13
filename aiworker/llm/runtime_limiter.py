"""Single-runtime limiter to enforce one active model invocation."""

from __future__ import annotations

from threading import Lock


class RuntimeLimiter:
    """Thread-safe limiter that allows only one active runtime section."""

    def __init__(self) -> None:
        self._lock = Lock()

    def acquire(self) -> None:
        self._lock.acquire()

    def release(self) -> None:
        self._lock.release()

    def is_busy(self) -> bool:
        acquired = self._lock.acquire(blocking=False)
        if acquired:
            self._lock.release()
            return False
        return True
