"""Immutable audit trail for the self-modification lifecycle.

Every significant action — validation, sandbox execution, approval
decision, policy check — is recorded as an :class:`AuditEvent`.
Events are append-only and immutable once created.

The :class:`AuditLog` stores events in memory with optional
persistence to the experience memory database.  It is the single
source of truth for answering "what happened and when".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional, Sequence

EventCategory = Literal[
    "validation",
    "sandbox",
    "approval",
    "policy",
    "circuit_breaker",
    "rate_limit",
    "health_check",
    "lifecycle",
]

EventSeverity = Literal["info", "warning", "error", "critical"]


@dataclass(frozen=True)
class AuditEvent:
    """A single immutable audit record.

    Attributes:
        event_id: Unique identifier (UUID4).
        timestamp: UTC ISO-8601 timestamp of when the event occurred.
        category: Classification of the event source.
        severity: Importance level of the event.
        action: Short verb-phrase describing what happened.
        detail: Human-readable explanation.
        metadata: Arbitrary key-value pairs for structured context.
        attempt_id: Optional link to a change attempt for correlation.
    """

    event_id: str
    timestamp: str
    category: EventCategory
    severity: EventSeverity
    action: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)
    attempt_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "category": self.category,
            "severity": self.severity,
            "action": self.action,
            "detail": self.detail,
            "metadata": dict(self.metadata),
            "attempt_id": self.attempt_id,
        }


def create_event(
    category: EventCategory,
    severity: EventSeverity,
    action: str,
    detail: str,
    metadata: Optional[dict[str, Any]] = None,
    attempt_id: Optional[str] = None,
) -> AuditEvent:
    """Factory function that stamps an event with a fresh ID and UTC time.

    Args:
        category: Event classification.
        severity: Importance level.
        action: Short verb-phrase (e.g. ``"validation_passed"``).
        detail: Human-readable description.
        metadata: Optional structured context.
        attempt_id: Optional correlation ID.

    Returns:
        A fully populated :class:`AuditEvent`.
    """
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        category=category,
        severity=severity,
        action=action,
        detail=detail,
        metadata=metadata or {},
        attempt_id=attempt_id,
    )


class AuditLog:
    """Append-only, queryable audit event store.

    Events are held in memory in insertion order.  The log supports
    filtering by category, severity, and time range.  No events are
    ever deleted or modified after insertion.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> AuditEvent:
        """Append an event to the log and return it unchanged.

        Args:
            event: The audit event to record.

        Returns:
            The same event (for chaining convenience).
        """
        self._events.append(event)
        return event

    def emit(
        self,
        category: EventCategory,
        severity: EventSeverity,
        action: str,
        detail: str,
        metadata: Optional[dict[str, Any]] = None,
        attempt_id: Optional[str] = None,
    ) -> AuditEvent:
        """Create and record an event in a single call.

        A convenience wrapper around :func:`create_event` followed by
        :meth:`record`.
        """
        event = create_event(
            category=category,
            severity=severity,
            action=action,
            detail=detail,
            metadata=metadata,
            attempt_id=attempt_id,
        )
        return self.record(event)

    @property
    def count(self) -> int:
        """Total number of recorded events."""
        return len(self._events)

    def all_events(self) -> Sequence[AuditEvent]:
        """Return all events in insertion order (immutable view)."""
        return tuple(self._events)

    def filter_by_category(self, category: EventCategory) -> list[AuditEvent]:
        """Return events matching *category*."""
        return [e for e in self._events if e.category == category]

    def filter_by_severity(self, severity: EventSeverity) -> list[AuditEvent]:
        """Return events matching *severity*."""
        return [e for e in self._events if e.severity == severity]

    def filter_by_attempt(self, attempt_id: str) -> list[AuditEvent]:
        """Return events linked to a specific change attempt."""
        return [e for e in self._events if e.attempt_id == attempt_id]

    def last_n(self, n: int) -> list[AuditEvent]:
        """Return the most recent *n* events (newest last)."""
        return list(self._events[-n:])

    def errors_and_critical(self) -> list[AuditEvent]:
        """Return all events with severity ``error`` or ``critical``."""
        return [
            e for e in self._events
            if e.severity in ("error", "critical")
        ]
