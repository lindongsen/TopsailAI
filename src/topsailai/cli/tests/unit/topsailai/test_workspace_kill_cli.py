"""Tests for non-interactive workspace session termination.

Author: DawsonLin
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from cli_topsailai import core
from cli_topsailai.workspace_kill_cli import run_workspace_kill_cli


@pytest.fixture
def rows():
    """Return one exact ordinary session row."""
    return [{
        "session_id": "session-123",
        "pid": 1234,
        "session_pid": 1234,
        "filename": "session-123.1234.session.stdout",
        "is_task": False,
    }]


def invoke(tmp_path, rows, signal_sender):
    """Run the command with isolated discovery and signal seams."""
    discover = Mock(return_value=rows)
    code = run_workspace_kill_cli(
        ["session-123"],
        home_resolver=lambda: str(tmp_path),
        discover=discover,
        signal_sender=signal_sender,
        process_probe=lambda pid, sig: None,
    )
    discover.assert_called_once_with(str(Path(tmp_path) / "workspace" / "task"))
    return code


def test_kill_sends_sigterm_without_confirmation(tmp_path, rows):
    """A valid session is terminated directly without reading input."""
    signal_sender = Mock()
    assert invoke(tmp_path, rows, signal_sender) == 0
    signal_sender.assert_called_once_with(1234, 15)


@pytest.mark.parametrize("session_id", ["", ".", "..", "../outside", "a/b", "a\\b", "nul\0id"])
def test_invalid_session_is_rejected_before_discovery(tmp_path, session_id):
    """Invalid identifiers cannot reach discovery or signaling."""
    discover = Mock()
    signal_sender = Mock()
    assert run_workspace_kill_cli(
        [session_id], home_resolver=lambda: str(tmp_path),
        discover=discover, signal_sender=signal_sender,
    ) == 2
    discover.assert_not_called()
    signal_sender.assert_not_called()


@pytest.mark.parametrize("bad_rows", [
    [],
    [{"session_id": "session-123", "pid": 1234, "filename": "session-123.1234.task.stdout", "is_task": True}],
    [
        {"session_id": "session-123", "pid": 1234, "filename": "session-123.1234.session.stdout", "is_task": False},
        {"session_id": "session-123", "pid": 1235, "filename": "session-123.1235.session.stdout", "is_task": False},
    ],
])
def test_non_unique_or_task_target_is_rejected(tmp_path, bad_rows):
    """Missing, task-only and ambiguous rows never authorize signaling."""
    signal_sender = Mock()
    assert invoke(tmp_path, bad_rows, signal_sender) == 3
    signal_sender.assert_not_called()


@pytest.mark.parametrize("pid", [1, 9999])
def test_protected_or_dead_target_is_rejected(tmp_path, rows, monkeypatch, pid):
    """Protected and non-existent process targets are rejected before SIGTERM."""
    rows[0]["pid"] = pid
    rows[0]["filename"] = f"session-123.{pid}.session.stdout"
    signal_sender = Mock()
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.os.getpid", lambda: 9999)
    if pid == 1:
        assert invoke(tmp_path, rows, signal_sender) == 3
    else:
        assert invoke(tmp_path, rows, signal_sender) == 3
    signal_sender.assert_not_called()


def test_signal_failure_is_reported(tmp_path, rows, monkeypatch):
    """A signal delivery failure returns an error without claiming success."""
    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.os.kill", lambda pid, sig: None)
    sender = Mock(side_effect=PermissionError("denied"))
    assert invoke(tmp_path, rows, sender) == 4
    sender.assert_called_once_with(1234, 15)


def test_core_dispatches_workspace_kill(tmp_path, monkeypatch):
    """The top-level workspace parser routes kill to the non-interactive handler."""
    called = {}

    def fake(argv):
        called["argv"] = argv
        return 7

    monkeypatch.setattr("cli_topsailai.workspace_kill_cli.run_workspace_kill_cli", fake)
    with pytest.raises(SystemExit) as error:
        core.main(["workspace", "kill", "session-123"])
    assert error.value.code == 7
    assert called["argv"] == ["session-123"]


def test_json_receipt_reports_signal_submission(tmp_path, rows, capsys):
    """A successful kill emits one receipt that does not claim process exit."""
    import json

    signal_sender = Mock()
    code = run_workspace_kill_cli(
        ["session-123", "--json"],
        home_resolver=lambda: str(tmp_path),
        discover=Mock(return_value=rows),
        signal_sender=signal_sender,
        process_probe=lambda pid, sig: None,
    )
    assert code == 0
    signal_sender.assert_called_once_with(1234, 15)
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["action"] == "kill"
    assert payload["session_id"] == "session-123"
    assert payload["pid"] == 1234
    assert payload["delivery_state"] == "signal_sent"
    assert payload["response"]["exit_confirmed"] is False
    assert payload["delivery_unknown"] is False


@pytest.mark.parametrize("argv, expected_code, expected_error", [
    (["session-123", "--json", "extra"], 2, "usage_error"),
    (["../outside", "--json"], 2, "usage_error"),
])
def test_json_receipt_covers_usage_failures(tmp_path, argv, expected_code, expected_error, capsys):
    """Usage failures still produce exactly one parseable receipt."""
    import json

    signal_sender = Mock()
    code = run_workspace_kill_cli(
        argv, home_resolver=lambda: str(tmp_path),
        discover=Mock(return_value=[]), signal_sender=signal_sender,
    )
    assert code == expected_code
    signal_sender.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["exit_code"] == expected_code
    assert payload["error_code"] == expected_error
    assert payload["delivery_state"] == "not_delivered"


def test_json_receipt_covers_target_and_signal_failures(tmp_path, rows, capsys):
    """Target and signal failures keep their documented exit codes."""
    import json

    code = run_workspace_kill_cli(
        ["session-123", "--json"], home_resolver=lambda: str(tmp_path),
        discover=Mock(return_value=[]), signal_sender=Mock(),
    )
    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "target_not_unique"
    assert payload["delivery_state"] == "not_delivered"

    sender = Mock(side_effect=PermissionError("denied"))
    code = run_workspace_kill_cli(
        ["session-123", "--json"], home_resolver=lambda: str(tmp_path),
        discover=Mock(return_value=rows), signal_sender=sender,
        process_probe=lambda pid, sig: None,
    )
    assert code == 4
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "signal_failed"
    assert payload["pid"] == 1234


def test_plain_mode_output_is_unchanged(tmp_path, rows, capsys):
    """Without --json the historical plain output is preserved exactly."""
    signal_sender = Mock()
    assert run_workspace_kill_cli(
        ["session-123"], home_resolver=lambda: str(tmp_path),
        discover=Mock(return_value=rows), signal_sender=signal_sender,
        process_probe=lambda pid, sig: None,
    ) == 0
    captured = capsys.readouterr()
    assert captured.out == (
        "[INFO] SIGTERM sent to session=session-123, PID=1234; "
        "process exit is not confirmed.\n"
    )
    assert captured.err == ""


def test_json_flag_value_is_not_mistaken_for_the_option(tmp_path, rows, capsys):
    """A session literally named ``--json`` cannot enable JSON mode."""
    assert run_workspace_kill_cli(
        ["--", "--json"], home_resolver=lambda: str(tmp_path),
        discover=Mock(return_value=[]), signal_sender=Mock(),
    ) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[ERROR]" in captured.err
