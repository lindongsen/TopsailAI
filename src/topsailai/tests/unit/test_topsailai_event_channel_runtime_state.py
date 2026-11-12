"""Unit tests for exposing event-channel drop counts through Runtime Data.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Verify the Runtime Data mirror, the observer seam, and /runtime display
"""

import pytest

from topsailai.ai_base.runtime_data import RuntimeDataStore
from topsailai.events.subscribers import (
    EventChannelStats,
    reset_event_channel_stats,
    set_drop_observer,
    set_subscription_registry,
)
from topsailai.workspace.event_channel import runtime_state
from topsailai.workspace.plugin_instruction import runtime as runtime_instruction


class _FakeRuntime:
    """Minimal Agent runtime holding one Runtime Data Store."""

    def __init__(self):
        self.runtime_data = RuntimeDataStore()


class _FakeAgent:
    """Minimal Agent exposing the runtime attribute the mirror reads."""

    def __init__(self):
        self.runtime = _FakeRuntime()


@pytest.fixture(autouse=True)
def _isolated_state():
    """Give every test its own registry, counters, observer, and lease cache."""
    set_subscription_registry(None)
    reset_event_channel_stats()
    set_drop_observer(None)
    runtime_state.clear_event_channel_runtime_state()
    yield
    set_subscription_registry(None)
    reset_event_channel_stats()
    set_drop_observer(None)
    runtime_state.clear_event_channel_runtime_state()


@pytest.fixture
def fake_agent(monkeypatch):
    """Bind one fake Agent to both the thread-local and instruction lookups."""
    agent = _FakeAgent()
    monkeypatch.setattr(runtime_state, "get_agent_object", lambda: agent)
    monkeypatch.setattr(runtime_instruction, "get_ai_agent", lambda: agent)
    return agent


def test_publish_returns_false_without_an_agent(monkeypatch):
    monkeypatch.setattr(runtime_state, "get_agent_object", lambda: None)
    stats = EventChannelStats()
    stats.record_delivery(True)

    assert runtime_state.publish_event_channel_stats(stats) is False


def test_publish_returns_false_when_runtime_is_missing(monkeypatch):
    class _NoRuntime:
        runtime = None

    monkeypatch.setattr(runtime_state, "get_agent_object", lambda: _NoRuntime())
    stats = EventChannelStats()
    stats.record_delivery(True)

    assert runtime_state.publish_event_channel_stats(stats) is False


def test_publish_creates_one_active_state(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)

    assert runtime_state.publish_event_channel_stats(stats) is True

    snapshot = fake_agent.runtime.runtime_data.get(runtime_state.RUNTIME_STATE_KEY)
    assert snapshot is not None
    assert snapshot.value["dropped_total"] == 1
    assert snapshot.value["delivered_total"] == 1
    assert snapshot.value["phase"] == "dropping"


def test_publish_uses_delivering_phase_when_nothing_was_dropped(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(False)

    runtime_state.publish_event_channel_stats(stats)

    snapshot = fake_agent.runtime.runtime_data.get(runtime_state.RUNTIME_STATE_KEY)
    assert snapshot.value["phase"] == "delivering"
    assert snapshot.value["dropped_total"] == 0


def test_publish_updates_the_same_generation_on_repeated_drops(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)
    runtime_state.publish_event_channel_stats(stats)
    first = fake_agent.runtime.runtime_data.get(runtime_state.RUNTIME_STATE_KEY)

    stats.record_delivery(True)
    runtime_state.publish_event_channel_stats(stats)
    second = fake_agent.runtime.runtime_data.get(runtime_state.RUNTIME_STATE_KEY)

    assert second.revision == first.revision + 1
    assert second.value["dropped_total"] == 2


def test_publish_skips_when_the_total_did_not_change(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)
    runtime_state.publish_event_channel_stats(stats)
    first = fake_agent.runtime.runtime_data.get(runtime_state.RUNTIME_STATE_KEY)

    assert runtime_state.publish_event_channel_stats(stats) is False

    second = fake_agent.runtime.runtime_data.get(runtime_state.RUNTIME_STATE_KEY)
    assert second.revision == first.revision


def test_publish_carries_the_cumulative_total_after_a_gap(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)
    runtime_state.publish_event_channel_stats(stats)

    stats.record_delivery(True)
    stats.record_delivery(True)
    runtime_state.publish_event_channel_stats(stats)

    snapshot = fake_agent.runtime.runtime_data.get(runtime_state.RUNTIME_STATE_KEY)
    assert snapshot.value["dropped_total"] == 3


def test_publish_never_raises_when_the_store_rejects_the_value(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)

    def boom(*args, **kwargs):
        raise RuntimeError("store exploded")

    fake_agent.runtime.runtime_data.activate = boom

    assert runtime_state.publish_event_channel_stats(stats) is False


def test_install_attaches_the_mirror_to_the_drop_seam():
    import topsailai.events.subscribers.fanout as fanout

    runtime_state.install_event_channel_runtime_observer()

    assert fanout._drop_observer is runtime_state.publish_event_channel_stats


def test_uninstall_detaches_the_mirror():
    import topsailai.events.subscribers.fanout as fanout

    runtime_state.install_event_channel_runtime_observer()
    runtime_state.uninstall_event_channel_runtime_observer()

    assert fanout._drop_observer is None


def test_install_is_idempotent():
    import topsailai.events.subscribers.fanout as fanout

    runtime_state.install_event_channel_runtime_observer()
    runtime_state.install_event_channel_runtime_observer()

    assert fanout._drop_observer is runtime_state.publish_event_channel_stats


def test_clear_drops_cached_leases(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)
    runtime_state.publish_event_channel_stats(stats)

    runtime_state.clear_event_channel_runtime_state()
    stats.record_delivery(True)

    assert runtime_state.publish_event_channel_stats(stats) is True


def test_runtime_instruction_displays_drop_counts(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)
    stats.record_delivery(False)
    runtime_state.publish_event_channel_stats(stats)

    text = runtime_instruction.show_runtime()

    assert "Dropped total: 1" in text
    assert "Delivered total: 2" in text
    assert "Phase: dropping" in text


def test_runtime_instruction_get_displays_drop_counts(fake_agent):
    stats = EventChannelStats()
    stats.record_delivery(True)
    runtime_state.publish_event_channel_stats(stats)

    text = runtime_instruction.get_runtime(runtime_state.RUNTIME_STATE_KEY)

    assert "Dropped total: 1" in text


def test_retry_state_rendering_is_unchanged_by_the_new_fields(fake_agent):
    store = fake_agent.runtime.runtime_data
    store.activate(
        "llm.request.retry",
        owner_id="llm",
        value={
            "phase": "fault_retrying",
            "failed_attempts": 3,
            "next_retry_number": 4,
            "threshold": 3,
            "last_error_category": "timeout",
        },
        public=True,
    )

    text = runtime_instruction.show_runtime()

    assert "Phase: fault_retrying" in text
    assert "Failed attempts: 3" in text
    assert "Next retry number: 4" in text
    assert "Threshold: 3" in text
    assert "Last error category: timeout" in text
    assert "Dropped total" not in text
    assert "Delivered total" not in text


def test_display_whitelist_keeps_existing_field_order():
    fields = runtime_instruction._DISPLAY_VALUE_FIELDS

    assert fields[:5] == (
        "phase",
        "failed_attempts",
        "next_retry_number",
        "threshold",
        "last_error_category",
    )
    assert fields[5:] == ("dropped_total", "delivered_total")
