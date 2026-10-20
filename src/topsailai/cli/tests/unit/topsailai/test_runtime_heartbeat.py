"""Heartbeat shortcut contracts using the installed CLI configuration.

Author: DawsonLin
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from cli_topsailai import runtime_cli, runtime_control, runtime_operations
from cli_topsailai import state, yaml_commands
from cli_topsailai.completer import tab_completer
from cli_topsailai.streaming import _handle_stream_command


@pytest.fixture
def runtime_scope(monkeypatch):
    """Load real commands while restoring shared interactive state afterward."""
    commands = yaml_commands.load_yaml_commands(
        str(Path(__file__).resolve().parents[3] / "topsailai.yaml"))
    monkeypatch.setattr(state, "yaml_commands", commands)
    monkeypatch.setattr(state, "current_scope", "runtime")
    monkeypatch.setattr(state, "current_session_id", "heartbeat-session")
    return commands


def test_scope_and_existing_actions(runtime_scope, monkeypatch):
    """Expose the new shortcut without removing prior shortcuts or handlers."""
    for name in ("heartbeat", "hard_interrupt", "soft_interrupt", "clear_interrupt",
                 "get_runtime_messages", "call_instruction", "fbt.force_retry"):
        assert yaml_commands.match_yaml_command(f"/control.{name}", "/fixture")
    assert set(runtime_control.get_control_actions()) >= {
        "heartbeat", "call_instruction", "get_runtime_messages", "get_session_messages",
        "hard_interrupt", "soft_interrupt", "clear_interrupt", "llm_control",
    }
    monkeypatch.setattr(state, "current_scope", "session")
    assert yaml_commands.match_yaml_command("/control.heartbeat", "/fixture")
    monkeypatch.setattr(state, "current_scope", "workspace")
    assert yaml_commands.match_yaml_command("/control.heartbeat", "/fixture") is None


def test_runtime_dispatch_uses_watched_pid_and_empty_payload(runtime_scope, monkeypatch):
    """Route the live YAML through streaming and command construction."""
    launch = Mock()
    monkeypatch.setattr("cli_topsailai.process.run_external_command", launch)
    _handle_stream_command("/control.heartbeat", "/fixture", [], "heartbeat-session",
                           "/fixture/heartbeat-session.2468.session.stdout")
    launch.assert_called_once()
    assert launch.call_args.args[0] == [
        "topsailai_send_control", "-s", "heartbeat-session", "-c", "heartbeat",
        "-a", "{}", "-p", "2468",
    ]


def test_runtime_unknown_shortcut_is_rejected(runtime_scope, monkeypatch, capsys):
    """Unknown shortcuts must not start an external process."""
    launch = Mock()
    monkeypatch.setattr("cli_topsailai.process.run_external_command", launch)
    _handle_stream_command("/control.nonexistent_action", "/fixture", [],
                           "heartbeat-session", None, default_pid=2468)
    launch.assert_not_called()
    assert "Could not match runtime control command" in capsys.readouterr().out


def test_heartbeat_completion(runtime_scope):
    """Offer the same heartbeat action through the existing dynamic completer."""
    assert tab_completer("/control.heart", 0) == "/control.heartbeat"
    assert tab_completer("/control.heart", 1) is None


@pytest.mark.parametrize("arguments", [
    ["control", "heartbeat"], ["-i", "/control.heartbeat"],
    ["-i", "/control heartbeat {}"],
])
def test_noninteractive_runtime_accepts_heartbeat(arguments):
    """Existing runtime syntax already normalizes heartbeat with empty payload."""
    executor = Mock(return_value=runtime_operations.RuntimeResult(
        True, 0, "control", "heartbeat-session", 2468, "control_acknowledged"))
    assert runtime_cli.run_runtime_cli(
        ["-s", "heartbeat-session", "-p", "2468", *arguments],
        executor=executor, home_resolver=lambda: "/fixture") == 0
    request = executor.call_args.args[0]
    assert request.control_action == "heartbeat"
    assert request.payload == {}


def test_noninteractive_unknown_action_rejected_before_target_lookup(monkeypatch):
    """The real dynamic allowlist still rejects unregistered actions before I/O."""
    resolve = Mock()
    monkeypatch.setattr(runtime_operations.runtime_target, "resolve_runtime_target", resolve)
    result = runtime_operations.execute_runtime_request(
        runtime_operations.RuntimeRequest("control", control_action="nonexistent_action", payload={}),
        Path("/fixture"), session_id="heartbeat-session", pid=2468)
    assert result.ok is False
    assert result.error_code == "usage_error"
    resolve.assert_not_called()
