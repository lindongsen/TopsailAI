"""Regression contracts for sessions with several child task records.

Author: DawsonLin
"""
from pathlib import Path
from unittest.mock import Mock

import pytest

import driver_targets as targets
import session_agent_driver as sad
from ai_base.agent_types.exception import AgentEndProcess
from plugins.tools import exit_process, inject_input


def row(folder, pid, *, task=True, suffix="job"):
    """Build detached discovered-file evidence."""
    filename = f"s1.{pid}.{suffix}.task.stdout" if task else f"s1.{pid}.session.stdout"
    return dict(session_id="s1", pid=pid, session_pid=10, is_task=task,
                path=str(folder / filename), filename=filename, ctime=pid)


def test_multiple_children_and_dead_parent(monkeypatch, tmp_path):
    """A live waiting child triggers analysis even when its parent is dead."""
    records = [row(tmp_path, 10, task=False), row(tmp_path, 20), row(tmp_path, 30)]
    monkeypatch.setattr(sad, "discover_log_files", lambda _: records)
    monkeypatch.setattr(sad, "_is_pid_alive", lambda pid: pid in (20, 30))
    monkeypatch.setattr(sad, "is_session_pipe_open", lambda r: r["pid"] == 20)
    assert sad.check_session_status("s1") == "input"
    assert sad._current_record("s1")["pid"] == 20
    monkeypatch.setattr(sad, "is_session_pipe_open", lambda r: False)
    assert sad.check_session_status("s1") == "running"
    monkeypatch.setattr(sad, "_is_pid_alive", lambda pid: False)
    assert sad.check_session_status("s1") == "idle"
    assert sad._current_record("s1") is None


def test_own_pipe_only_and_duplicate_logs(tmp_path):
    """Parent INPUT must not manufacture a child's input ownership."""
    records = [row(tmp_path, 20), row(tmp_path, 20, suffix="second")]
    probe = Mock(side_effect=lambda r: r["session_pid"] == 10)
    rows, status = targets.observe_records(records, lambda pid: True, probe)
    assert status == "running"
    assert len(rows) == 2
    assert records[0].get("status") is None
    assert all(call.args[0]["session_pid"] == 20 for call in probe.call_args_list)


def test_discovery_error_is_not_idle(monkeypatch):
    """Unavailable authority propagates rather than declaring termination."""
    monkeypatch.setattr(sad, "discover_log_files", Mock(side_effect=OSError("denied")))
    with pytest.raises(OSError):
        sad.check_session_status("s1")


def test_task_context(monkeypatch, tmp_path):
    """Analysis context includes all process rows and child logs."""
    records = [dict(row(tmp_path, 20), status="input"), dict(row(tmp_path, 30), status="running")]
    for record in records:
        Path(record["path"]).write_text("child progress\n")
    monkeypatch.setattr(sad, "_task_dir", lambda: tmp_path)
    monkeypatch.setattr(sad, "_session_snapshot", lambda _: (records, "input"))
    manager = Mock()
    manager.retrieve_messages.return_value = []
    monkeypatch.setattr(sad.ctx_manager, "get_session_manager", lambda: manager)
    info = sad.get_session_info("s1")
    assert "pid=20" in info["processes_summary"]
    assert "pid=30" in info["processes_summary"]
    assert "child progress" in info["log_tail"]
    assert "child progress" in sad.render_analysis_prompt(info)


@pytest.mark.parametrize("pid", [None, 0, -1, True, "20"])
def test_invalid_task_selector(tmp_path, pid):
    """Invalid selectors cannot produce sends."""
    with pytest.raises(ValueError):
        targets.send_task_input(tmp_path, "s1", pid, "yes", timeout=1)


def prepare_child(monkeypatch, tmp_path):
    """Provide real regular log evidence and isolated runtime probes."""
    record = row(tmp_path, 20)
    Path(record["path"]).write_text("waiting\n")
    monkeypatch.setattr(targets, "discover_log_files", lambda _: [record])
    monkeypatch.setattr(targets, "probe_process", lambda _: targets.ProcessState.ALIVE)
    monkeypatch.setattr(targets, "own_pipe_open", lambda _: True)
    sender = Mock()
    monkeypatch.setattr(targets, "send_to_pipe", sender)
    return record, sender


def test_exact_child_send(monkeypatch, tmp_path):
    """Explicit child PID uses its own pipe, not parent resolution."""
    record, sender = prepare_child(monkeypatch, tmp_path)
    monkeypatch.setattr(inject_input, "_task_dir", lambda: tmp_path)
    core = Mock()
    monkeypatch.setattr(inject_input, "execute_runtime_request", core)
    assert "pid 20" in inject_input.inject_input("s1", "continue", 20)
    sender.assert_called_once_with(tmp_path / "s1.20.session.pipe", "continue", timeout=5.0)
    core.assert_not_called()


