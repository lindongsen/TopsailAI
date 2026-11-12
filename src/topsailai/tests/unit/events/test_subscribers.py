"""Unit tests for the event-channel subscriber layer.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Verify filtering, bounded queues, isolation, and fan-out behavior
"""

import threading

import pytest

from topsailai.events.models import Event
from topsailai.events.subscribers import (
    Subscriber,
    SubscriptionRegistry,
    fan_out,
    get_subscription_registry,
    matches_event_type,
    set_subscription_registry,
)


def _event(event_type: str = "tool_call.start") -> Event:
    """Build a minimal event for tests."""
    return Event(event_type=event_type, payload={})


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Give every test its own process-wide registry."""
    set_subscription_registry(None)
    yield
    set_subscription_registry(None)


def test_matches_event_type_accepts_all_when_filter_empty():
    assert matches_event_type("anything.at.all", ()) is True


def test_matches_event_type_supports_wildcard_and_prefix():
    assert matches_event_type("tool_call.start", ("*",)) is True
    assert matches_event_type("tool_call.start", ("tool_call.*",)) is True
    assert matches_event_type("tool_call.start", ("tool_call.start",)) is True


def test_matches_event_type_rejects_unrelated_pattern():
    assert matches_event_type("tool_call.start", ("llm.*",)) is False
    assert matches_event_type("tool_call.start", ("tool_call",)) is False


def test_subscriber_requires_non_empty_id():
    with pytest.raises(ValueError):
        Subscriber(subscriber_id="")


def test_subscriber_drops_oldest_when_queue_is_full():
    subscriber = Subscriber("s1", queue_size=3)
    events = [_event(f"e{i}") for i in range(5)]
    for event in events:
        subscriber.enqueue(event)

    queued = subscriber.snapshot()
    assert [event.event_type for event in queued] == ["e2", "e3", "e4"]
    assert subscriber.dropped == 2


def test_subscriber_enqueue_reports_drop():
    subscriber = Subscriber("s1", queue_size=1)
    assert subscriber.enqueue(_event("a")) is False
    assert subscriber.enqueue(_event("b")) is True
    assert subscriber.dropped == 1


def test_subscriber_drain_returns_insertion_order_and_empties_queue():
    subscriber = Subscriber("s1", queue_size=10)
    for index in range(3):
        subscriber.enqueue(_event(f"e{index}"))

    drained = subscriber.drain()
    assert [event.event_type for event in drained] == ["e0", "e1", "e2"]
    assert subscriber.size == 0


def test_subscriber_drain_with_count_keeps_remainder():
    subscriber = Subscriber("s1", queue_size=10)
    for index in range(4):
        subscriber.enqueue(_event(f"e{index}"))

    first = subscriber.drain(2)
    assert [event.event_type for event in first] == ["e0", "e1"]
    assert subscriber.size == 2


def test_subscriber_staleness_follows_touch():
    subscriber = Subscriber("s1")
    assert subscriber.is_stale(0) is False
    assert subscriber.is_stale(60) is False
    subscriber.touch()
    assert subscriber.idle_seconds() >= 0


def test_registry_register_and_unregister():
    registry = SubscriptionRegistry()
    subscriber = registry.register("s1", ["tool_call.*"])
    assert subscriber is not None
    assert registry.get("s1") is subscriber
    assert len(registry) == 1

    assert registry.unregister("s1") is subscriber
    assert registry.get("s1") is None
    assert len(registry) == 0


def test_registry_replaces_entry_on_reconnect():
    registry = SubscriptionRegistry()
    first = registry.register("s1")
    second = registry.register("s1")

    assert second is not first
    assert registry.get("s1") is second
    assert len(registry) == 1


def test_registry_rejects_new_subscriber_when_full():
    registry = SubscriptionRegistry(max_subscribers=1)
    assert registry.register("s1") is not None
    assert registry.register("s2") is None
    assert len(registry) == 1


def test_registry_allows_existing_id_when_full():
    registry = SubscriptionRegistry(max_subscribers=1)
    registry.register("s1")
    assert registry.register("s1") is not None


def test_registry_stale_subscribers_respects_timeout():
    registry = SubscriptionRegistry()
    registry.register("s1")
    assert registry.stale_subscribers(0) == []
    assert registry.stale_subscribers(3600) == []


def test_fan_out_without_registry_is_noop():
    assert fan_out(_event()) == 0


def test_fan_out_delivers_only_to_matching_subscribers():
    registry = get_subscription_registry()
    tool_subscriber = registry.register("tools", ["tool_call.*"])
    llm_subscriber = registry.register("llm", ["llm.*"])

    delivered = fan_out(_event("tool_call.start"))

    assert delivered == 1
    assert tool_subscriber.size == 1
    assert llm_subscriber.size == 0


def test_fan_out_reaches_every_matching_subscriber():
    registry = get_subscription_registry()
    first = registry.register("a")
    second = registry.register("b")

    assert fan_out(_event("custom.event")) == 2
    assert first.size == 1
    assert second.size == 1


def test_fan_out_isolates_slow_subscriber_from_others():
    registry = get_subscription_registry()
    slow = registry.register("slow", queue_size=1)
    fast = registry.register("fast", queue_size=100)

    for index in range(5):
        fan_out(_event(f"e{index}"))

    assert slow.size == 1
    assert slow.dropped == 4
    assert fast.size == 5
    assert fast.dropped == 0


def test_fan_out_never_raises_when_subscriber_fails():
    class BrokenRegistry(SubscriptionRegistry):
        def snapshot(self):
            raise RuntimeError("boom")

    set_subscription_registry(BrokenRegistry())
    assert fan_out(_event()) == 0


def test_fan_out_is_safe_under_concurrent_producers():
    registry = get_subscription_registry()
    subscriber = registry.register("s1", queue_size=10000)

    def produce():
        for index in range(200):
            fan_out(_event(f"e{index}"))

    threads = [threading.Thread(target=produce) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert subscriber.size == 800


def test_collector_record_fans_out_to_subscriber(file_config):
    from topsailai.events.collector import EventCollector

    registry = get_subscription_registry()
    subscriber = registry.register("s1", ["tool_call.*"])
    collector = EventCollector(file_config)
    try:
        collector.record("tool_call.start", payload={"tool_name": "x"})
        collector.record("llm.response.raw", payload={})

        queued = subscriber.snapshot()
        assert [event.event_type for event in queued] == ["tool_call.start"]
    finally:
        collector.close()


def test_collector_record_does_not_fan_out_when_disabled(disabled_config):
    from topsailai.events.collector import EventCollector

    registry = get_subscription_registry()
    subscriber = registry.register("s1")
    collector = EventCollector(disabled_config)
    try:
        collector.record("tool_call.start", payload={})
        assert subscriber.size == 0
    finally:
        collector.close()


def test_collector_record_fans_out_before_backend_flush(file_config):
    """Fan-out must not wait for the backend flush interval."""
    from topsailai.events.collector import EventCollector

    registry = get_subscription_registry()
    subscriber = registry.register("s1")
    collector = EventCollector(file_config)
    try:
        collector.record("custom.event", payload={})
        # No flush() call: the subscriber must already hold the event.
        assert subscriber.size == 1
    finally:
        collector.close()


def test_collector_record_stays_non_blocking_with_full_subscriber_queue(file_config):
    from topsailai.events.collector import EventCollector

    registry = get_subscription_registry()
    subscriber = registry.register("s1", queue_size=1)
    collector = EventCollector(file_config)
    try:
        for index in range(50):
            collector.record(f"custom.event{index}", payload={})

        assert subscriber.size == 1
        assert subscriber.dropped == 49
    finally:
        collector.close()
