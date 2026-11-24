"""Tests for the graceful agent exit gate and its delivery boundary.

Author: DawsonLin
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli_topsailai import core
from cli_topsailai.workspace_kill_cli import (
    KillTarget,
    run_workspace_kill_cli,
)
from cli_topsailai.workspace_kill_graceful import (
    AGENT_WAITING,
    GRACEFUL_EXIT_MESSAGE,
    SESSION_IDLE,
    GracefulRefusal,
    deliver_graceful_exit,
    observe_graceful_states,
)

FILENAME = "session-123.1234.session.stdout"
GRACEFUL_MODULE = (
    Path(__file__).resolve().parents[3]
    / "cli_topsailai" / "workspace_kill_graceful.py"
)


@pytest.fixture
def row(tmp_path):
    """Return one exact ordinary session row with a concrete evidence path."""
    path = tmp_path / "workspace" / "task" / FILENAME
    path.parent.mkdir(parents=True)
    path.write_text("log")
    return {
        "session_id": "session-123", "pid": 1234, "session_pid": 1234,
        "filename": FILENAME, "path": str(path), "is_task": False,
    }


def _enrich_with(status):
    """Build an agent-state seam that writes one fixed workspace status."""
    def enrich(rows, home):
        for item in rows:
            item["workspace_status"] = status
    return enrich


def _collect_with(record):
    """Build a lock-state seam that answers one fixed record per filename."""
    def collect(rows):
        return {item["filename"]: dict(record) for item in rows}
    return collect


def _ok_result():
    """Build a delivery result that reports a written payload."""
    return Mock(ok=True, error_code=None, bytes_written=6)


def invoke(tmp_path, row, argv, *, enrich=None, collect=None, deliverer=None,
           sender=None):
    """Run the command with isolated discovery, identity and action seams.

    The two state seams replace only the collectors. The gate itself always runs,
    so no test can reach a successful delivery while skipping a precondition.
    """
    discover = Mock(return_value=[row])
    sender = sender or Mock()
    kwargs = {
        "home_resolver": lambda: str(tmp_path), "discover": discover,
        "bound_signal_sender": sender,
        "identity_probe": lambda pid: (pid, 77),
        "relation_probe": lambda pid, path: True,
        "absence_probe": lambda pid: False,
        "graceful_enrich": enrich or _enrich_with(AGENT_WAITING),
        "graceful_collect": collect or _collect_with(
            {"status": SESSION_IDLE, "error_code": None, "message": None}),
    }
    if deliverer is not None:
        kwargs["graceful_deliverer"] = deliverer
    code = run_workspace_kill_cli(argv, **kwargs)
    return code, sender


def test_both_preconditions_hold_and_exit_is_delivered(tmp_path, row):
    """An idle lock plus a waiting agent authorizes exactly one /exit delivery."""
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77", "--graceful"],
        deliverer=deliverer,
    )
    assert code == 0
    # The graceful path must never signal, because the caller asked for a
    # cooperative exit rather than a termination.
    sender.assert_not_called()
    deliverer.assert_called_once()
    task_dir, session_id, pid = deliverer.call_args.args
    assert task_dir == str(Path(tmp_path) / "workspace" / "task")
    assert session_id == "session-123"
    assert pid == 1234


def test_graceful_receipt_reports_delivery_not_exit(tmp_path, row, capsys):
    """A written message is reported as delivery, never as confirmed exit."""
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77", "--graceful", "--json"],
        deliverer=deliverer,
    )
    assert code == 0
    sender.assert_not_called()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ok"] is True
    assert receipt["delivery_state"] == "pipe_written"
    assert receipt["response"]["graceful"] is True
    assert receipt["response"]["message"] == GRACEFUL_EXIT_MESSAGE
    assert receipt["response"]["exit_confirmed"] is False
    assert receipt["response"]["session_status"] == SESSION_IDLE
    assert receipt["response"]["agent_status"] == AGENT_WAITING


def test_busy_session_lock_refuses_without_delivery(tmp_path, row, capsys):
    """A processing lock refuses, because a task currently holds the session."""
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77", "--graceful", "--json"],
        collect=_collect_with({"status": "processing", "error_code": None,
                               "message": None}),
        deliverer=deliverer,
    )
    assert code == 3
    sender.assert_not_called()
    deliverer.assert_not_called()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ok"] is False
    assert receipt["error_code"] == "graceful_session_busy"


def test_agent_not_waiting_refuses_without_delivery(tmp_path, row, capsys):
    """A running agent refuses, because a delivered line would not be consumed."""
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77", "--graceful", "--json"],
        enrich=_enrich_with("running"), deliverer=deliverer,
    )
    assert code == 3
    sender.assert_not_called()
    deliverer.assert_not_called()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["error_code"] == "graceful_agent_not_waiting"


def test_unobservable_state_refuses_without_delivery(tmp_path, row, capsys):
    """An unknown state refuses, because unknown is not the same as satisfied."""
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77", "--graceful", "--json"],
        collect=_collect_with({"status": None, "error_code": "timeout",
                               "message": "no answer"}),
        deliverer=deliverer,
    )
    assert code == 3
    sender.assert_not_called()
    deliverer.assert_not_called()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["error_code"] == "graceful_status_unavailable"


def test_delivery_failure_is_reported_as_failure(tmp_path, row, capsys):
    """A failed write is exit 4 and never a success receipt."""
    deliverer = Mock(return_value=Mock(ok=False, error_code="endpoint_missing"))
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77", "--graceful", "--json"],
        deliverer=deliverer,
    )
    assert code == 4
    sender.assert_not_called()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ok"] is False
    assert receipt["error_code"] == "graceful_delivery_failed"
    assert "endpoint_missing" in receipt["message"]


def test_delivery_exception_is_reported_as_failure(tmp_path, row, capsys):
    """A raising deliverer is classified instead of escaping the command."""
    deliverer = Mock(side_effect=OSError("pipe vanished"))
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77", "--graceful", "--json"],
        deliverer=deliverer,
    )
    assert code == 4
    sender.assert_not_called()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["error_code"] == "graceful_delivery_failed"


def test_default_action_still_signals(tmp_path, row):
    """Without the flag the command keeps its SIGTERM contract."""
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "77"], deliverer=deliverer,
    )
    assert code == 0
    sender.assert_called_once()
    deliverer.assert_not_called()


def test_generation_is_still_required_with_graceful(tmp_path, row):
    """The graceful flag never relaxes the identity requirement."""
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "--graceful"], deliverer=deliverer,
    )
    assert code == 2
    sender.assert_not_called()
    deliverer.assert_not_called()


def test_generation_mismatch_refuses_before_observation(tmp_path, row):
    """A stale generation is rejected before any state is observed."""
    enrich = Mock()
    collect = Mock()
    deliverer = Mock(return_value=_ok_result())
    code, sender = invoke(
        tmp_path, row, ["session-123", "-g", "78", "--graceful"],
        enrich=enrich, collect=collect, deliverer=deliverer,
    )
    assert code == 3
    enrich.assert_not_called()
    collect.assert_not_called()
    deliverer.assert_not_called()
    sender.assert_not_called()


def test_observe_requires_both_states_to_hold(row, tmp_path):
    """The gate returns both states only when each one is satisfied."""
    states = observe_graceful_states(
        row, str(tmp_path),
        enrich=_enrich_with(AGENT_WAITING),
        collect=_collect_with({"status": SESSION_IDLE, "error_code": None,
                               "message": None}),
    )
    assert states == {"session_status": SESSION_IDLE,
                      "agent_status": AGENT_WAITING}


@pytest.mark.parametrize("agent_status", ["running", "idle", None, ""])
def test_observe_refuses_any_non_waiting_agent_state(row, tmp_path, agent_status):
    """Only the waiting state authorizes delivery, including unknown values."""
    with pytest.raises(GracefulRefusal) as raised:
        observe_graceful_states(
            row, str(tmp_path),
            enrich=_enrich_with(agent_status),
            collect=_collect_with({"status": SESSION_IDLE, "error_code": None,
                                   "message": None}),
        )
    expected = (
        "graceful_status_unavailable" if not agent_status
        else "graceful_agent_not_waiting"
    )
    assert raised.value.error_code == expected


@pytest.mark.parametrize("record", [
    {"status": "processing", "error_code": None, "message": None},
    {"status": None, "error_code": "timeout", "message": "no answer"},
    {"status": None, "error_code": None, "message": None},
])
def test_observe_refuses_any_non_idle_lock_state(row, tmp_path, record):
    """Only an idle lock authorizes delivery, including unknown values."""
    with pytest.raises(GracefulRefusal) as raised:
        observe_graceful_states(
            row, str(tmp_path),
            enrich=_enrich_with(AGENT_WAITING),
            collect=_collect_with(record),
        )
    expected = (
        "graceful_session_busy" if record["status"] == "processing"
        else "graceful_status_unavailable"
    )
    assert raised.value.error_code == expected


def test_observe_refuses_a_missing_lock_record(row, tmp_path):
    """A row absent from the collector answer is unknown, not idle."""
    with pytest.raises(GracefulRefusal) as raised:
        observe_graceful_states(
            row, str(tmp_path),
            enrich=_enrich_with(AGENT_WAITING),
            collect=lambda rows: {},
        )
    assert raised.value.error_code == "graceful_status_unavailable"


def test_observe_queries_only_the_target_row(row, tmp_path):
    """One row in means one child process, never one per discovered row."""
    collect = Mock(return_value={FILENAME: {"status": SESSION_IDLE,
                                            "error_code": None, "message": None}})
    enrich = Mock(side_effect=_enrich_with(AGENT_WAITING))
    observe_graceful_states(row, str(tmp_path), enrich=enrich, collect=collect)
    assert enrich.call_args.args[0] == [row]
    assert collect.call_args.args[0] == [row]


def test_deliver_uses_the_existing_send_action(tmp_path):
    """Delivery reuses the FIFO transport with the existing exit spelling."""
    execute = Mock(return_value=_ok_result())
    deliver_graceful_exit(
        str(tmp_path), "session-123", 1234, execute=execute,
    )
    request = execute.call_args.args[0]
    assert request.action == "send"
    assert request.message == GRACEFUL_EXIT_MESSAGE
    assert execute.call_args.kwargs == {"session_id": "session-123", "pid": 1234}


def test_deliver_hands_the_transport_an_absolute_path(tmp_path):
    """The transport requires an absolute ``Path`` and rejects a plain string.

    ``runtime_target._absolute_path`` raises ``usage_error`` for anything that is
    not an absolute ``Path`` instance, so passing the caller's string made every
    real delivery fail while the seam-based tests still passed. This pins the
    contract the real executor actually enforces.
    """
    execute = Mock(return_value=_ok_result())
    deliver_graceful_exit(str(tmp_path), "session-123", 1234, execute=execute)
    task_dir = execute.call_args.args[1]
    assert isinstance(task_dir, Path)
    assert task_dir.is_absolute()


def test_deliver_normalizes_a_relative_directory(tmp_path, monkeypatch):
    """A relative directory is made absolute instead of being rejected."""
    execute = Mock(return_value=_ok_result())
    monkeypatch.chdir(tmp_path)
    deliver_graceful_exit(".", "session-123", 1234, execute=execute)
    task_dir = execute.call_args.args[1]
    assert isinstance(task_dir, Path)
    assert task_dir.is_absolute()


def test_graceful_module_does_not_probe_the_lock_itself():
    """The gate must not reimplement lock detection it is required to reuse."""
    source = GRACEFUL_MODULE.read_text()
    for forbidden in ("fcntl", "flock", "lockf", "ctxm_try_session_lock"):
        assert forbidden not in source


def test_graceful_module_is_importable_without_a_shebang():
    """A compiled build ships this module as an importable extension."""
    first_line = GRACEFUL_MODULE.read_text().splitlines()[0]
    assert not first_line.startswith("#!")


def test_core_dispatches_graceful_flag(tmp_path, row, monkeypatch):
    """The real dispatch path forwards the flag to the kill command."""
    captured = {}

    def fake_run(argv):
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr(
        "cli_topsailai.workspace_kill_cli.run_workspace_kill_cli", fake_run,
    )
    with pytest.raises(SystemExit) as raised:
        core.main([
            "workspace", "kill", "session-123", "-g", "77", "--graceful",
        ])
    assert raised.value.code == 0
    assert captured["argv"] == ["session-123", "-g", "77", "--graceful"]
