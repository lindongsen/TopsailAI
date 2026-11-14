"""Integration test for the process-level event channel over a real socket.

The unit tests prove the lifecycle in isolation. This test proves the wiring:
a CLI entry point starts the channel once for the process, a real subscriber
connects over the real Unix domain socket, and a real event recorded through
the production collector arrives at that subscriber.

The channel belongs to the process, not to one agent turn, so the socket must
survive across turns and must be released only when the process exits.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Verify the process-started channel delivers real events
"""

import json
import os
import socket
import tempfile

import pytest

from topsailai.events import collector as collector_module
from topsailai.events.subscribers import fanout
from topsailai.events.subscribers.fanout import set_subscription_registry
from topsailai.workspace.event_channel import process_bootstrap
from topsailai.workspace.event_channel.lifecycle import (
    reset_event_channel_lifecycle,
)


pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="Unix domain sockets are unavailable"
)


class Client:
    """Minimal event-channel client used by this test."""

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

    def close(self) -> None:
        """Close the client socket."""
        try:
            self.sock.close()
        except OSError:
            pass


@pytest.fixture
def socket_dir():
    """Provide a short temporary directory for the Unix domain socket.

    A Unix socket path is limited to about 108 bytes. The per-file test runner
    nests its base temporary directory inside the project, so ``tmp_path`` can
    exceed that limit and the bind fails with ``AF_UNIX path too long``. A
    directory created directly under the system temporary root stays short.
    """
    with tempfile.TemporaryDirectory(prefix="ec-") as directory:
        yield directory


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, socket_dir):
    """Isolate the channel lifecycle, the collector, and the events file."""
    monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", "1")
    monkeypatch.setenv(
        "TOPSAILAI_EVENTS_FILE_PATH", os.path.join(socket_dir, "recorded.events")
    )
    monkeypatch.setenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", "1")
    collector_module.reset_event_collector()
    reset_event_channel_lifecycle()
    process_bootstrap.reset_process_event_channel()
    try:
        yield
    finally:
        process_bootstrap.reset_process_event_channel()
        reset_event_channel_lifecycle()
        set_subscription_registry(None)
        collector_module.reset_event_collector()


def _start(session_id: str, socket_dir: str):
    """Start the process channel bound to a short socket path."""
    socket_path = os.path.join(socket_dir, "events.sock")
    return process_bootstrap.start_process_event_channel(
        session_id=session_id, socket_path=socket_path
    )


def test_process_start_creates_a_socket_a_subscriber_can_use(socket_dir):
    server = _start("wired-session", socket_dir)
    try:
        assert server is not None
        assert server.is_running()
        assert os.path.exists(server.socket_path)

        client = Client(server.socket_path)
        try:
            client.send({"type": "subscribe", "subscriber_id": "wired-sub"})
            confirmation = client.recv_until("subscribed")
            assert confirmation["subscriber_id"] == "wired-sub"
        finally:
            client.close()
    finally:
        process_bootstrap.stop_process_event_channel()


def test_a_real_recorded_event_reaches_the_subscriber(socket_dir):
    server = _start("wired-session", socket_dir)
    try:
        client = Client(server.socket_path)
        try:
            client.send({"type": "subscribe", "subscriber_id": "wired-sub"})
            client.recv_until("subscribed")

            collector_module.get_event_collector().record(
                "tool_call.start",
                payload={"tool_name": "wired_tool"},
                session_id="wired-session",
            )

            frame = client.recv_until("event")
            assert frame["event"]["event_type"] == "tool_call.start"
            assert frame["event"]["payload"]["tool_name"] == "wired_tool"
        finally:
            client.close()
    finally:
        process_bootstrap.stop_process_event_channel()


def test_stop_removes_the_socket_and_detaches_the_registry(socket_dir):
    server = _start("wired-session", socket_dir)
    socket_path = server.socket_path
    assert fanout._registry is server.registry

    process_bootstrap.stop_process_event_channel()

    assert not server.is_running()
    assert not os.path.exists(socket_path)
    assert fanout._registry is None
    assert process_bootstrap.get_process_event_channel_server() is None


def test_disabled_channel_creates_no_socket(monkeypatch):
    monkeypatch.setenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", "0")

    server = process_bootstrap.start_process_event_channel(
        session_id="disabled-session"
    )

    assert server is None
    assert fanout._registry is None


def test_repeated_start_in_one_process_returns_the_same_server(socket_dir):
    first = _start("shared-session", socket_dir)
    second = process_bootstrap.start_process_event_channel(
        session_id="shared-session"
    )
    try:
        assert first is second
        assert process_bootstrap.get_process_event_channel_server() is first
    finally:
        process_bootstrap.stop_process_event_channel()


def test_stop_is_idempotent(socket_dir):
    _start("wired-session", socket_dir)

    process_bootstrap.stop_process_event_channel()
    process_bootstrap.stop_process_event_channel()

    assert process_bootstrap.get_process_event_channel_server() is None
