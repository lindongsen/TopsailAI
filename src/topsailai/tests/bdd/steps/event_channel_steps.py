"""Real UDS event-channel acceptance steps.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Drive the real event channel server over a real Unix domain socket
"""

import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from topsailai.events.models import Event
from topsailai.events.subscribers import (
    SubscriptionRegistry,
    fan_out,
    set_subscription_registry,
)
from topsailai.workspace.event_channel import EventChannelConfig, EventChannelServer

RECV_TIMEOUT = 5.0


def _wait_for(predicate, timeout=RECV_TIMEOUT, interval=0.01):
    """Poll a predicate until it becomes true or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _connect(state, subscriber_id, event_types=None):
    """Open a real UDS link and complete the subscribe handshake."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(RECV_TIMEOUT)
    sock.connect(state.socket_path)
    frame = {"type": "subscribe", "subscriber_id": subscriber_id}
    if event_types:
        frame["filter"] = {"event_types": event_types}
    sock.sendall(json.dumps(frame).encode("utf-8") + b"\n")
    confirmation = _read_frame(sock)
    assert confirmation["type"] == "subscribed", confirmation
    assert confirmation["subscriber_id"] == subscriber_id
    return sock


def _read_frame(sock):
    """Read exactly one JSONL frame from a link."""
    buffer = b""
    while b"\n" not in buffer:
        chunk = sock.recv(65536)
        if not chunk:
            raise AssertionError("link closed before a frame arrived")
        buffer += chunk
    line, _, _ = buffer.partition(b"\n")
    return json.loads(line.decode("utf-8"))


def _send(sock, frame):
    """Send one JSONL frame."""
    sock.sendall(json.dumps(frame).encode("utf-8") + b"\n")


@pytest.fixture
def channel_state(bdd_tmp_path):
    """Own one real server, its registry, and every link opened by a scenario."""
    state = SimpleNamespace(
        socket_path=str(bdd_tmp_path / "events.sock"),
        server=None,
        registry=None,
        links={},
        recorded=[],
    )
    try:
        yield state
    finally:
        for sock in state.links.values():
            try:
                sock.close()
            except OSError:
                pass
        if state.server is not None:
            state.server.stop()
            assert not state.server.is_running()
            assert not __import__("os").path.exists(state.socket_path)
        set_subscription_registry(None)


@given(
    parsers.parse('an event channel serving session "{session}"'),
    target_fixture="channel_state",
)
def start_channel(channel_state, session):
    """Start the real server with production defaults."""
    return _start(channel_state, session, queue_size=100, heartbeat_timeout=5.0)


@given(
    parsers.parse(
        'an event channel serving session "{session}" with a {timeout} second heartbeat timeout'
    ),
    target_fixture="channel_state",
)
def start_channel_with_timeout(channel_state, session, timeout):
    """Start the real server with a short heartbeat timeout."""
    return _start(channel_state, session, queue_size=100, heartbeat_timeout=float(timeout))


@given(
    parsers.parse('an event channel serving session "{session}" with a {size} event queue'),
    target_fixture="channel_state",
)
def start_channel_with_queue(channel_state, session, size):
    """Start the real server with a small per-subscriber queue."""
    return _start(channel_state, session, queue_size=int(size), heartbeat_timeout=5.0)


def _start(state, session, queue_size, heartbeat_timeout):
    """Start a real server and install its registry for fan-out."""
    state.session = session
    state.registry = SubscriptionRegistry(max_subscribers=8, queue_size=queue_size)
    set_subscription_registry(state.registry)
    config = EventChannelConfig(
        enabled=True,
        max_subscribers=8,
        queue_size=queue_size,
        heartbeat_interval=0.2,
        heartbeat_timeout=heartbeat_timeout,
    )
    state.server = EventChannelServer(
        socket_path=state.socket_path,
        config=config,
        registry=state.registry,
        read_timeout=0.2,
        reaper_interval=0.1,
    )
    state.server.start()
    assert state.server.is_running()
    return state


@when(
    parsers.parse(
        'a subscriber "{subscriber_id}" connects and subscribes to every event type'
    )
)
def subscribe_all(channel_state, subscriber_id):
    """Subscribe without a filter."""
    channel_state.links[subscriber_id] = _connect(channel_state, subscriber_id)


@when(
    parsers.parse('a subscriber "{subscriber_id}" connects and subscribes to "{pattern}"')
)
def subscribe_filtered(channel_state, subscriber_id, pattern):
    """Subscribe with one filter pattern."""
    channel_state.links[subscriber_id] = _connect(
        channel_state, subscriber_id, [pattern]
    )


@when(parsers.parse('the session records a "{event_type}" event'))
def record_event(channel_state, event_type):
    """Record one event through the real fan-out entry point."""
    event = Event(event_type=event_type, payload={"marker": event_type})
    channel_state.recorded.append(event)
    fan_out(event)