@pytest.mark.parametrize("live,waiting", [(False, True), (True, False)])
def test_child_changed_state_aborts(monkeypatch, tmp_path, live, waiting):
    """Dead or no-longer-waiting children must not receive input."""
    _, sender = prepare_child(monkeypatch, tmp_path)
    monkeypatch.setattr(targets, "probe_process", lambda _: targets.ProcessState.ALIVE if live else targets.ProcessState.DEAD)
    monkeypatch.setattr(targets, "own_pipe_open", lambda _: waiting)
    monkeypatch.setattr(inject_input, "_task_dir", lambda: tmp_path)
    with pytest.raises(AgentEndProcess):
        inject_input.inject_input("s1", "continue", 20)
    sender.assert_not_called()


def test_no_task_and_session_evidence_use_core(monkeypatch, tmp_path):
    """Session records retain core resolution and no matching tasks fall back."""
    monkeypatch.setattr(targets, "discover_log_files", lambda _: [])
    assert not targets.send_task_input(tmp_path, "s1", 20, "yes", timeout=1)
    monkeypatch.setattr(targets, "discover_log_files", lambda _: [row(tmp_path, 20, task=False)])
    assert not targets.send_task_input(tmp_path, "s1", 20, "yes", timeout=1)


def test_task_log_rejects_symlink_and_outside(tmp_path):
    """Child evidence cannot redirect reads outside task storage."""
    record = row(tmp_path, 20)
    with pytest.raises(ValueError):
        targets.task_log_target(tmp_path / "other", record)
    Path(record["path"]).symlink_to(tmp_path)
    with pytest.raises(ValueError):
        targets.task_log_target(tmp_path, record)


def test_exit_guard(monkeypatch):
    """A child completion cannot stop monitoring other live tasks."""
    exit_process.reset_exit_flag()
    monkeypatch.setattr(exit_process, "_EXIT_GUARD", lambda: False)
    with pytest.raises(AgentEndProcess):
        exit_process.exit_process("s1")
    assert not exit_process.is_exit_requested()
    exit_process.set_exit_guard(lambda: True)
    assert exit_process.exit_process("s1") == "exit requested"
    exit_process.reset_exit_flag()


def test_own_pipe_adapter(monkeypatch, tmp_path):
    """The direct adapter removes parent fallback."""
    probe = Mock(return_value=True)
    monkeypatch.setattr(targets, "is_session_pipe_open", probe)
    assert targets.own_pipe_open(row(tmp_path, 20))
    assert probe.call_args.args[0]["session_pid"] == 20


def test_changed_log_identity_rejected(monkeypatch, tmp_path):
    """Replacement between probes cannot authorize child delivery."""
    record, sender = prepare_child(monkeypatch, tmp_path)

    def replace_log(_):
        """Replace evidence while preserving an explicit original backup."""
        path = Path(record["path"])
        path.rename(tmp_path / "old-log")
        path.write_text("replacement\n")
        return True

    monkeypatch.setattr(targets, "own_pipe_open", replace_log)
    with pytest.raises(ValueError, match="evidence changed"):
        targets.send_task_input(tmp_path, "s1", 20, "yes", timeout=1)
    sender.assert_not_called()


def test_log_budget_preserves_all_statuses(monkeypatch, tmp_path):
    """Large early logs do not hide later waiting tasks."""
    records = [dict(row(tmp_path, pid), status="input") for pid in range(20, 40)]
    for record in records:
        Path(record["path"]).write_text("x" * 10000)
    monkeypatch.setattr(sad, "_session_snapshot", lambda _: (records, "input"))
    monkeypatch.setattr(sad, "_task_dir", lambda: tmp_path)
    manager = Mock()
    manager.retrieve_messages.return_value = []
    monkeypatch.setattr(sad.ctx_manager, "get_session_manager", lambda: manager)
    info = sad.get_session_info("s1")
    assert "pid=39 is_task=True status=input" in info["processes_summary"]
    assert "truncated" in info["processes_summary"]
    assert len(info["log_tail"]) <= sad.MESSAGES_SUMMARY_MAX_CHARS


def test_real_child_fifo_delivery(monkeypatch, tmp_path):
    """Exercise child evidence, liveness, own-pipe detection and actual FIFO I/O."""
    import os

    if os.name != "posix":
        pytest.skip("FIFO transport requires POSIX")
    pid = os.getpid()
    record = row(tmp_path, pid)
    Path(record["path"]).write_text("waiting\n")
    pipe = tmp_path / f"s1.{pid}.session.pipe"
    os.mkfifo(pipe)
    reader = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
    received = []
    try:
        monkeypatch.setattr(targets, "discover_log_files", lambda _: [record])
        # The pipe is held by this exact PID; no core target resolver is mocked.
        assert targets.send_task_input(tmp_path, "s1", pid, "continue", timeout=1)
        received.append(os.read(reader, 4096))
        assert received == [b"continue\nEOF\n"]
    finally:
        os.close(reader)
