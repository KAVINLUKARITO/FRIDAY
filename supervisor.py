from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class SupervisorState(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    ABORTED = "aborted"


@dataclass
class ActionRecord:
    action_hash: str
    timestamp: float
    count: int = 1


class Supervisor:
    """Lightweight execution supervisor for loop and retry control."""

    def __init__(
        self,
        max_steps: int = 100,
        max_retries: int = 3,
        repeat_threshold: int = 2,
        time_window: float = 60.0,
    ) -> None:
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.repeat_threshold = repeat_threshold
        self.time_window = time_window
        self.action_history: list[ActionRecord] = []
        self.step_count = 0
        self.retry_count = 0
        self.state = SupervisorState.HEALTHY
        self._replan_callback: Callable[[], None] | None = None
        self._abort_callback: Callable[[str], None] | None = None
        self.last_reason: str | None = None

    def register_callbacks(
        self,
        replan: Callable[[], None],
        abort: Callable[[str], None],
    ) -> None:
        """Register replanning and abort callbacks."""

        self._replan_callback = replan
        self._abort_callback = abort

    def _hash_action(self, action: dict[str, Any]) -> str:
        """Create a stable hash for action comparison."""

        action_str = json.dumps(action, sort_keys=True, default=str)
        return hashlib.md5(action_str.encode("utf-8")).hexdigest()

    def check_action(self, action: dict[str, Any]) -> tuple[bool, str | None]:
        """Check whether an action is safe to execute."""

        current_time = time.time()
        action_hash = self._hash_action(action)

        if self.step_count >= self.max_steps:
            self.state = SupervisorState.ABORTED
            self.last_reason = f"Max steps ({self.max_steps}) exceeded"
            self._abort(self.last_reason)
            return False, self.last_reason

        for record in self.action_history:
            if record.action_hash != action_hash:
                continue
            if current_time - record.timestamp < self.time_window:
                record.count += 1
                record.timestamp = current_time
                if record.count > self.repeat_threshold:
                    self.state = SupervisorState.WARNING
                    self.last_reason = f"Action repeated {record.count} times"
                    self.trigger_replan(self.last_reason)
                    return False, self.last_reason
                return True, None
            record.timestamp = current_time
            record.count = 1
            return True, None

        self.action_history.append(ActionRecord(action_hash=action_hash, timestamp=current_time))
        self._cleanup_history(current_time)
        return True, None

    def record_step(self) -> None:
        """Record a completed step."""

        self.step_count += 1
        if self.state is SupervisorState.WARNING:
            self.state = SupervisorState.HEALTHY

    def record_retry(self) -> bool:
        """Record a retry attempt and abort if retries are exhausted."""

        self.retry_count += 1
        if self.retry_count >= self.max_retries:
            self.state = SupervisorState.CRITICAL
            self.last_reason = f"Max retries ({self.max_retries}) exceeded"
            self._abort(self.last_reason)
            return False
        return True

    def record_success(self) -> None:
        """Reset retry counter after a successful step."""

        self.retry_count = 0
        if self.state is not SupervisorState.ABORTED:
            self.state = SupervisorState.HEALTHY

    def trigger_replan(self, reason: str) -> None:
        """Trigger replanning callback."""

        self.state = SupervisorState.WARNING
        self.last_reason = reason
        if self._replan_callback is not None:
            self._replan_callback()

    def get_state(self) -> SupervisorState:
        """Return current supervisor state."""

        return self.state

    def reset(self) -> None:
        """Reset supervisor state for a new task."""

        self.action_history.clear()
        self.step_count = 0
        self.retry_count = 0
        self.state = SupervisorState.HEALTHY
        self.last_reason = None

    def _abort(self, reason: str) -> None:
        if self._abort_callback is not None:
            self._abort_callback(reason)

    def _cleanup_history(self, current_time: float) -> None:
        self.action_history = [
            record
            for record in self.action_history
            if current_time - record.timestamp < self.time_window
        ]
