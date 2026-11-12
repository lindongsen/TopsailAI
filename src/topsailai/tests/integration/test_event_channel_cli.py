"""Integration tests for the event-channel subscriber CLI client.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Verify the CLI client subscribes, receives events, and honours ids
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from topsailai.events.models import Event
from topsailai.events.subscribers import (
    SubscriptionRegistry,
    fan_out,
    set_subscription_registry,
)
from topsailai.workspace.event_channel import EventChannelConfig, EventChannelServer

# The CLI modules bootstrap their own imports and are addressed by bare module
# name, matching the existing CLI test convention.
CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="Unix domain sockets are unavailable"
)


@pytest.fixture
def channel(tmp_path):
    """Start a real event channel server for the CLI client tests."""
    socket_path = str(tmp_path / "events.sock")
    registry = SubscriptionRegistry(max_subscribers=4, queue_size=100)
    set_subscription_registry(registry)
    config = EventChannelConfig(
        enabled=True,
        max_subscribers=4,
        queue_size=100,
        heartbeat_interval=0.2,
        heartbeat_timeout=5.0,
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


def test_generate_subscriber_id_is_unique():
    from topsailai_event_subscribe import generate_subscriber_id

    first = generate_subscriber_id()
    second = generate_subscriber_id()
    assert first != second
    assert first.startswith("sub-")


def test_client_receives_event_and_exits_at_limit(channel):
    from topsailai_event_subscribe import run_client

    server, socket_path, registry = channel
    result = {}

    def run():
        result["code"] = run_client(
            socket_path=socket_path,
            subscriber_id="cli-sub",
            event_types=None,
            heartbeat_interval=0.2,
            max_events=1,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    assert _wait_for(lambda: registry.get("cli-sub") is not None)
    fan_out(Event(event_type="tool_call.start", payload={"tool_name": "x"}))

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result["code"] == 0


def test_client_honours_event_type_filter(channel):
    from topsailai_event_subscribe import run_client

    server, socket_path, registry = channel
    result = {}

    def run():
        result["code"] = run_client(
            socket_path=socket_path,
            subscriber_id="cli-filtered",
            event_types=["llm.*"],
            heartbeat_interval=0.2,
            max_events=1,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    assert _wait_for(lambda: registry.get("cli-filtered") is not None)
    fan_out(Event(event_type="tool_call.start", payload={}))
    fan_out(Event(event_type="llm.response.raw", payload={"n": 1}))

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result["code"] == 0


def test_client_exits_when_server_stops(channel):
    from topsailai_event_subscribe import run_client

    server, socket_path, registry = channel
    result = {}

    def run():
        result["code"] = run_client(
            socket_path=socket_path,
            subscriber_id="cli-stop",
            event_types=None,
            heartbeat_interval=0.2,
            max_events=None,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    assert _wait_for(lambda: registry.get("cli-stop") is not None)
    server.stop()

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result["code"] == 0


def test_client_reports_connection_failure(tmp_path):
    from topsailai_event_subscribe import run_client

    code = run_client(
        socket_path=str(tmp_path / "missing.sock"),
        subscriber_id="cli-missing",
        event_types=None,
        heartbeat_interval=0.2,
        max_events=1,
    )
    assert code == 1


def test_discover_socket_paths_finds_session_socket(tmp_path, monkeypatch):
    import topsailai_event_subscribe as cli

    monkeypatch.setattr(cli, "FOLDER_WORKSPACE_TASK", str(tmp_path))

    assert cli.discover_socket_paths("session-x") == []

    wanted = tmp_path / "session-x.123.session.events.sock"
    wanted.write_text("", encoding="utf-8")
    (tmp_path / "session-x.456.session.events.sock").write_text("", encoding="utf-8")
    (tmp_path / "other.789.session.events.sock").write_text("", encoding="utf-8")
    (tmp_path / "session-x.123.session.meta").write_text("{}", encoding="utf-8")

    found = cli.discover_socket_paths("session-x")
    assert found == sorted(
        [
            str(wanted.resolve()),
            str((tmp_path / "session-x.456.session.events.sock").resolve()),
        ]
    )
