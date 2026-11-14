"""Unit tests for the event channel hard invariants.

The channel is enabled by default, so it must be impossible for it to harm the
process it observes. These tests pin the three guarantees that make the default
safe: no startup failure escapes, no runtime failure escapes, and no shutdown
step can block or raise.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Verify the channel can never block or abnormally exit the process
"""

from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from topsailai.events.subscribers.fanout import (
    fan_out,
    get_subscription_registry_or_none,
    set_drop_observer,
    set_subscription_registry,
)
from topsailai.events.subscribers.registry import SubscriptionRegistry
from topsailai.events.subscribers.subscriber import Subscriber
from topsailai.events.models import Event
from topsailai.workspace.event_channel import lifecycle, process_bootstrap, server as server_module
from topsailai.workspace.event_channel.config import EventChannelConfig
from topsailai.workspace.event_channel.lifecycle import (
    get_or_start_event_channel_server,
    release_event_channel_server,
    reset_event_channel_lifecycle,
)
from topsailai.workspace.event_channel.server import EventChannelServer
from topsailai.workspace.event_channel.writer import EventWriter


pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="Unix domain sockets are unavailable"
)


@pytest.fixture(autouse=True)
def clean_lifecycle():
    """Drop every shared server and the process-wide registry around a test."""
    reset_event_channel_lifecycle()
    try:
        yield
    finally:
        reset_event_channel_lifecycle()
        set_subscription_registry(None)


@pytest.fixture
def socket_dir():
    """Yield a short temporary directory suitable for a Unix socket path."""
    with tempfile.TemporaryDirectory(prefix="ec-") as tmpdir:
        yield Path(tmpdir)


def _config(**overrides):
    """Build an enabled configuration with fast test timings."""
    values = dict(
        enabled=True,
        max_subscribers=4,
        queue_size=10,
        heartbeat_interval=0.2,
        heartbeat_timeout=1.0,
    )
    values.update(overrides)
    return EventChannelConfig(**values)


def _server(socket_dir, name="events.sock", **overrides):
    """Build a server bound to a short socket path."""
    return EventChannelServer(
        socket_path=str(socket_dir / name),
        config=_config(**overrides),
        registry=SubscriptionRegistry(max_subscribers=4, queue_size=10),
        read_timeout=0.2,
        reaper_interval=0.2,
    )


def test_start_failure_leaves_no_socket_file(monkeypatch, socket_dir):
    """A failure after the bind must remove the socket it already created."""
    server = _server(socket_dir)
    monkeypatch.setattr(
        server_module,
        "restrict_socket_permissions",
        Mock(side_effect=OSError("cannot chmod")),
    )

    with pytest.raises(OSError):
        server.start()

    assert not Path(server.socket_path).exists()
    assert server.is_running() is False


def test_start_failure_after_bind_removes_the_socket(monkeypatch, socket_dir):
    """A failure after the bind must still clean the socket up."""
    server = _server(socket_dir)
    monkeypatch.setattr(
        server_module,
        "restrict_socket_permissions",
        Mock(side_effect=OSError("cannot chmod")),
    )

    with pytest.raises(OSError):
        server.start()

    assert not Path(server.socket_path).exists()
    assert server.is_running() is False


def test_start_failure_does_not_escape_the_process_bootstrap(
    monkeypatch, socket_dir
):
    """A startup failure must degrade to no channel instead of raising."""
    monkeypatch.setattr(
        process_bootstrap,
        "get_event_channel_config",
        lambda: _config(),
    )
    monkeypatch.setattr(
        process_bootstrap,
        "get_or_start_event_channel_server",
        Mock(side_effect=OSError("cannot bind")),
    )

    result = process_bootstrap.start_process_event_channel(
        session_id="hardening-session",
        socket_path=str(socket_dir / "boot.sock"),
    )

    assert result is None
    assert process_bootstrap.get_process_event_channel_server() is None


def test_stop_never_raises_when_a_step_fails(monkeypatch, socket_dir):
    """Shutdown runs from atexit, so a failing step must not raise."""
    server = _server(socket_dir)
    server.start()
    monkeypatch.setattr(
        server, "_close_listener", Mock(side_effect=RuntimeError("boom"))
    )

    server.stop()

    assert server.is_running() is False


def test_stop_is_bounded_even_when_a_thread_ignores_the_signal(
    monkeypatch, socket_dir
):
    """Shutdown must not wait indefinitely for a thread that will not stop."""
    server = _server(socket_dir)
    server.start()

    stuck = threading.Thread(target=lambda: time.sleep(30), daemon=True)
    stuck.start()
    server._thread = stuck

    started = time.monotonic()
    server.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    stuck.join(timeout=0)


def test_accept_loop_survives_a_transient_os_error(monkeypatch, socket_dir):
    """A transient accept error must not end the channel for the process."""
    monkeypatch.setattr(server_module, "DEFAULT_ACCEPT_RETRY_DELAY", 0.01)
    server = _server(socket_dir)

    class FlakySocket:
        """Accept raises once, then behaves like an idle listener."""

        def __init__(self):
            self.calls = 0

        def accept(self):
            self.calls += 1
            if self.calls == 1:
                raise OSError("transient accept failure")
            raise socket.timeout()

    flaky = FlakySocket()
    server._sock = flaky
    worker = threading.Thread(target=server._serve, daemon=True)
    worker.start()

    deadline = time.monotonic() + 5.0
    while flaky.calls < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    server._stop_event.set()
    worker.join(timeout=5.0)

    assert flaky.calls >= 3
    assert worker.is_alive() is False


