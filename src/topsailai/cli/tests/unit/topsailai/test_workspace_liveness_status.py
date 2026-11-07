"""Pin the liveness contract of the workspace status and kill authority.

Author: DawsonLin

The workspace table is the surface an operator reads before acting on a row,
and ``workspace_pid`` is the value ``/kill`` is allowed to signal. Both must
agree with the shared liveness primitive: a zombie has already terminated, so
it must never render RUN and must never be offered as a killable PID.
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import formatting, session_driver, workspace_kill


def _spawn_zombie():
    """Fork a child that exits immediately without being reaped.

    Returns the child PID, which the caller must reap. The helper waits until
    the OS actually reports state ``Z``, because a freshly forked child is
    still running for a few milliseconds and probing it early would test the
    race instead of the zombie contract.
    """
    from cli_topsailai.agent_launch_process import _process_state

    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        os._exit(0)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _process_state(pid) == "Z":
            return pid
        time.sleep(0.01)
    raise AssertionError(f"child {pid} never reached zombie state")


def _reap(pid):
    """Reap a child PID, ignoring an already-reaped or non-child PID."""
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass


def _absent_pid():
    """Return a PID that the OS authoritatively reports as absent."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        os._exit(0)
    _reap(pid)
    return pid


@pytest.fixture
def isolated(monkeypatch):
    """Isolate driver observation and pipe probing from the real host."""
    monkeypatch.setattr(formatting, "is_session_pipe_open", Mock(return_value=False))
    monkeypatch.setattr(session_driver, "observe_driver", Mock(return_value=None))


def _row(pid, session_id="s1"):
    """Build a minimal session stdout row for the given PID."""
    return {
        "filename": f"{session_id}.{pid}.session.stdout",
        "session_id": session_id,
        "pid": pid,
        "session_pid": pid,
        "is_task": False,
        "ctime": 1700000000.0,
    }


def test_zombie_row_is_not_running(isolated, tmp_path):
    """A zombie has terminated, so its row must not render RUN."""
    pid = _spawn_zombie()
    try:
        row = _row(pid)
        formatting.enrich_workspace_rows([row], str(tmp_path))
        assert row["workspace_status"] == "idle"
    finally:
        _reap(pid)


def test_zombie_row_exposes_no_kill_authority(isolated, tmp_path):
    """A zombie PID must never be offered to ``/kill`` as a signal target."""
    pid = _spawn_zombie()
    try:
        row = _row(pid)
        formatting.enrich_workspace_rows([row], str(tmp_path))
        assert row["workspace_pid"] is None
        assert workspace_kill.kill_workspace_row(
            [row], 0, read_input=Mock(return_value="y")
        ) is False
    finally:
        _reap(pid)


def test_live_row_is_running_and_killable(isolated, tmp_path):
    """A live process must render RUN and keep its kill authority."""
    row = _row(os.getpid())
    formatting.enrich_workspace_rows([row], str(tmp_path))
    assert row["workspace_status"] == "running"
    assert row["workspace_pid"] == os.getpid()


def test_absent_row_is_idle(isolated, tmp_path):
    """A reaped PID must render idle."""
    row = _row(_absent_pid())
    formatting.enrich_workspace_rows([row], str(tmp_path))
    assert row["workspace_status"] == "idle"
    assert row["workspace_pid"] is None


@pytest.mark.parametrize("pid", [-1, 0])
def test_non_positive_pid_row_is_idle(isolated, tmp_path, pid):
    """A non-positive PID addresses a group, not one process, so it is idle."""
    row = _row(pid)
    formatting.enrich_workspace_rows([row], str(tmp_path))
    assert row["workspace_status"] == "idle"
    assert row["workspace_pid"] is None


def test_unverifiable_pid_is_not_reported_running(isolated, tmp_path, monkeypatch):
    """When the OS refuses to answer, the display must not claim RUN."""
    from cli_topsailai.process_liveness import ProcessState

    monkeypatch.setattr(formatting, "pid_state", Mock(return_value=ProcessState.UNKNOWN))
    row = _row(4242)
    formatting.enrich_workspace_rows([row], str(tmp_path))
    assert row["workspace_status"] == "idle"
    assert row["workspace_pid"] is None
