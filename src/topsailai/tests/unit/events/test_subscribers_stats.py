"""Unit tests for event-channel delivery counters and the drop observer seam.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Verify cumulative counters, fan-out accounting, and observer isolation
"""

import threading

import pytest

from topsailai.events.models import Event
from topsailai.events.subscribers import (
    EventChannelStats,
    Subscriber,
    SubscriptionRegistry,
    fan_out,
    get_event_channel_stats,
    reset_event_channel_stats,
    set_drop_observer,
    set_subscription_registry,
)


def _event(event_type: str = "tool_call.start") -> Event:
    """Build a minimal event for tests."""
    return Event(event_type=event_type, payload={})


@pytest.fixture(autouse=True)
def _isolated_state():
    """Give every test its own registry, counters, and observer."""
    set_subscription_registry(None)
    reset_event_channel_stats()
    set_drop_observer(None)
    yield
    set_subscription_registry(None)
    reset_event_channel_stats()
    set_drop_observer(None)


def test_stats_start_at_zero():
    stats = EventChannelStats()

    assert stats.snapshot() == (0, 0)
    assert stats.delivered_total == 0
    assert stats.dropped_total == 0


def test_record_delivery_counts_delivery_without_drop():
    stats = EventChannelStats()

    stats.record_delivery(False)

    assert stats.snapshot() == (1, 0)


def test_record_delivery_counts_delivery_and_drop():
    stats = EventChannelStats()

    stats.record_delivery(True)

    assert stats.snapshot() == (1, 1)


def test_reset_clears_both_counters():
    stats = EventChannelStats()
    stats.record_delivery(True)

    stats.reset()

    assert stats.snapshot() == (0, 0)


def test_stats_are_thread_safe():
    stats = EventChannelStats()

    def worker():
        for _ in range(200):
            stats.record_delivery(True)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert stats.snapshot() == (800, 800)


def test_fan_out_counts_one_delivery_per_matching_subscriber():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=10)
    registry.register("a", ())
    registry.register("b", ())
    set_subscription_registry(registry)

    delivered = fan_out(_event())

    assert delivered == 2
    assert get_event_channel_stats().snapshot() == (2, 0)


def test_fan_out_skips_non_matching_subscribers():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=10)
    registry.register("a", ("tool_call.*",))
    registry.register("b", ("llm.*",))
    set_subscription_registry(registry)

    delivered = fan_out(_event("tool_call.start"))

    assert delivered == 1
    assert get_event_channel_stats().snapshot() == (1, 0)


def test_fan_out_counts_drop_when_queue_is_full():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=1)
    registry.register("a", ())
    set_subscription_registry(registry)

    fan_out(_event("tool_call.start"))
    fan_out(_event("tool_call.end"))

    assert get_event_channel_stats().snapshot() == (2, 1)


def test_fan_out_without_registry_counts_nothing():
    delivered = fan_out(_event())

    assert delivered == 0
    assert get_event_channel_stats().snapshot() == (0, 0)


def test_drop_observer_is_not_called_for_ordinary_delivery():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=10)
    registry.register("a", ())
    set_subscription_registry(registry)
    calls = []
    set_drop_observer(lambda stats: calls.append(stats.snapshot()))

    fan_out(_event())

    assert calls == []


def test_drop_observer_receives_cumulative_totals_on_drop():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=1)
    registry.register("a", ())
    set_subscription_registry(registry)
    calls = []
    set_drop_observer(lambda stats: calls.append(stats.snapshot()))

    fan_out(_event("tool_call.start"))
    fan_out(_event("tool_call.end"))

    assert calls == [(2, 1)]


def test_drop_observer_failure_does_not_break_fan_out():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=1)
    registry.register("a", ())
    set_subscription_registry(registry)

    def boom(stats):
        raise RuntimeError("observer exploded")

    set_drop_observer(boom)

    fan_out(_event("tool_call.start"))
    delivered = fan_out(_event("tool_call.end"))

    assert delivered == 1
    assert get_event_channel_stats().snapshot() == (2, 1)


def test_detaching_observer_stops_notifications():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=1)
    registry.register("a", ())
    set_subscription_registry(registry)
    calls = []
    set_drop_observer(lambda stats: calls.append(stats.snapshot()))
    set_drop_observer(None)

    fan_out(_event("tool_call.start"))
    fan_out(_event("tool_call.end"))

    assert calls == []


def test_subscriber_own_drop_counter_is_independent_of_process_totals():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=1)
    subscriber = registry.register("a", ())
    set_subscription_registry(registry)

    fan_out(_event("tool_call.start"))
    fan_out(_event("tool_call.end"))

    assert subscriber.dropped == 1
    assert get_event_channel_stats().dropped_total == 1


def test_stats_survive_subscriber_removal():
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=1)
    registry.register("a", ())
    set_subscription_registry(registry)
    fan_out(_event("tool_call.start"))
    fan_out(_event("tool_call.end"))

    registry.unregister("a")

    assert get_event_channel_stats().dropped_total == 1