def test_writer_contains_an_unexpected_failure():
    """A writer thread failure must be logged, never raised."""
    subscriber = Subscriber(subscriber_id="writer-sub", queue_size=4)
    subscriber.enqueue(Event.create(event_type="test.event", payload={}))
    connection = Mock()
    connection.send = Mock(side_effect=RuntimeError("send exploded"))
    writer = EventWriter(subscriber=subscriber, connection=connection)

    writer.run()

    assert writer.is_alive() is False


def test_atexit_stop_never_raises(monkeypatch):
    """The atexit handler must swallow every failure."""
    monkeypatch.setattr(
        process_bootstrap,
        "stop_process_event_channel",
        Mock(side_effect=RuntimeError("shutdown exploded")),
    )

    process_bootstrap._atexit_stop()


def test_take_started_server_detaches_when_the_lock_is_unavailable(monkeypatch):
    """A lock held by a dead thread must not hang interpreter exit."""
    monkeypatch.setattr(process_bootstrap, "LOCK_ACQUIRE_TIMEOUT", 0.05)
    sentinel = Mock()
    process_bootstrap._started_server = sentinel
    process_bootstrap._started_session_id = "locked-session"

    holder_ready = threading.Event()
    release_holder = threading.Event()

    def hold_lock():
        with process_bootstrap._bootstrap_lock:
            holder_ready.set()
            release_holder.wait(5.0)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    holder_ready.wait(5.0)
    try:
        started = time.monotonic()
        server, session_id = process_bootstrap._take_started_server()
        elapsed = time.monotonic() - started
    finally:
        release_holder.set()
        holder.join(timeout=5.0)

    assert server is sentinel
    assert session_id == "locked-session"
    assert process_bootstrap._started_server is None
    # A blocking acquire would wait for the holder to release the lock, which
    # only happens after this call returns. The bound is what makes interpreter
    # exit safe, so it must be asserted rather than assumed.
    assert elapsed < 1.0


def test_lifecycle_restores_the_previous_registry_when_start_fails(
    monkeypatch, socket_dir
):
    """A failed start must not detach a registry another server still uses."""
    previous = SubscriptionRegistry(max_subscribers=2, queue_size=5)
    set_subscription_registry(previous)
    monkeypatch.setattr(
        EventChannelServer, "start", Mock(side_effect=OSError("cannot bind"))
    )

    with pytest.raises(OSError):
        get_or_start_event_channel_server(
            session_id="restore-session",
            pid=1234,
            config=_config(),
            socket_path=str(socket_dir / "restore.sock"),
        )

    assert get_subscription_registry_or_none() is previous


def test_release_stops_the_server_outside_the_lifecycle_lock(socket_dir):
    """Stopping joins threads, so it must never run while holding the lock."""
    server = get_or_start_event_channel_server(
        session_id="lock-session",
        pid=4321,
        config=_config(),
        socket_path=str(socket_dir / "lock.sock"),
    )
    observed = {}

    def record_lock_state():
        observed["locked"] = lifecycle._event_channel_lock.locked()

    server.stop = record_lock_state

    release_event_channel_server(session_id="lock-session", pid=4321, server=server)

    assert observed["locked"] is False


def test_fan_out_never_waits_for_the_registry_lock():
    """The producer must not block when a registry mutation holds the lock."""
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=100)
    registry.register("blocked", ())
    set_subscription_registry(registry)
    holding = threading.Event()
    release = threading.Event()

    def hold_registry_lock():
        with registry._lock:
            holding.set()
            release.wait(5.0)

    holder = threading.Thread(target=hold_registry_lock, daemon=True)
    holder.start()
    assert holding.wait(5.0)

    started = time.monotonic()
    delivered = fan_out(Event(event_type="tool_call.start", payload={}))
    elapsed = time.monotonic() - started
    release.set()
    holder.join(5.0)

    assert elapsed < 0.5, f"fan_out waited {elapsed:.3f}s for the registry lock"
    assert delivered == 0


def test_fan_out_never_waits_for_the_subscriber_lock():
    """The producer must not block when a writer holds a subscriber lock."""
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=100)
    subscriber = registry.register("blocked", ())
    set_subscription_registry(registry)
    holding = threading.Event()
    release = threading.Event()

    def hold_subscriber_lock():
        with subscriber._lock:
            holding.set()
            release.wait(5.0)

    holder = threading.Thread(target=hold_subscriber_lock, daemon=True)
    holder.start()
    assert holding.wait(5.0)

    started = time.monotonic()
    fan_out(Event(event_type="tool_call.start", payload={}))
    elapsed = time.monotonic() - started
    release.set()
    holder.join(5.0)

    assert elapsed < 0.5, f"fan_out waited {elapsed:.3f}s for the subscriber lock"


def test_fan_out_never_waits_for_the_drop_observer():
    """A slow observer must not delay the producer that counted the drop."""
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=1)
    registry.register("full", ())
    set_subscription_registry(registry)
    entered = threading.Event()
    release = threading.Event()

    def slow_observer(stats):
        entered.set()
        release.wait(5.0)

    set_drop_observer(slow_observer)
    # The queue holds one event, so the first fan-out fills it and only the
    # second one overflows and counts a drop.
    fan_out(Event(event_type="tool_call.start", payload={}))
    fan_out(Event(event_type="tool_call.start", payload={}))
    assert entered.wait(5.0), "the observer never ran"

    started = time.monotonic()
    fan_out(Event(event_type="tool_call.end", payload={}))
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 0.5, f"fan_out waited {elapsed:.3f}s for the drop observer"
