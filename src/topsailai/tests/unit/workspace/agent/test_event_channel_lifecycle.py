"""Unit tests for the shared event channel lifecycle.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Verify sharing, reference counting, and registry installation
"""

import os
import socket
import tempfile
from pathlib import Path

import pytest

from topsailai.events.subscribers import fanout
from topsailai.events.subscribers.fanout import (
    get_subscription_registry,
    set_subscription_registry,
)
from topsailai.workspace.event_channel.config import EventChannelConfig
from topsailai.workspace.event_channel.lifecycle import (
    get_or_start_event_channel_server,
    release_event_channel_server,
    reset_event_channel_lifecycle,
    resolve_event_channel_socket_path,
)


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
    """Yield a short temporary directory suitable for a Unix socket path.

    pytest's ``tmp_path`` is unusable here: the per-file runner nests its base
    temp directory under the project, which pushes a socket path past the
    108-byte ``AF_UNIX`` limit and makes ``bind`` fail with ``OSError: AF_UNIX
    path too long``. A directory created directly under the system temp root
    stays short regardless of where the runner puts its own base temp directory.
    """
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


def test_start_creates_a_live_socket_and_installs_the_registry(socket_dir):
    socket_path = str(socket_dir / "events.sock")

    server = get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )

    assert server.is_running()
    assert os.path.exists(socket_path)
    assert get_subscription_registry() is server.registry


def test_second_caller_reuses_the_same_server(socket_dir):
    socket_path = str(socket_dir / "events.sock")

    first = get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )
    second = get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )

    assert first is second


def test_different_session_gets_a_different_server(socket_dir):
    first = get_or_start_event_channel_server(
        session_id="s1",
        pid=1234,
        config=_config(),
        socket_path=str(socket_dir / "a.sock"),
    )
    second = get_or_start_event_channel_server(
        session_id="s2",
        pid=1234,
        config=_config(),
        socket_path=str(socket_dir / "b.sock"),
    )

    assert first is not second
    assert first.is_running()
    assert second.is_running()


def test_release_keeps_the_server_alive_until_the_last_reference(socket_dir):
    socket_path = str(socket_dir / "events.sock")
    first = get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )
    get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )

    release_event_channel_server(session_id="s1", pid=1234, server=first)

    assert first.is_running()
    assert os.path.exists(socket_path)


def test_last_release_stops_the_server_and_removes_the_socket(socket_dir):
    socket_path = str(socket_dir / "events.sock")
    server = get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )

    release_event_channel_server(session_id="s1", pid=1234, server=server)

    assert not server.is_running()
    assert not os.path.exists(socket_path)


def test_last_release_detaches_the_process_wide_registry(socket_dir):
    socket_path = str(socket_dir / "events.sock")
    server = get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )
    assert get_subscription_registry() is server.registry

    release_event_channel_server(session_id="s1", pid=1234, server=server)

    assert fanout._registry is None


def test_release_with_a_mismatched_server_is_ignored(socket_dir):
    socket_path = str(socket_dir / "events.sock")
    server = get_or_start_event_channel_server(
        session_id="s1", pid=1234, config=_config(), socket_path=socket_path
    )
    other = get_or_start_event_channel_server(
        session_id="s2",
        pid=1234,
        config=_config(),
        socket_path=str(socket_dir / "other.sock"),
    )

    release_event_channel_server(session_id="s1", pid=1234, server=other)

    assert server.is_running()
    assert os.path.exists(socket_path)


def test_release_of_an_unknown_key_is_a_no_op():
    release_event_channel_server(session_id="missing", pid=999)

    assert fanout._registry is None


def test_reset_stops_every_server(socket_dir):
    first = get_or_start_event_channel_server(
        session_id="s1",
        pid=1234,
        config=_config(),
        socket_path=str(socket_dir / "a.sock"),
    )
    second = get_or_start_event_channel_server(
        session_id="s2",
        pid=1234,
        config=_config(),
        socket_path=str(socket_dir / "b.sock"),
    )

    reset_event_channel_lifecycle()

    assert not first.is_running()
    assert not second.is_running()
    assert fanout._registry is None


def test_resolve_socket_path_uses_the_session_scoped_convention():
    path = resolve_event_channel_socket_path("abc")

    assert path.endswith(f"abc.{os.getpid()}.session.events.sock")
