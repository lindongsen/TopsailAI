"""Pin the liveness contract of the runtime viewer's session-exit check.

Author: DawsonLin

``_is_session_alive`` decides whether the runtime viewer keeps waiting for a
session. It previously returned True when neither a stdout file nor a PID was
known, which is a fail-open answer: an unverifiable session was treated as
running forever. It must agree with the shared liveness primitive instead.
"""

import os
import time

import pytest

from cli_topsailai import streaming


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


def test_live_pid_is_alive():
    """The current process must keep the viewer waiting."""
    assert streaming._is_session_alive(None, os.getpid()) is True


def test_absent_pid_is_not_alive():
    """A reaped PID must end the viewer."""
    assert streaming._is_session_alive(None, _absent_pid()) is False


def test_zombie_pid_is_not_alive():
    """A zombie has terminated and must end the viewer."""
    pid = _spawn_zombie()
    try:
        assert streaming._is_session_alive(None, pid) is False
    finally:
        _reap(pid)


@pytest.mark.parametrize("pid", [-1, 0])
def test_non_positive_pid_is_not_alive(pid):
    """A non-positive PID addresses a group, not one process, so it is dead."""
    assert streaming._is_session_alive(None, pid) is False


def test_missing_stdout_file_is_not_alive(tmp_path):
    """A vanished stdout file must end the viewer."""
    assert streaming._is_session_alive(str(tmp_path / "gone.stdout"), None) is False


def test_existing_stdout_file_without_pid_is_alive(tmp_path):
    """An existing file with no PID is the only remaining positive evidence."""
    path = tmp_path / "s1.123.session.stdout"
    path.write_text("log\n", encoding="utf-8")
    assert streaming._is_session_alive(str(path), None) is True


def test_no_identifier_is_not_alive():
    """With no evidence at all the viewer must not claim the session is alive."""
    assert streaming._is_session_alive(None, None) is False


def test_unverifiable_pid_is_not_alive(monkeypatch):
    """When the OS refuses to answer, the viewer must not claim it is alive."""
    from cli_topsailai import process_liveness

    monkeypatch.setattr(
        process_liveness, "pid_state", lambda pid: process_liveness.ProcessState.UNKNOWN
    )
    assert streaming._is_session_alive(None, 4242) is False
