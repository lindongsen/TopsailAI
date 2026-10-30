"""Tests for exact process-instance workspace termination.

Author: DawsonLin
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli_topsailai import core
from cli_topsailai.workspace_kill_cli import (
    KillTarget,
    WorkspaceKillError,
    _resolve_target,
    _signal_bound,
    run_workspace_kill_cli,
)


@pytest.fixture
def rows(tmp_path):
    """Return one exact ordinary session row with a concrete evidence path."""
    path = tmp_path / "workspace" / "task" / "session-123.1234.session.stdout"
    path.parent.mkdir(parents=True)
    path.write_text("log")
    return [{
        "session_id": "session-123", "pid": 1234, "session_pid": 1234,
        "filename": path.name, "path": str(path), "is_task": False,
    }]


def invoke(tmp_path, rows, sender, argv=None, *, identity_probe=None,
           relation_probe=None):
    """Run the command with isolated discovery and process-identity seams."""
    discover = Mock(return_value=rows)
    kwargs = {
        "home_resolver": lambda: str(tmp_path), "discover": discover,
        "bound_signal_sender": sender,
        "identity_probe": identity_probe or (lambda pid: (pid, 77)),
        "relation_probe": relation_probe or (lambda pid, path: True),
        "absence_probe": lambda pid: False,
    }
    code = run_workspace_kill_cli(
        argv or ["session-123", "--generation", "77"], **kwargs,
    )
    discover.assert_called_once_with(str(Path(tmp_path) / "workspace" / "task"))
    return code


def test_kill_signals_exact_verified_instance(tmp_path, rows):
    """A matching generation and evidence relation authorize one signal."""
    sender = Mock()
    assert invoke(tmp_path, rows, sender) == 0
    target, sig = sender.call_args.args
    assert target == KillTarget(1234, 77, (1234, 77))
    assert sig == 15


@pytest.mark.parametrize("session_id", ["", ".", "..", "../outside", "a/b", "a\\b", "nul\0id"])
def test_invalid_session_is_rejected_before_discovery(tmp_path, session_id):
    """Invalid identifiers cannot reach discovery or signaling."""
    discover = Mock()
    sender = Mock()
    assert run_workspace_kill_cli(
        [session_id, "-g", "77"], home_resolver=lambda: str(tmp_path),
        discover=discover, bound_signal_sender=sender,
    ) == 2
    discover.assert_not_called()
    sender.assert_not_called()


@pytest.mark.parametrize("argv", [
    ["session-123"], ["session-123", "-g", "0"],
    ["session-123", "-g", "-1"], ["session-123", "-g", "x"],
    ["session-123", "-g", "77", "-g", "78"],
])
def test_generation_is_required_and_strict(tmp_path, argv):
    """A bare PID/session selector never authorizes termination."""
    sender = Mock()
    assert run_workspace_kill_cli(argv, home_resolver=lambda: str(tmp_path),
                                  discover=Mock(), bound_signal_sender=sender) == 2
    sender.assert_not_called()


def test_stale_generation_is_rejected_without_signal(tmp_path, rows):
    """A queued request for an older process generation fails closed."""
    sender = Mock()
    assert invoke(tmp_path, rows, sender,
                  ["session-123", "-g", "76"]) == 3
    sender.assert_not_called()


def test_reused_pid_without_original_evidence_is_rejected(tmp_path, rows):
    """A live process that does not hold the historical stdout is not the owner."""
    sender = Mock()
    assert invoke(tmp_path, rows, sender, relation_probe=lambda pid, path: False) == 3
    sender.assert_not_called()


def test_unavailable_identity_evidence_is_rejected(tmp_path, rows):
    """Unreadable immutable identity evidence is uncertainty, not absence."""
    sender = Mock()
    assert invoke(tmp_path, rows, sender, identity_probe=lambda pid: None) == 3
    sender.assert_not_called()


def test_one_live_instance_among_historical_rows_is_selected(tmp_path, rows):
    """Authoritatively absent historical rows do not make one live run ambiguous."""
    old = dict(rows[0], pid=1233,
               filename="session-123.1233.session.stdout",
               path=str(tmp_path / "workspace/task/session-123.1233.session.stdout"))
    sender = Mock()
    discover = Mock(return_value=[old, rows[0]])
    code = run_workspace_kill_cli(
        ["session-123", "-g", "77"],
        home_resolver=lambda: str(tmp_path), discover=discover,
        identity_probe=lambda pid: (pid, 77) if pid == 1234 else None,
        absence_probe=lambda pid: pid == 1233,
        relation_probe=lambda pid, path: True,
        bound_signal_sender=sender,
    )
    assert code == 0
    assert sender.call_args.args[0].pid == 1234


def test_multiple_verified_live_instances_are_rejected(tmp_path, rows):
    """No newest-row heuristic selects among concurrent live executions."""
    second = dict(rows[0], pid=1235,
                  filename="session-123.1235.session.stdout",
                  path=str(tmp_path / "workspace/task/session-123.1235.session.stdout"))
    sender = Mock()
    assert invoke(tmp_path, [rows[0], second], sender) == 3
    sender.assert_not_called()


def test_signal_bound_revalidates_identity_after_pidfd_open(monkeypatch):
    """An identity change between selection and signaling sends no signal."""
    sent = Mock()
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.os.pidfd_open", lambda pid: 9)
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.os.close", Mock())
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.signal.pidfd_send_signal", sent)
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli._process_identity",
                        lambda pid: (pid, 78))
    with pytest.raises(WorkspaceKillError, match="target_changed"):
        _signal_bound(KillTarget(1234, 77, (1234, 77)), 15)
    sent.assert_not_called()


def test_signal_bound_uses_pidfd(monkeypatch):
    """The successful signal is bound to the opened immutable process handle."""
    sent = Mock()
    closed = Mock()
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.os.pidfd_open", lambda pid: 9)
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.os.close", closed)
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.signal.pidfd_send_signal", sent)
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli._process_identity",
                        lambda pid: (pid, 77))
    _signal_bound(KillTarget(1234, 77, (1234, 77)), 15)
    sent.assert_called_once_with(9, 15)
    closed.assert_called_once_with(9)


def test_core_forwards_workspace_kill_options(monkeypatch):
    """The public dispatcher preserves generation and JSON arguments."""
    called = {}

    def fake(argv):
        called["argv"] = argv
        return 7

    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.run_workspace_kill_cli", fake)
    with pytest.raises(SystemExit) as error:
        core.main(["workspace", "kill", "session-123", "-g", "77", "--json"])
    assert error.value.code == 7
    assert called["argv"] == ["session-123", "-g", "77", "--json"]


def test_public_workspace_kill_help_advertises_contract(capsys):
    """Public help exposes both generation binding and JSON output offline."""
    with pytest.raises(SystemExit) as error:
        core.main(["workspace", "kill", "--help"])
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "usage: topsailai workspace kill" in output
    assert "--generation" in output and "--json" in output


def test_json_receipt_reports_verified_generation(tmp_path, rows, capsys):
    """A successful receipt identifies the exact generation signaled."""
    sender = Mock()
    code = invoke(tmp_path, rows, sender,
                  ["session-123", "-g", "77", "--json"])
    assert code == 0
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    payload = json.loads(output)
    assert payload["pid"] == 1234
    assert payload["delivery_state"] == "signal_sent"
    assert payload["response"]["generation"] == 77
    assert payload["response"]["exit_confirmed"] is False


def test_json_target_failure_is_one_receipt(tmp_path, rows, capsys):
    """A stale remote selector remains parseable and sends no signal."""
    sender = Mock()
    assert invoke(tmp_path, rows, sender,
                  ["session-123", "-g", "76", "--json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "generation_mismatch"
    assert payload["delivery_state"] == "not_delivered"
    sender.assert_not_called()


def test_plain_mode_reports_generation(tmp_path, rows, capsys):
    """Human output identifies the process generation used for authorization."""
    assert invoke(tmp_path, rows, Mock()) == 0
    captured = capsys.readouterr()
    assert "PID=1234, generation=77" in captured.out
    assert captured.err == ""


def test_generation_value_named_json_does_not_enable_json_mode(tmp_path, capsys):
    """An invalid generation value cannot change the requested output format."""
    code = run_workspace_kill_cli(
        ["session-123", "-g", "--json"],
        home_resolver=lambda: str(tmp_path), discover=Mock(),
        bound_signal_sender=Mock(),
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "generation" in captured.err