@then(parsers.parse('subscriber "{subscriber_id}" receives that event over the link'))
def receives_event(channel_state, subscriber_id):
    """Assert the pushed frame carries the recorded event."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event"
    assert frame["event"]["event_type"] == channel_state.recorded[-1].event_type


@then(parsers.parse('subscriber "{subscriber_id}" receives only the "{event_type}" event'))
def receives_only(channel_state, subscriber_id, event_type):
    """Assert the filtered event arrives and the rejected one never does."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event"
    assert frame["event"]["event_type"] == event_type

    channel_state.links[subscriber_id].settimeout(0.3)
    with pytest.raises(socket.timeout):
        _read_frame(channel_state.links[subscriber_id])


@when(parsers.parse("the subscriber sends heartbeat sequence {seq:d}"))
def send_heartbeat(channel_state, seq):
    """Send one heartbeat on the most recently opened link."""
    sock = list(channel_state.links.values())[-1]
    _send(sock, {"type": "heartbeat", "seq": seq})


@then(parsers.parse("the server acknowledges heartbeat sequence {seq:d}"))
def heartbeat_ack(channel_state, seq):
    """Assert the acknowledgement echoes the client sequence number."""
    frame = _read_frame(list(channel_state.links.values())[-1])
    assert frame == {"type": "heartbeat_ack", "seq": seq}


@then(parsers.parse('subscriber "{subscriber_id}" is still registered'))
def still_registered(channel_state, subscriber_id):
    """Assert the subscriber survived the heartbeat exchange."""
    assert channel_state.registry.get(subscriber_id) is not None


@when("the subscriber closes the link")
def close_link(channel_state):
    """Close the most recently opened link."""
    sock = list(channel_state.links.values())[-1]
    sock.close()


@then(parsers.parse('subscriber "{subscriber_id}" is no longer registered'))
def not_registered(channel_state, subscriber_id):
    """Assert the server released the subscriber after the link ended."""
    assert _wait_for(lambda: channel_state.registry.get(subscriber_id) is None)


@then("a later recorded event is delivered to nobody")
def delivered_to_nobody(channel_state):
    """Assert fan-out reports no delivery once every link is gone."""
    assert _wait_for(lambda: len(channel_state.registry) == 0)
    assert fan_out(Event(event_type="tool_call.start", payload={})) == 0


@when(parsers.parse('the same subscriber "{subscriber_id}" reconnects'))
def reconnect(channel_state, subscriber_id):
    """Reconnect with the same client-generated identity."""
    channel_state.links[subscriber_id] = _connect(channel_state, subscriber_id)


@then(parsers.parse('only one link exists for subscriber "{subscriber_id}"'))
def one_link(channel_state, subscriber_id):
    """Assert the registry holds exactly one entry for the identity."""
    assert _wait_for(lambda: len(channel_state.registry) == 1)
    assert channel_state.registry.get(subscriber_id) is not None


@then("an event recorded after the reconnect arrives exactly once")
def arrives_once(channel_state):
    """Assert the new link receives the event and no duplicate follows."""
    event = Event(event_type="tool_call.start", payload={"after": "reconnect"})
    assert fan_out(event) == 1

    sock = list(channel_state.links.values())[-1]
    frame = _read_frame(sock)
    assert frame["type"] == "event"
    assert frame["event"]["payload"] == {"after": "reconnect"}

    sock.settimeout(0.3)
    with pytest.raises(socket.timeout):
        _read_frame(sock)


@when("the subscriber unsubscribes")
def unsubscribe(channel_state):
    """Send an explicit unsubscribe frame."""
    _send(list(channel_state.links.values())[-1], {"type": "unsubscribe"})


@then("the server confirms the unsubscribe")
def unsubscribe_confirmed(channel_state):
    """Assert the confirmation frame arrives before the link closes."""
    frame = _read_frame(list(channel_state.links.values())[-1])
    assert frame["type"] == "unsubscribed"


@when("the subscriber stops sending heartbeats")
def stop_heartbeats(channel_state):
    """Keep the link open but stop all liveness signals."""
    assert len(channel_state.registry) == 1


@then(
    parsers.parse('subscriber "{subscriber_id}" is reclaimed without an explicit disconnect')
)
def reclaimed(channel_state, subscriber_id):
    """Assert the reaper removes a silent subscriber."""
    assert _wait_for(lambda: channel_state.registry.get(subscriber_id) is None)


@when(parsers.parse("the subscriber stops reading while {count:d} events are recorded"))
def stop_reading(channel_state, count):
    """Record events while the subscriber never reads its link."""
    channel_state.recorded = []
    started = time.monotonic()
    for index in range(count):
        event = Event(event_type="tool_call.start", payload={"index": index})
        channel_state.recorded.append(event)
        fan_out(event)
    channel_state.record_elapsed = time.monotonic() - started


@then(parsers.parse("recording all {count:d} events completes without blocking"))
def recording_not_blocked(channel_state, count):
    """Assert the producer finished promptly for every event."""
    assert len(channel_state.recorded) == count
    assert channel_state.record_elapsed < 1.0


@then("the subscriber queue stays bounded instead of growing without limit")
def queue_bounded(channel_state):
    """Assert the bounded queue never exceeds its configured capacity."""
    subscriber = channel_state.registry.snapshot()[0]
    assert subscriber.queue_size == 2
    assert subscriber.size <= subscriber.queue_size
