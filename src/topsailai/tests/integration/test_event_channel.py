"""Integration tests for the event channel over a real Unix domain socket.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Verify subscribe, push, heartbeat, unsubscribe, disconnect, reconnect
"""

import json
import os
import socket
import threading
import time

import pytest

from topsailai.events.models import Event
from topsailai.events.subscribers import fan_out, set_subscription_registry
from topsailai.workspace.event_channel import EventChannelConfig, EventChannelServer


pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="Unix domain sockets are unavailable"
)


class Client:
    """Minimal event-channel client used by the tests."""

    def __init__(self, socket_path: str):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect(socket_path)
        self._buffer = b""

    def send(self, frame: dict) -> None:
        """Send one JSONL frame."""
        self.sock.sendall(json.dumps(frame).encode("utf-8") + b"\n")

    def recv(self) -> dict:
        """Receive one JSONL frame."""
        while b"\n" not in self._buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("connection closed")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return json.loads(line.decode("utf-8"))

    def recv_until(self, frame_type: str, limit: int = 50) -> dict:
        """Receive frames until one matches the requested type."""
        for _ in range(limit):
            frame = self.recv()
            if frame.get("type") == frame_type:
                return frame
        raise AssertionError(f"frame {frame_type} not received")

    def subscribe(self, subscriber_id: str, event_types=None) -> dict:
        """Perform the subscribe handshake and return the confirmation."""
        payload = {"type": "subscribe", "subscriber_id": subscriber_id}
        if event_types is not None:
            payload["filter"] = {"event_types": event_types}
        self.send(payload)
        return self.recv()

    def close(self) -> None:
        """Close the client socket."""
        try:
            self.sock.close()
        except Exception:
            pass


@pytest.fixture
def channel(tmp_path):
    """Start a real event channel server on a temporary socket path."""
    socket_path = str(tmp_path / "events.sock")
    registry = None
    from topsailai.events.subscribers import SubscriptionRegistry

    registry = SubscriptionRegistry(max_subscribers=4, queue_size=100)
    set_subscription_registry(registry)
    config = EventChannelConfig(
        enabled=True,
        max_subscribers=4,
        queue_size=100,
        heartbeat_interval=0.2,
        heartbeat_timeout=1.0,
    )
    server = EventChannelServer(
        socket_path=socket_path,
        config=config,
        registry=registry,
        read_timeout=0.2,
        reaper_interval=0.2,
    )
    server.start()
    try:
        yield server, socket_path, registry
    finally:
        server.stop()
        set_subscription_registry(None)


def _wait_for(predicate, timeout=5.0, interval=0.02):
    """Poll a predicate until it becomes true or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_subscribe_receives_pushed_event(channel):
    server, socket_path, registry = channel
    client = Client(socket_path)
    try:
        confirmation = client.subscribe("sub-1")
        assert confirmation["type"] == "subscribed"
        assert confirmation["subscriber_id"] == "sub-1"

        assert _wait_for(lambda: registry.get("sub-1") is not None)
        fan_out(Event(event_type="tool_call.start", payload={"tool_name": "x"}))

        frame = client.recv_until("event")
        assert frame["event"]["event_type"] == "tool_call.start"
        assert frame["event"]["payload"]["tool_name"] == "x"
    finally:
        client.close()


def test_filter_excludes_unrequested_event_types(channel):
    server, socket_path, registry = channel
    client = Client(socket_path)
    try:
        client.subscribe("sub-1", ["llm.*"])
        assert _wait_for(lambda: registry.get("sub-1") is not None)

        fan_out(Event(event_type="tool_call.start", payload={}))
        fan_out(Event(event_type="llm.response.raw", payload={}))

        frame = client.recv_until("event")
        assert frame["event"]["event_type"] == "llm.response.raw"
    finally:
        client.close()


def test_heartbeat_is_acknowledged_with_same_seq(channel):
    server, socket_path, registry = channel
    client = Client(socket_path)
    try:
        client.subscribe("sub-1")
        assert _wait_for(lambda: registry.get("sub-1") is not None)

        client.send({"type": "heartbeat", "seq": 42})
        frame = client.recv_until("heartbeat_ack")
        assert frame["seq"] == 42
    finally:
        client.close()


def test_unsubscribe_closes_the_link(channel):
    server, socket_path, registry = channel
    client = Client(socket_path)
    try:
        client.subscribe("sub-1")
        assert _wait_for(lambda: registry.get("sub-1") is not None)

        client.send({"type": "unsubscribe"})
        frame = client.recv_until("unsubscribed")
        assert frame["subscriber_id"] == "sub-1"

        assert _wait_for(lambda: registry.get("sub-1") is None)
        with pytest.raises((EOFError, OSError)):
            client.recv()
    finally:
        client.close()


def test_disconnect_stops_sending_and_unregisters(channel):
    server, socket_path, registry = channel
    client = Client(socket_path)
    client.subscribe("sub-1")
    assert _wait_for(lambda: registry.get("sub-1") is not None)

    client.close()

    assert _wait_for(lambda: registry.get("sub-1") is None)


def test_reconnect_with_same_id_replaces_the_old_link(channel):
    server, socket_path, registry = channel
    first = Client(socket_path)
    try:
        first.subscribe("sub-1")
        assert _wait_for(lambda: registry.get("sub-1") is not None)

        second = Client(socket_path)
        try:
            second.subscribe("sub-1")
            assert _wait_for(lambda: registry.get("sub-1") is not None)

            fan_out(Event(event_type="custom.event", payload={"n": 1}))

            frame = second.recv_until("event")
            assert frame["event"]["payload"]["n"] == 1
            assert len(registry) == 1
        finally:
            second.close()
    finally:
        first.close()


def test_stale_subscriber_is_reclaimed_by_heartbeat_timeout(channel):
    server, socket_path, registry = channel
    client = Client(socket_path)
    try:
        client.subscribe("sub-1")
        assert _wait_for(lambda: registry.get("sub-1") is not None)

        # Stop sending heartbeats; the reaper must reclaim the subscriber.
        assert _wait_for(lambda: registry.get("sub-1") is None, timeout=6.0)
    finally:
        client.close()


def test_subscriber_limit_rejects_extra_subscriber(channel):
    server, socket_path, registry = channel
    clients = []
    try:
        for index in range(4):
            client = Client(socket_path)
            clients.append(client)
            assert client.subscribe(f"sub-{index}")["type"] == "subscribed"

        extra = Client(socket_path)
        clients.append(extra)
        frame = extra.subscribe("sub-overflow")
        assert frame["type"] == "error"
    finally:
        for client in clients:
            client.close()


def test_first_frame_must_be_subscribe(channel):
    server, socket_path, registry = channel
    client = Client(socket_path)
    try:
        client.send({"type": "heartbeat", "seq": 1})
        frame = client.recv()
        assert frame["type"] == "error"
    finally:
        client.close()


def test_server_stop_removes_socket_file(channel):
    server, socket_path, registry = channel
    assert os.path.exists(socket_path)
    server.stop()
    assert not os.path.exists(socket_path)
