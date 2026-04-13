"""Shared world-state registry for the autonomy loop."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorldStateStore:
    """Thread-safe in-memory snapshot of the system's current world state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "version": 0,
            "last_updated": None,
            "goal": "",
            "active_plan": (),
            "active_tasks": (),
            "observations": {},
            "constraints": {},
            "resources": {},
            "predictions": {},
        }

    def update(self, **changes: Any) -> dict[str, Any]:
        with self._lock:
            for key, value in changes.items():
                if value is None:
                    continue
                if key in {"observations", "constraints", "resources", "predictions"}:
                    current = dict(self._state.get(key, {}))
                    current.update(dict(value))
                    self._state[key] = current
                elif key in {"active_plan", "active_tasks"}:
                    self._state[key] = tuple(value)
                else:
                    self._state[key] = value
            self._state["version"] = int(self._state["version"]) + 1
            self._state["last_updated"] = _utcnow_iso()
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def reset(self) -> None:
        with self._lock:
            self._state = {
                "version": 0,
                "last_updated": None,
                "goal": "",
                "active_plan": (),
                "active_tasks": (),
                "observations": {},
                "constraints": {},
                "resources": {},
                "predictions": {},
            }


world_state_store = WorldStateStore()


def update_world_state(**changes: Any) -> dict[str, Any]:
    """Merge observations into the shared world state and return a snapshot."""

    return world_state_store.update(**changes)


def get_world_state() -> dict[str, Any]:
    """Return a defensive copy of the current world state."""

    return world_state_store.snapshot()
