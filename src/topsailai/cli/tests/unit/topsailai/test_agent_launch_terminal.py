"""Tests for the selectable background terminal mechanisms."""

import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import time
import uuid
from pathlib import Path
from unittest.mock import patch
import pytest
from cli_topsailai import agent_launch_terminal as terminal

from test_agent_launch_terminal_helpers import *

def test_resolve_mechanism_accepts_raw_without_external_binary():
    """The preferred new-process mechanism needs no external binary."""
    assert terminal.resolve_mechanism("raw") == "raw"


@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_resolve_mechanism_fails_closed_when_binary_is_absent(mechanism):
    """An explicitly selected absent mechanism is never silently replaced."""
    with patch.object(terminal.shutil, "which", return_value=None):
        with pytest.raises(terminal.TerminalUnavailable) as error:
            terminal.resolve_mechanism(mechanism)
    message = str(error.value)
    assert mechanism in message
    assert "not installed or not found in PATH" in message
    assert "--agent-mode raw" in message


def test_resolve_mechanism_rejects_unknown_name():
    """Only the documented mechanisms are accepted."""
    with pytest.raises(terminal.TerminalUnavailable, match="unsupported background mechanism"):
        terminal.resolve_mechanism("screen")


def test_resolve_mechanism_rejects_tmux_without_environment_option():
    """A tmux that cannot forward the identity environment is unusable."""
    with patch.object(terminal.shutil, "which", return_value="/usr/bin/tmux"), \
         patch("cli_topsailai.project_scope._tmux_supports_environment_option",
               return_value=False):
        with pytest.raises(terminal.TerminalUnavailable, match="new-session -e"):
            terminal.resolve_mechanism("tmux")


def test_resolve_mechanism_accepts_installed_terminal_binaries():
    """Installed tmux and dtach are accepted unchanged."""
    with patch.object(terminal.shutil, "which", return_value="/usr/bin/tool"), \
         patch("cli_topsailai.project_scope._tmux_supports_environment_option",
               return_value=True):
        assert terminal.resolve_mechanism("tmux") == "tmux"
        assert terminal.resolve_mechanism("dtach") == "dtach"


@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_prepare_attempt_creates_private_resources(home, mechanism):
    """Each attempt owns a 0700 directory and a unique control socket path."""
    first = terminal.prepare_attempt(mechanism, "session-1")
    second = terminal.prepare_attempt(mechanism, "session-1")
    assert first.directory != second.directory
    assert first.token != second.token
    assert stat.S_IMODE(first.directory.stat().st_mode) == 0o700
    assert first.control_path.parent == first.directory
    assert first.request_path.parent == first.directory
    if mechanism == "tmux":
        assert first.session_name and first.tmux_socket
        assert first.dtach_path is None
    else:
        assert first.dtach_path is not None
        assert first.session_name is None


def test_prepare_attempt_rejects_overlong_control_path(tmp_path, monkeypatch):
    """An AF_UNIX path that cannot bind fails closed before any spawn."""
    deep = tmp_path / ("d" * 60) / ("e" * 60)
    monkeypatch.setenv("TOPSAILAI_HOME", str(deep))
    with pytest.raises(terminal.TerminalUnavailable, match="too long for AF_UNIX"):
        terminal.prepare_attempt("tmux", "session-1")


def test_write_request_is_private_and_exclusive(home):
    """The request file is created 0600 and never overwritten."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    terminal.write_request(attempt.request_path, {"kind": "x", "token": "t"})
    assert stat.S_IMODE(attempt.request_path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        terminal.write_request(attempt.request_path, {"kind": "y"})


def test_build_command_preserves_identity_aliases_and_cwd(home):
    """tmux forwards both identity aliases and the workspace directory."""
    attempt = terminal.prepare_attempt("tmux", "session-1")
    environment = {
        "SESSION_ID": "session-1",
        "TOPSAILAI_SESSION_ID": "session-1",
        "PATH": "/usr/bin",
    }
    command = terminal.build_command(attempt, ["python", "entry.py"], "/work/proj", environment)
    assert command[:5] == ["tmux", "-L", attempt.tmux_socket, "new-session", "-d"]
    assert "-c" in command and command[command.index("-c") + 1] == "/work/proj"
    assert "SESSION_ID=session-1" in command
    assert "TOPSAILAI_SESSION_ID=session-1" in command
    assert "PATH=/usr/bin" in command
    assert command[-3:] == [
        "--internal-workspace-agent-supervisor",
        str(attempt.request_path),
        str(attempt.control_path),
    ]


def test_build_command_dtach_uses_private_socket(home):
    """dtach detaches through its own private socket and keeps the supervisor argv."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    command = terminal.build_command(attempt, ["python", "entry.py"], "/work/proj", None)
    assert command[:3] == ["dtach", "-n", str(attempt.dtach_path)]
    assert command[-3:] == [
        "--internal-workspace-agent-supervisor",
        str(attempt.request_path),
        str(attempt.control_path),
    ]


