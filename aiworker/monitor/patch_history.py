"""Patch lifecycle history for the monitoring dashboard."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import threading
import uuid
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PatchEvent:
    id: str
    timestamp: str
    patch_type: str
    confidence: float
    validation_status: str
    file_changed: list[str] = field(default_factory=list)
    diff: str = ""
    result: str = ""
    root_cause: str = ""
    fix_proposal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PatchHistory:
    """Thread-safe append-only history of patch lifecycle events."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: deque[PatchEvent] = deque(maxlen=500)

    def record_event(
        self,
        patch_type: str,
        *,
        confidence: float = 0.0,
        validation_status: str = "pending",
        file_changed: list[str] | tuple[str, ...] | None = None,
        diff: str = "",
        result: str = "",
        root_cause: str = "",
        fix_proposal: str = "",
    ) -> PatchEvent:
        event = PatchEvent(
            id=uuid.uuid4().hex,
            timestamp=_utcnow_iso(),
            patch_type=patch_type,
            confidence=max(0.0, min(1.0, float(confidence))),
            validation_status=validation_status,
            file_changed=list(file_changed or ()),
            diff=diff,
            result=result,
            root_cause=root_cause,
            fix_proposal=fix_proposal,
        )
        with self._lock:
            self._events.append(event)
        return event

    def list_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for event in reversed(self._events)]

    def last_patch_time(self) -> str | None:
        with self._lock:
            return self._events[-1].timestamp if self._events else None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def latest_event(self) -> PatchEvent | None:
        with self._lock:
            return self._events[-1] if self._events else None

    def find_event(self, event_id: str) -> PatchEvent | None:
        with self._lock:
            for event in self._events:
                if event.id == event_id:
                    return event
        return None


patch_history = PatchHistory()
