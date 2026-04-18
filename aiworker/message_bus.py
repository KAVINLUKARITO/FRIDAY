from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable

from pydantic import BaseModel, Field

from aiworker.logger import get_logger


class EventType(str, Enum):
    RECON_COMPLETE = "recon.complete"
    SCAN_COMPLETE = "scan.complete"
    ANALYSIS_COMPLETE = "analysis.complete"
    EXPLOIT_VALIDATED = "exploit.validated"
    REPORT_READY = "report.ready"
    MARKET_DATA_UPDATED = "market.data_updated"
    SIGNAL_GENERATED = "signal.generated"
    RISK_APPROVED = "risk.approved"
    RISK_REJECTED = "risk.rejected"
    ORDER_EXECUTED = "order.executed"
    PORTFOLIO_UPDATED = "portfolio.updated"
    AGENT_ERROR = "agent.error"
    SYSTEM_SHUTDOWN = "system.shutdown"


class Event(BaseModel):
    event_type: EventType
    source_agent: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str


class MessageBus:
    """Synchronous, thread-safe in-process event bus."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscriptions: dict[EventType, list[Callable[[Event], None]]] = defaultdict(list)
        self._history: list[Event] = []
        self._logger = get_logger("message_bus")

    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        with self._lock:
            if handler not in self._subscriptions[event_type]:
                self._subscriptions[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        with self._lock:
            handlers = self._subscriptions.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)
            if not handlers and event_type in self._subscriptions:
                self._subscriptions.pop(event_type, None)

    def publish(self, event: Event) -> None:
        with self._lock:
            handlers = list(self._subscriptions.get(event.event_type, []))
            self._history.append(event)
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                self._logger.exception(
                    "handler failed for event %s from %s: %s",
                    event.event_type.value,
                    event.source_agent,
                    exc,
                )

    def clear(self) -> None:
        with self._lock:
            self._subscriptions.clear()
            self._history.clear()

    def history(self, run_id: str | None = None) -> list[Event]:
        with self._lock:
            events = list(self._history)
        if run_id is None:
            return events
        return [event for event in events if event.run_id == run_id]


bus = MessageBus()
