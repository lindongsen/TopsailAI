"""Unit tests for the process-level event channel bootstrap.

The channel belongs to the process, so these tests exercise the bootstrap
directly instead of going through an agent run. Every test keeps the socket in a
short temporary directory, because a Unix domain socket path is limited to about
108 bytes and the per-file test runner nests its base directory deep inside the
project.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Verify the process-level event channel bootstrap contract
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from topsailai.workspace.event_channel import process_bootstrap
from topsailai.workspace.event_channel.config import EventChannelConfig


@pytest.fixture(name="socket_dir")
def socket_dir_fixture():
    """Provide a short temporary directory for the socket file."""
    with tempfile.TemporaryDirectory(prefix="ec-") as directory:
        yield directory


@pytest.fixture(name="clean_state")
def clean_state_fixture():
    """Reset the process bootstrap state before and after each test."""
    process_bootstrap.reset_process_event_channel()
    yield
    process_bootstrap.reset_process_event_channel()


def _enabled_config() -> EventChannelConfig:
    """Build an enabled channel configuration for the tests."""
    return EventChannelConfig(enabled=True)


def test_disabled_channel_returns_none_and_creates_no_socket(
    monkeypatch, socket_dir, clean_state
):
    """A disabled channel must not start a server or create a socket."""
    monkeypatch.setattr(
        process_bootstrap,
        "get_event_channel_config",
        lambda: EventChannelConfig(enabled=False),
    )
    socket_path = str(Path(socket_dir) / "disabled.sock")

    server = process_bootstrap.start_process_event_channel(
        session_id="disabled-session", socket_path=socket_path
    )

    assert server is None
    assert process_bootstrap.get_process_event_channel_server() is None
    assert not Path(socket_path).exists()


def test_enabled_channel_starts_a_server_and_creates_the_socket(
    monkeypatch, socket_dir, clean_state
):
    """An enabled channel must start one server and expose its socket."""
    monkeypatch.setattr(
        process_bootstrap, "get_event_channel_config", _enabled_config
    )
    socket_path = str(Path(socket_dir) / "enabled.sock")

    server = process_bootstrap.start_process_event_channel(
        session_id="enabled-session", socket_path=socket_path
    )

    assert server is not None
    assert Path(socket_path).exists()
    assert process_bootstrap.get_process_event_channel_server() is server


def test_repeated_start_returns_the_same_server(
    monkeypatch, socket_dir, clean_state
):
    """A second start in one process must reuse the running server."""
    monkeypatch.setattr(
        process_bootstrap, "get_event_channel_config", _enabled_config
    )
    socket_path = str(Path(socket_dir) / "repeated.sock")

    first = process_bootstrap.start_process_event_channel(
        session_id="repeated-session", socket_path=socket_path
    )
    second = process_bootstrap.start_process_event_channel(
        session_id="repeated-session", socket_path=socket_path
    )

    assert first is not None
    assert second is first

    # One stop must be enough. A bootstrap that forwarded every call to the
    # shared lifecycle would inflate the reference count, so this single stop
    # would leave the socket behind.
    process_bootstrap.stop_process_event_channel()
    assert not Path(socket_path).exists()


def test_stop_removes_the_socket_and_clears_the_state(
    monkeypatch, socket_dir, clean_state
):
    """Stopping must release the socket and forget the server."""
    monkeypatch.setattr(
        process_bootstrap, "get_event_channel_config", _enabled_config
    )
    socket_path = str(Path(socket_dir) / "stopped.sock")
    process_bootstrap.start_process_event_channel(
        session_id="stopped-session", socket_path=socket_path
    )
    assert Path(socket_path).exists()

    process_bootstrap.stop_process_event_channel()

    assert not Path(socket_path).exists()
    assert process_bootstrap.get_process_event_channel_server() is None


def test_stop_without_a_server_is_safe(clean_state):
    """Stopping a channel that never started must not raise."""
    process_bootstrap.stop_process_event_channel()
    process_bootstrap.stop_process_event_channel()

    assert process_bootstrap.get_process_event_channel_server() is None


def test_start_failure_is_logged_and_never_raised(
    monkeypatch, socket_dir, clean_state, caplog
):
    """A startup failure must be swallowed so observability cannot break the CLI."""
    monkeypatch.setattr(
        process_bootstrap, "get_event_channel_config", _enabled_config
    )
    monkeypatch.setattr(
        process_bootstrap,
        "get_or_start_event_channel_server",
        Mock(side_effect=OSError("socket unavailable")),
    )

    with caplog.at_level("WARNING"):
        server = process_bootstrap.start_process_event_channel(
            session_id="failing-session",
            socket_path=str(Path(socket_dir) / "failing.sock"),
        )

    assert server is None
    assert process_bootstrap.get_process_event_channel_server() is None
    assert "socket unavailable" in caplog.text


def test_atexit_is_registered_once(monkeypatch, socket_dir, clean_state):
    """The exit handler must be registered exactly once per process."""
    monkeypatch.setattr(
        process_bootstrap, "get_event_channel_config", _enabled_config
    )
    register = Mock()
    monkeypatch.setattr(process_bootstrap.atexit, "register", register)
    socket_path = str(Path(socket_dir) / "atexit.sock")

    process_bootstrap.start_process_event_channel(
        session_id="atexit-session", socket_path=socket_path
    )
    process_bootstrap.stop_process_event_channel()
    process_bootstrap.start_process_event_channel(
        session_id="atexit-session", socket_path=socket_path
    )

    # The server registers its own stop handler too, so count only the
    # process-level handler this module owns. That handler is the guarded
    # wrapper, not ``stop_process_event_channel`` directly, because an atexit
    # handler that raises would change the process exit status.
    process_registrations = [
        call
        for call in register.call_args_list
        if call.args[0] is process_bootstrap._atexit_stop
    ]
    assert len(process_registrations) == 1


def test_reset_clears_the_state_so_a_new_server_can_start(
    monkeypatch, socket_dir, clean_state
):
    """Reset must allow a fresh startup after a previous server was released."""
    monkeypatch.setattr(
        process_bootstrap, "get_event_channel_config", _enabled_config
    )
    socket_path = str(Path(socket_dir) / "reset.sock")

    first = process_bootstrap.start_process_event_channel(
        session_id="reset-session", socket_path=socket_path
    )
    process_bootstrap.reset_process_event_channel()
    second = process_bootstrap.start_process_event_channel(
        session_id="reset-session", socket_path=socket_path
    )

    assert first is not None
    assert second is not None
    assert second is not first