def test_open_listener_binds_private_socket(home):
    """The control socket is bound before the container starts and is 0600."""
    attempt = terminal.prepare_attempt("tmux", "session-1")
    listener = terminal.open_listener(attempt)
    try:
        assert stat.S_IMODE(attempt.control_path.stat().st_mode) == 0o600
    finally:
        listener.close()


def test_remove_tree_logs_every_deletion(home, capsys):
    """Attempt cleanup reports each removed file and the directory."""
    attempt = terminal.prepare_attempt("dtach", "session-1")
    terminal.write_request(attempt.request_path, {"kind": "x"})
    terminal._remove_tree(attempt.directory)
    output = capsys.readouterr().out
    assert "Removed terminal attempt file" in output
    assert "Removed terminal attempt directory" in output
    assert not attempt.directory.exists()


def test_terminal_module_does_not_own_driver_custody():
    """The terminal transport must not duplicate the approved custody proof."""
    source = Path(terminal.__file__).read_text(encoding="utf-8")
    assert "stop_owned_driver" not in source
    assert "driver_ownership" not in source


def test_background_default_is_raw_and_never_uses_terminal_transport(tmp_path):
    """A background launch without -m stays on the independent new process."""
    from cli_topsailai.agent_launch import launch_configured_agent

    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())), \
         patch("cli_topsailai.agent_launch_background.launch_background", return_value={
             "launcher_pid": 4321, "log_path": str(tmp_path / "fixed.agent-launch.log"),
         }) as launch, \
         patch("cli_topsailai.agent_launch_terminal.submit_terminal") as submit:
        assert launch_configured_agent(str(tmp_path), mode=None, background=True) == 0
    launch.assert_called_once()
    submit.assert_not_called()


@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_background_unavailable_mechanism_fails_closed(tmp_path, capsys, mechanism):
    """An absent mechanism reports a preparation failure and spawns nothing."""
    from cli_topsailai.agent_launch import launch_configured_agent

    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())), \
         patch.object(terminal.shutil, "which", return_value=None), \
         patch("cli_topsailai.agent_launch_background.launch_background") as launch, \
         patch("cli_topsailai.agent_launch_terminal.submit_terminal") as submit:
        assert launch_configured_agent(
            str(tmp_path), mode=mechanism, background=True) == 4
    launch.assert_not_called()
    submit.assert_not_called()
    captured = capsys.readouterr()
    assert "Agent launch preparation failed" in captured.err
    assert mechanism in captured.err
    assert "not installed or not found in PATH" in captured.err


@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_background_selected_mechanism_reaches_terminal_transport(tmp_path, mechanism):
    """An available selected mechanism is dispatched to the terminal transport."""
    from cli_topsailai.agent_launch import launch_configured_agent

    with patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               return_value=({}, set())), \
         patch.object(terminal.shutil, "which", return_value="/usr/bin/tool"), \
         patch("cli_topsailai.project_scope._tmux_supports_environment_option",
               return_value=True), \
         patch("cli_topsailai.agent_launch_background.launch_background") as launch, \
         patch("cli_topsailai.agent_launch_terminal.submit_terminal", return_value={
             "launcher_pid": 99, "log_path": str(tmp_path / "fixed.agent-launch.log"),
         }) as submit:
        assert launch_configured_agent(
            str(tmp_path), mode=mechanism, background=True) == 0
    launch.assert_not_called()
    assert submit.call_args.kwargs["mechanism"] == mechanism


def _capture_terminal_request(monkeypatch, transport, *, protocol_error):
    """Install the submit doubles and record the private request they write."""
    written = []
    attempt = _install_submit_doubles(monkeypatch, transport,
                                      protocol_error=protocol_error)
    monkeypatch.setattr(terminal, "write_request",
                        lambda path, request: written.append(dict(request)))
    return attempt, written


@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_terminal_request_records_non_interactive_flag(monkeypatch, mechanism):
    """A non-interactive launch is recorded for the terminal supervisor."""
    order = []
    transport = _FakeTransport(order)
    attempt, written = _capture_terminal_request(
        monkeypatch, transport, protocol_error=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        terminal.submit_terminal("/work/proj", "session-1", mechanism=mechanism,
                                 non_interactive=True)

    assert written
    assert all(request.get("non_interactive") is True for request in written)


@pytest.mark.parametrize("mechanism", ["tmux", "dtach"])
def test_terminal_request_omits_non_interactive_when_not_requested(monkeypatch, mechanism):
    """An ordinary terminal launch keeps the historical request shape."""
    order = []
    transport = _FakeTransport(order)
    attempt, written = _capture_terminal_request(
        monkeypatch, transport, protocol_error=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        terminal.submit_terminal("/work/proj", "session-1", mechanism=mechanism)

    assert written
    assert all("non_interactive" not in request for request in written)
