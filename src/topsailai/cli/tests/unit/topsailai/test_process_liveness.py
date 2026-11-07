#!/usr/bin/env python3
"""
Unit tests for the shared process-liveness primitive.

Author: DawsonLin

These tests pin the three-state contract that every status path must share:
``ALIVE``, ``DEAD`` and ``UNKNOWN``. They exist because the CLI previously
carried several mutually inconsistent probes, so a zombie, a reused PID or a
non-positive PID could each be reported as a running session.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import process_liveness
from cli_topsailai.agent_launch_process import _process_state
from cli_topsailai.process_liveness import (
    ProcessState,
    is_pid_alive,
    pid_state,
    session_liveness,
)


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
    _reap(pid)
    return pid


class TestPidState(unittest.TestCase):
    """Pin the classification of a single PID."""

    def test_current_process_is_alive(self):
        """The running test process must classify as ALIVE."""
        self.assertIs(pid_state(os.getpid()), ProcessState.ALIVE)

    def test_absent_process_is_dead(self):
        """A reaped PID must classify as DEAD, not UNKNOWN."""
        self.assertIs(pid_state(_absent_pid()), ProcessState.DEAD)

    def test_zombie_is_dead(self):
        """An unreaped zombie has exited, so it must classify as DEAD."""
        pid = _spawn_zombie()
        try:
            self.assertIs(pid_state(pid), ProcessState.DEAD)
        finally:
            _reap(pid)

    def test_zombie_is_not_alive(self):
        """``is_pid_alive`` must not report a zombie as alive."""
        pid = _spawn_zombie()
        try:
            self.assertFalse(is_pid_alive(pid))
        finally:
            _reap(pid)

    def test_negative_pid_is_unknown(self):
        """A negative PID must never reach ``os.kill``."""
        self.assertIs(pid_state(-1), ProcessState.UNKNOWN)

    def test_zero_pid_is_unknown(self):
        """PID 0 addresses the process group, so it must be rejected."""
        self.assertIs(pid_state(0), ProcessState.UNKNOWN)

    def test_non_integer_pid_is_unknown(self):
        """A non-integer PID must be rejected instead of coerced."""
        self.assertIs(pid_state("123"), ProcessState.UNKNOWN)
        self.assertIs(pid_state(None), ProcessState.UNKNOWN)

    def test_boolean_pid_is_unknown(self):
        """``True`` is an ``int`` subclass but is not a PID."""
        self.assertIs(pid_state(True), ProcessState.UNKNOWN)

    def test_non_positive_pid_never_calls_kill(self):
        """No probe may signal PID 0 or a negative PID."""
        with patch.object(process_liveness.os, "kill") as kill:
            pid_state(-1)
            pid_state(0)
        kill.assert_not_called()

    def test_unreadable_proc_entry_is_unknown(self):
        """An unreadable process table entry must fail closed."""
        with patch.object(process_liveness, "_process_absent", return_value=False), \
                patch.object(process_liveness, "_process_state", return_value=None):
            self.assertIs(pid_state(os.getpid()), ProcessState.UNKNOWN)

    def test_race_to_exit_reports_dead(self):
        """A process that exits mid-probe must be re-checked, not left UNKNOWN."""
        with patch.object(process_liveness, "_process_absent",
                          side_effect=[False, True]), \
                patch.object(process_liveness, "_process_state", return_value=None):
            self.assertIs(pid_state(os.getpid()), ProcessState.DEAD)


class TestPortableFallback(unittest.TestCase):
    """Pin behaviour when the Linux process table is unavailable."""

    def test_fallback_alive(self):
        """Without ``/proc`` a successful probe means ALIVE."""
        with patch.object(process_liveness, "_proc_available", return_value=False):
            self.assertIs(pid_state(os.getpid()), ProcessState.ALIVE)

    def test_fallback_dead(self):
        """Without ``/proc`` a lookup failure means DEAD."""
        with patch.object(process_liveness, "_proc_available", return_value=False), \
                patch.object(process_liveness.os, "kill",
                             side_effect=ProcessLookupError):
            self.assertIs(pid_state(4242), ProcessState.DEAD)

    def test_fallback_permission_denied_is_alive(self):
        """A permission refusal proves the process exists, so it is ALIVE."""
        with patch.object(process_liveness, "_proc_available", return_value=False), \
                patch.object(process_liveness.os, "kill",
                             side_effect=PermissionError):
            self.assertIs(pid_state(4242), ProcessState.ALIVE)

    def test_fallback_other_error_is_unknown(self):
        """An unexplained probe failure must fail closed."""
        with patch.object(process_liveness, "_proc_available", return_value=False), \
                patch.object(process_liveness.os, "kill", side_effect=OSError):
            self.assertIs(pid_state(4242), ProcessState.UNKNOWN)


class TestSessionLiveness(unittest.TestCase):
    """Pin the per-session answer derived from every stdout candidate."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="liveness-")
        self.task_dir = os.path.join(self.home, "workspace", "task")
        os.makedirs(self.task_dir)

    def tearDown(self):
        for entry in os.listdir(self.task_dir):
            os.unlink(os.path.join(self.task_dir, entry))
        os.rmdir(self.task_dir)
        os.rmdir(os.path.join(self.home, "workspace"))
        os.rmdir(self.home)

    def _touch(self, name, mtime):
        """Create one stdout candidate with an explicit modification time."""
        path = os.path.join(self.task_dir, name)
        Path(path).write_text("", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_no_candidate_is_idle(self):
        """A session with no stdout file is idle."""
        self.assertEqual(session_liveness("sess-1", home=self.home), "idle")

    def test_empty_session_id_is_unknown(self):
        """An empty identity cannot be answered, so it fails closed."""
        self.assertEqual(session_liveness("", home=self.home), "unknown")

    def test_live_candidate_is_live(self):
        """A live PID proves the session is running."""
        self._touch(f"sess-1.{os.getpid()}.session.stdout", 1000)
        self.assertEqual(session_liveness("sess-1", home=self.home), "live")

    def test_dead_candidate_is_idle(self):
        """A dead PID with no other candidate is idle."""
        self._touch(f"sess-1.{_absent_pid()}.session.stdout", 1000)
        self.assertEqual(session_liveness("sess-1", home=self.home), "idle")

    def test_older_live_candidate_beats_newer_dead_one(self):
        """A newer dead file must not hide an older live process."""
        self._touch(f"sess-1.{os.getpid()}.session.stdout", 1000)
        self._touch(f"sess-1.{_absent_pid()}.session.stdout", 2000)
        self.assertEqual(session_liveness("sess-1", home=self.home), "live")

    def test_zombie_candidate_is_idle(self):
        """A zombie candidate must not keep a session running."""
        pid = _spawn_zombie()
        try:
            self._touch(f"sess-1.{pid}.session.stdout", 1000)
            self.assertEqual(session_liveness("sess-1", home=self.home), "idle")
        finally:
            _reap(pid)

    def test_unparseable_filename_is_not_a_candidate(self):
        """A filename without a parseable PID is not a session candidate."""
        self._touch("sess-1.notapid.session.stdout", 1000)
        self.assertEqual(session_liveness("sess-1", home=self.home), "idle")

    def test_non_positive_pid_candidate_is_unknown(self):
        """A non-positive PID candidate fails closed instead of probing."""
        self._touch("sess-1.-1.session.stdout", 1000)
        self.assertEqual(session_liveness("sess-1", home=self.home), "unknown")

    def test_other_session_is_ignored(self):
        """Candidates belonging to another session must not be inspected."""
        self._touch(f"sess-2.{os.getpid()}.session.stdout", 1000)
        self.assertEqual(session_liveness("sess-1", home=self.home), "idle")

    def test_missing_task_directory_is_idle(self):
        """A missing task directory means no candidate exists."""
        os.rmdir(self.task_dir)
        self.assertEqual(session_liveness("sess-1", home=self.home), "idle")
        os.makedirs(self.task_dir)


if __name__ == "__main__":
    unittest.main()
