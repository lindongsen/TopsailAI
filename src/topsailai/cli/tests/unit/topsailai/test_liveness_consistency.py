"""Cross-command liveness consistency tests.

Every command that reports whether a session is running must agree with every
other command for the same session and the same on-disk state. These tests pin
that agreement, because the batch command and the single-session command
previously used different rules and could report opposite answers.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(CLI_ROOT, "..", "src"))
sys.path.insert(0, SRC_ROOT)
sys.path.insert(0, CLI_ROOT)

import topsailai_project_history as ph
import topsailai_session_info as si
import topsailai_sessions_info as ssi
from cli_topsailai.agent_launch_process import _process_state
from cli_topsailai.process_liveness import ProcessState, pid_state


def _spawn_zombie():
    """Fork a child that exits immediately without being reaped.

    Returns the child PID, which the caller must reap. The helper waits until
    the OS actually reports state ``Z``, because a freshly forked child is
    still running for a few milliseconds and probing it early would test the
    race instead of the zombie contract.
    """
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
    os.waitpid(pid, 0)
    return pid


def _write_stdout(task_dir: Path, session_id: str, pid: int, mtime: float) -> Path:
    """Create one session stdout file with an explicit modification time."""
    path = task_dir / f"{session_id}.{pid}.session.stdout"
    path.write_text("x")
    os.utime(path, (mtime, mtime))
    return path


class TestBatchAndSingleAgree:
    """The batch command and the single-session command must agree."""

    def test_older_live_file_is_not_hidden_by_newer_dead_file(self, tmp_path: Path):
        """A newer dead stdout file must not hide an older live process.

        This is the exact divergence that was reported: the single-session
        command inspected every candidate and answered Running, while the
        batch command inspected only the newest file and answered Idle.
        """
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        live_pid = os.getpid()
        dead_pid = _absent_pid()
        _write_stdout(task_dir, "sessA", live_pid, 1000)
        _write_stdout(task_dir, "sessA", dead_pid, 2000)

        single = si._is_session_running(str(tmp_path), "sessA")
        batch = ssi._running_status_map(str(tmp_path))

        assert single is True
        assert batch == {"sessA": True}

    def test_newer_live_file_is_reported_running_by_both(self, tmp_path: Path):
        """Both commands report Running when the newest file is the live one."""
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        live_pid = os.getpid()
        dead_pid = _absent_pid()
        _write_stdout(task_dir, "sessB", dead_pid, 1000)
        _write_stdout(task_dir, "sessB", live_pid, 2000)

        assert si._is_session_running(str(tmp_path), "sessB") is True
        assert ssi._running_status_map(str(tmp_path)) == {"sessB": True}

    def test_all_candidates_dead_is_idle_for_both(self, tmp_path: Path):
        """Both commands report Idle when every candidate is dead."""
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        _write_stdout(task_dir, "sessC", _absent_pid(), 1000)
        _write_stdout(task_dir, "sessC", _absent_pid(), 2000)

        assert si._is_session_running(str(tmp_path), "sessC") is False
        assert ssi._running_status_map(str(tmp_path)) == {"sessC": False}

    def test_zombie_candidate_is_idle_for_both(self, tmp_path: Path):
        """A zombie candidate must not keep a session looking alive anywhere."""
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        zombie_pid = _spawn_zombie()
        try:
            _write_stdout(task_dir, "sessD", zombie_pid, 1000)

            assert si._is_session_running(str(tmp_path), "sessD") is False
            assert ssi._running_status_map(str(tmp_path)) == {"sessD": False}
        finally:
            _reap(zombie_pid)

    def test_batch_keeps_one_scan_for_many_candidates(self, tmp_path: Path):
        """Collecting every candidate must not add a directory scan per file."""
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        for index in range(20):
            _write_stdout(task_dir, f"s{index}", _absent_pid(), 1000 + index)
            _write_stdout(task_dir, f"s{index}", _absent_pid(), 2000 + index)

        calls = {"count": 0}
        real_listdir = os.listdir

        def counting_listdir(path):
            calls["count"] += 1
            return real_listdir(path)

        original = ssi.os.listdir
        ssi.os.listdir = counting_listdir
        try:
            running_by_id = ssi._running_status_map(str(tmp_path))
        finally:
            ssi.os.listdir = original

        assert calls["count"] == 1
        assert len(running_by_id) == 20


class TestProjectHistoryLiveness:
    """``topsailai_project_history`` must use the shared probe."""

    def test_zombie_is_not_alive(self):
        """A zombie process must not be reported as a running session."""
        zombie_pid = _spawn_zombie()
        try:
            assert pid_state(zombie_pid) is ProcessState.DEAD
            assert ph._is_pid_alive(zombie_pid) is False
        finally:
            _reap(zombie_pid)

    def test_non_positive_pid_is_not_alive(self):
        """Non-positive PIDs must never be probed as a single process."""
        assert ph._is_pid_alive(-1) is False
        assert ph._is_pid_alive(0) is False

    def test_older_live_file_is_not_hidden_by_newer_dead_file(self, tmp_path: Path):
        """History must agree with the other commands on the same session."""
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        live_pid = os.getpid()
        dead_pid = _absent_pid()
        _write_stdout(task_dir, "sessE", live_pid, 1000)
        _write_stdout(task_dir, "sessE", dead_pid, 2000)

        assert ph._is_session_running(str(tmp_path), "sessE") is True
        assert si._is_session_running(str(tmp_path), "sessE") is True
        assert ssi._running_status_map(str(tmp_path)) == {"sessE": True}

    def test_recorded_pid_fast_path_still_works(self, tmp_path: Path):
        """The recorded-PID fast path must survive the probe replacement."""
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        live_pid = os.getpid()
        _write_stdout(task_dir, "sessF", live_pid, 1000)

        assert ph._is_session_running(str(tmp_path), "sessF", live_pid) is True

    def test_recorded_zombie_pid_does_not_authorize_running(self, tmp_path: Path):
        """A recorded PID that is a zombie must not authorize Running."""
        task_dir = tmp_path / ph.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        zombie_pid = _spawn_zombie()
        try:
            _write_stdout(task_dir, "sessG", zombie_pid, 1000)
            assert ph._is_session_running(str(tmp_path), "sessG", zombie_pid) is False
        finally:
            _reap(zombie_pid)


class TestDeadCodeRemoved:
    """The inverted-semantics helper must not remain as a trap."""

    def test_find_session_pid_is_gone(self):
        """``_find_session_pid`` implemented the opposite liveness rule."""
        assert not hasattr(si, "_find_session_pid")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
