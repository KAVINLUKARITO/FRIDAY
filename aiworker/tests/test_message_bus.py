from __future__ import annotations

from datetime import datetime, timezone

from message_bus import Event, EventType, MessageBus


def test_subscribe_and_publish_calls_handler() -> None:
    message_bus = MessageBus()
    events: list[str] = []

    def handler(event: Event) -> None:
        events.append(event.source_agent)

    message_bus.subscribe(EventType.RECON_COMPLETE, handler)
    message_bus.publish(
        Event(
            event_type=EventType.RECON_COMPLETE,
            source_agent="tester",
            payload={},
            timestamp=datetime.now(timezone.utc),
            run_id="run-1",
        )
    )
    assert events == ["tester"]


def test_multiple_handlers_all_called() -> None:
    message_bus = MessageBus()
    calls: list[str] = []

    message_bus.subscribe(EventType.RECON_COMPLETE, lambda event: calls.append("one"))
    message_bus.subscribe(EventType.RECON_COMPLETE, lambda event: calls.append("two"))
    message_bus.publish(
        Event(
            event_type=EventType.RECON_COMPLETE,
            source_agent="tester",
            payload={},
            timestamp=datetime.now(timezone.utc),
            run_id="run-1",
        )
    )
    assert calls == ["one", "two"]


def test_handler_exception_does_not_propagate() -> None:
    message_bus = MessageBus()
    message_bus.subscribe(EventType.RECON_COMPLETE, lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
    message_bus.publish(
        Event(
            event_type=EventType.RECON_COMPLETE,
            source_agent="tester",
            payload={},
            timestamp=datetime.now(timezone.utc),
            run_id="run-1",
        )
    )


def test_unsubscribe_removes_handler() -> None:
    message_bus = MessageBus()
    calls: list[str] = []

    def handler(event: Event) -> None:
        calls.append("called")

    message_bus.subscribe(EventType.RECON_COMPLETE, handler)
    message_bus.unsubscribe(EventType.RECON_COMPLETE, handler)
    message_bus.publish(
        Event(
            event_type=EventType.RECON_COMPLETE,
            source_agent="tester",
            payload={},
            timestamp=datetime.now(timezone.utc),
            run_id="run-1",
        )
    )
    assert calls == []


def test_publish_with_no_subscribers_does_not_error() -> None:
    message_bus = MessageBus()
    message_bus.publish(
        Event(
            event_type=EventType.RECON_COMPLETE,
            source_agent="tester",
            payload={},
            timestamp=datetime.now(timezone.utc),
            run_id="run-1",
        )
    )
