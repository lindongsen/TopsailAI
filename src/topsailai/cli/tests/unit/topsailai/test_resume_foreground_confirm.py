#!/usr/bin/env python3
"""
Unit tests for the foreground resume startup confirmation ordering.

Author: DawsonLin

A foreground ``dtach`` resume blocks until the agent exits, and the agent
removes its control socket on the way out. Probing the channel only after that
wait therefore always finds the socket already gone and reports a healthy run
as unreachable. These tests pin that the probe runs while the wait is still in
progress, and that the heartbeat stays the authority in every other case.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import project_scope
from cli_topsailai.driver_ownership import DriverOwnership
from cli_topsailai.project_scope import resume_session_result

SESSION_ID = "s1"
CHILD_PID = 4242


def _make_task_dir(home):
    """Create the task directory a session publishes its runtime files into."""
    task_dir = os.path.join(home, "workspace", "task")
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def _socket_path(home, session_id, pid):
    """Return the control socket path the resumed process would publish."""
    return os.path.join(
        home, "workspace", "task", f"{session_id}.{pid}.session.sock"
    )


class FakeChild:
    """Child double whose wait simulates a real agent run.

    ``on_run`` receives the socket path and decides what the agent does while
    it is running, so a test can publish the channel, keep it, or never create
    it at all.
    """

    def __init__(self, socket_path, on_run, returncode=0):
        self.pid = CHILD_PID
        self.returncode = returncode
        self.socket_path = socket_path
        self.on_run = on_run
        self.waited = False

    def wait(self, timeout=None):
        """Simulate the agent run, then report the exit status."""
        self.waited = True
        self.on_run(self.socket_path)
        return self.returncode

    def poll(self):
        """Report the exit status without blocking."""
        return self.returncode

    def terminate(self):
        """Accept a termination request without effect."""

    def kill(self):
        """Accept a kill request without effect."""


def _heartbeat_from_socket(session_id, pid, **kwargs):
    """Answer like the real probe: only an existing socket can answer."""
    if not session_id or pid != CHILD_PID:
        return None
    path = _socket_path(_heartbeat_from_socket.home, session_id, pid)
    return True if os.path.exists(path) else None


class ForegroundConfirmOrderingTest(unittest.TestCase):
    """Pin that a foreground resume confirms while the agent is still running."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.workspace = os.path.join(self.home, "project")
        os.makedirs(self.workspace, exist_ok=True)
        _make_task_dir(self.home)
        self.socket_path = _socket_path(self.home, SESSION_ID, CHILD_PID)
        _heartbeat_from_socket.home = self.home

    def tearDown(self):
        self._tmp.cleanup()

    def _resume(self, on_run, returncode=0):
        """Run one real foreground resume with a simulated agent run."""
        child = FakeChild(self.socket_path, on_run, returncode=returncode)
        receipt = {}
        record = {"project_workspace": self.workspace}
        with patch.object(
            project_scope, "lookup_persisted_session", return_value=record
        ), patch.object(
            project_scope, "session_liveness", return_value="idle"
        ), patch.object(
            project_scope, "_apply_selected_model_environment",
            return_value=({}, set()),
        ), patch.object(
            project_scope, "_driver_argv", return_value=["python3"]
        ), patch.object(
            project_scope, "_driver_is_resolvable", return_value=True
        ), patch.object(
            project_scope, "_build_driver_pidfile", return_value=None
        ), patch.object(
            project_scope, "_build_owned_command",
            return_value=(["python3"], DriverOwnership(kind="dtach")),
        ), patch.object(
            project_scope, "_delete_invalid_session_stdout", return_value=[]
        ), patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            side_effect=_heartbeat_from_socket,
        ), patch.object(
            project_scope, "RESUME_STARTUP_POLL_SECONDS", 0.02
        ), patch("sys.stdout"):
            code = resume_session_result(
                SESSION_ID, home=self.home, emit_status=False,
                spawn=lambda argv, **kwargs: child, receipt=receipt,
            )
        return code, receipt, child

    def test_a_run_that_publishes_then_removes_its_socket_is_confirmed(self):
        """The probe must observe the channel before the agent removes it."""
        observed = []

        def _run(socket_path):
            """Publish the channel, stay alive briefly, then clean up."""
            with open(socket_path, "w", encoding="utf-8"):
                pass
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if os.path.exists(socket_path) and observed:
                    break
                time.sleep(0.01)
            os.remove(socket_path)

        def _heartbeat(session_id, pid, **kwargs):
            """Record that the probe ran while the socket still existed."""
            answer = _heartbeat_from_socket(session_id, pid, **kwargs)
            if answer is True:
                observed.append(pid)
            return answer

        child = FakeChild(self.socket_path, _run)
        record = {"project_workspace": self.workspace}
        receipt = {}
        with patch.object(
            project_scope, "lookup_persisted_session", return_value=record
        ), patch.object(
            project_scope, "session_liveness", return_value="idle"
        ), patch.object(
            project_scope, "_apply_selected_model_environment",
            return_value=({}, set()),
        ), patch.object(
            project_scope, "_driver_argv", return_value=["python3"]
        ), patch.object(
            project_scope, "_driver_is_resolvable", return_value=True
        ), patch.object(
            project_scope, "_build_driver_pidfile", return_value=None
        ), patch.object(
            project_scope, "_build_owned_command",
            return_value=(["python3"], DriverOwnership(kind="dtach")),
        ), patch.object(
            project_scope, "_delete_invalid_session_stdout", return_value=[]
        ), patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            side_effect=_heartbeat,
        ), patch.object(
            project_scope, "RESUME_STARTUP_POLL_SECONDS", 0.02
        ), patch("sys.stdout"):
            code = resume_session_result(
                SESSION_ID, home=self.home, emit_status=False,
                spawn=lambda argv, **kwargs: child, receipt=receipt,
            )

        self.assertTrue(child.waited)
        self.assertEqual(code, 0)
        self.assertTrue(receipt.get("startup_confirmed"))
        self.assertEqual(receipt.get("startup_reason"), "heartbeat_answered")
        self.assertEqual(receipt.get("startup_pid"), CHILD_PID)
        self.assertTrue(observed, "the probe never observed the live channel")

    def test_a_channel_that_survives_the_wait_is_still_confirmed(self):
        """A detached run keeps its socket, so the heartbeat still decides."""
        def _run(socket_path):
            """Publish the channel and leave it in place."""
            with open(socket_path, "w", encoding="utf-8"):
                pass

        code, receipt, child = self._resume(_run)

        self.assertTrue(child.waited)
        self.assertEqual(code, 0)
        self.assertEqual(receipt.get("startup_reason"), "heartbeat_answered")

    def test_a_run_without_a_channel_is_never_confirmed(self):
        """A child that never publishes a channel must not be trusted."""
        def _run(socket_path):
            """Exit without ever publishing a control channel."""

        code, receipt, child = self._resume(_run)

        self.assertTrue(child.waited)
        self.assertEqual(code, 4)
        self.assertFalse(receipt.get("startup_confirmed"))
        self.assertEqual(receipt.get("startup_reason"), "heartbeat_unreachable")

    def test_the_probe_starts_before_the_blocking_wait(self):
        """The probe must be running while the foreground wait is in progress."""
        probe_was_running = []

        def _run(socket_path):
            """Record whether the probe thread was already alive."""
            probe_was_running.append(
                any(
                    thread.name == "resume-startup-confirm"
                    for thread in threading.enumerate()
                )
            )

        self._resume(_run)

        self.assertEqual(probe_was_running, [True])

    def test_a_probe_start_failure_still_waits_for_the_child(self):
        """A thread-start failure must not skip the wait and orphan the child."""
        def _run(socket_path):
            """Publish the channel so the fallback confirmation can succeed."""
            with open(socket_path, "w", encoding="utf-8"):
                pass

        child = FakeChild(self.socket_path, _run)
        record = {"project_workspace": self.workspace}
        receipt = {}
        with patch.object(
            project_scope, "lookup_persisted_session", return_value=record
        ), patch.object(
            project_scope, "session_liveness", return_value="idle"
        ), patch.object(
            project_scope, "_apply_selected_model_environment",
            return_value=({}, set()),
        ), patch.object(
            project_scope, "_driver_argv", return_value=["python3"]
        ), patch.object(
            project_scope, "_driver_is_resolvable", return_value=True
        ), patch.object(
            project_scope, "_build_driver_pidfile", return_value=None
        ), patch.object(
            project_scope, "_build_owned_command",
            return_value=(["python3"], DriverOwnership(kind="dtach")),
        ), patch.object(
            project_scope, "_delete_invalid_session_stdout", return_value=[]
        ), patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            side_effect=_heartbeat_from_socket,
        ), patch.object(
            project_scope, "RESUME_STARTUP_POLL_SECONDS", 0.02
        ), patch.object(
            threading.Thread, "start", side_effect=RuntimeError("no threads")
        ), patch("sys.stdout"):
            code = resume_session_result(
                SESSION_ID, home=self.home, emit_status=False,
                spawn=lambda argv, **kwargs: child, receipt=receipt,
            )

        self.assertTrue(
            child.waited,
            "a probe start failure skipped the wait and orphaned the child",
        )
        self.assertEqual(code, 0)
        self.assertTrue(receipt.get("startup_confirmed"))
        self.assertEqual(receipt.get("startup_reason"), "heartbeat_answered")

if __name__ == "__main__":
    unittest.main()
