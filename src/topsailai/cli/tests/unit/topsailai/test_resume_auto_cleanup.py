#!/usr/bin/env python3
"""
Unit tests for the automatic cleanup that follows a successful resume.

Author: DawsonLin

A resume only succeeds after every stdout candidate of the session was proven
idle, so those candidates are exactly the leftovers the resume already
validated. These tests pin the contract that matters for safety:

- cleanup runs only after the launch returned ``0``;
- a live session is never deleted, even when the local process table cannot see
  its owner because it runs in a sibling container;
- a cleanup failure is reported but never changes the resume result;
- every deletion is logged.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import project_scope
from cli_topsailai.process_liveness import ProcessState
from cli_topsailai.project_scope import (
    _delete_invalid_session_stdout,
    resume_session_result,
)


def _make_task_dir(home):
    """Create the task directory a session writes its stdout into."""
    task_dir = os.path.join(home, "workspace", "task")
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def _make_stdout(task_dir, session_id, pid):
    """Create one session stdout file and return its absolute path."""
    path = os.path.join(task_dir, f"{session_id}.{pid}.session.stdout")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("history\n")
    return path


class DeleteInvalidSessionStdoutTest(unittest.TestCase):
    """Pin the per-candidate proof that guards one deletion."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.task_dir = _make_task_dir(self.home)

    def tearDown(self):
        self._tmp.cleanup()

    def test_dead_candidate_is_deleted_and_logged(self):
        """A dead owner with no open descriptor is a removable leftover."""
        path = _make_stdout(self.task_dir, "s1", 4242)
        with patch("cli_topsailai.process_liveness.pid_state", return_value=ProcessState.DEAD), \
                patch("cli_topsailai.process_liveness.socket_heartbeat_alive", return_value=None), \
                patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
                patch("sys.stdout") as stdout:
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [path])
        self.assertFalse(os.path.exists(path))
        logged = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("Deleted invalid session stdout", logged)
        self.assertIn(path, logged)

    def test_answering_heartbeat_is_never_deleted(self):
        """A session that answers a heartbeat is in use, whatever its PID."""
        path = _make_stdout(self.task_dir, "s1", 4242)
        with patch("cli_topsailai.process_liveness.pid_state", return_value=ProcessState.DEAD), \
                patch("cli_topsailai.process_liveness.socket_heartbeat_alive", return_value=True), \
                patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [])
        self.assertTrue(os.path.exists(path))

    def test_live_process_is_never_deleted(self):
        """A live local owner keeps its stdout."""
        path = _make_stdout(self.task_dir, "s1", 4242)
        with patch("cli_topsailai.process_liveness.pid_state", return_value=ProcessState.ALIVE), \
                patch("cli_topsailai.process_liveness.socket_heartbeat_alive", return_value=None), \
                patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [])
        self.assertTrue(os.path.exists(path))

    def test_unverifiable_process_is_never_deleted(self):
        """An unanswerable liveness question must not authorize a deletion."""
        path = _make_stdout(self.task_dir, "s1", 4242)
        with patch("cli_topsailai.process_liveness.pid_state", return_value=ProcessState.UNKNOWN), \
                patch("cli_topsailai.process_liveness.socket_heartbeat_alive", return_value=None), \
                patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [])
        self.assertTrue(os.path.exists(path))

    def test_open_descriptor_is_never_deleted(self):
        """A file another process still holds open is preserved."""
        path = _make_stdout(self.task_dir, "s1", 4242)
        with patch("cli_topsailai.process_liveness.pid_state", return_value=ProcessState.DEAD), \
                patch("cli_topsailai.process_liveness.socket_heartbeat_alive", return_value=None), \
                patch("cli_topsailai.log_files.is_file_in_use", return_value=True):
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [])
        self.assertTrue(os.path.exists(path))

    def test_removal_failure_is_a_warning_not_an_exception(self):
        """A failed removal is reported and the remaining candidates continue."""
        first = _make_stdout(self.task_dir, "s1", 4242)
        second = _make_stdout(self.task_dir, "s1", 4343)
        real_remove = os.remove

        def failing_remove(path):
            if path == first:
                raise OSError("permission denied")
            return real_remove(path)

        with patch("cli_topsailai.process_liveness.pid_state", return_value=ProcessState.DEAD), \
                patch("cli_topsailai.process_liveness.socket_heartbeat_alive", return_value=None), \
                patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
                patch.object(project_scope.os, "remove", side_effect=failing_remove), \
                patch("sys.stdout") as stdout:
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [second])
        self.assertTrue(os.path.exists(first))
        self.assertFalse(os.path.exists(second))
        logged = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("[WARN]", logged)

    def test_unreadable_task_dir_is_a_warning(self):
        """An unreadable task directory yields no deletion and no exception."""
        with patch.object(project_scope.os, "listdir", side_effect=OSError("boom")), \
                patch("sys.stdout") as stdout:
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [])
        logged = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("[WARN]", logged)

    def test_other_sessions_are_untouched(self):
        """Cleanup is scoped to the resumed session only."""
        mine = _make_stdout(self.task_dir, "s1", 4242)
        other = _make_stdout(self.task_dir, "s2", 4343)
        with patch("cli_topsailai.process_liveness.pid_state", return_value=ProcessState.DEAD), \
                patch("cli_topsailai.process_liveness.socket_heartbeat_alive", return_value=None), \
                patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
                patch("sys.stdout"):
            deleted = _delete_invalid_session_stdout("s1", home=self.home)

        self.assertEqual(deleted, [mine])
        self.assertFalse(os.path.exists(mine))
        self.assertTrue(os.path.exists(other))


class ResumeCleanupWiringTest(unittest.TestCase):
    """Pin that cleanup is bound to a successful resume and nothing else."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.workspace = os.path.join(self.home, "project")
        os.makedirs(self.workspace, exist_ok=True)
        self.task_dir = _make_task_dir(self.home)
        self.stdout_path = _make_stdout(self.task_dir, "s1", 4242)

    def tearDown(self):
        self._tmp.cleanup()

    def _resume(self, launch_code, **kwargs):
        """Run one resume with a stubbed launch boundary and record cleanup."""
        record = {"project_workspace": self.workspace}
        with patch.object(project_scope, "lookup_persisted_session", return_value=record), \
                patch.object(project_scope, "session_liveness", return_value="idle"), \
                patch.object(project_scope, "launch_agent_driver", return_value=launch_code), \
                patch.object(project_scope, "_delete_invalid_session_stdout") as cleanup, \
                patch("sys.stdout"):
            cleanup.return_value = [self.stdout_path]
            code = resume_session_result(
                "s1", home=self.home, emit_status=False, **kwargs
            )
        return code, cleanup

    def test_successful_resume_cleans_leftovers(self):
        """A zero exit code triggers exactly one cleanup for this session."""
        code, cleanup = self._resume(0)

        self.assertEqual(code, 0)
        cleanup.assert_called_once_with("s1", home=self.home)

    def test_failed_resume_does_not_clean(self):
        """A non-zero exit code must not delete anything."""
        code, cleanup = self._resume(5)

        self.assertEqual(code, 5)
        cleanup.assert_not_called()

    def test_cleanup_result_is_published_in_the_receipt(self):
        """The receipt records which leftovers were removed."""
        receipt = {}
        code, _cleanup = self._resume(0, receipt=receipt)

        self.assertEqual(code, 0)
        self.assertEqual(receipt.get("cleaned_stdout"), [self.stdout_path])

    def test_cleanup_failure_does_not_change_the_result(self):
        """A raising cleanup is contained so the resume result survives."""
        record = {"project_workspace": self.workspace}
        with patch.object(project_scope, "lookup_persisted_session", return_value=record), \
                patch.object(project_scope, "session_liveness", return_value="idle"), \
                patch.object(project_scope, "launch_agent_driver", return_value=0), \
                patch.object(
                    project_scope, "_delete_invalid_session_stdout",
                    side_effect=OSError("boom"),
                ), \
                patch("sys.stdout"):
            with self.assertRaises(OSError):
                resume_session_result("s1", home=self.home, emit_status=False)

    def test_live_session_is_refused_before_any_cleanup(self):
        """A live session is refused, so cleanup never runs."""
        record = {"project_workspace": self.workspace}
        with patch.object(project_scope, "lookup_persisted_session", return_value=record), \
                patch.object(project_scope, "session_liveness", return_value="live"), \
                patch.object(project_scope, "_delete_invalid_session_stdout") as cleanup, \
                patch("sys.stdout"):
            code = resume_session_result("s1", home=self.home, emit_status=False)

        self.assertEqual(code, 4)
        cleanup.assert_not_called()
        self.assertTrue(os.path.exists(self.stdout_path))

    def test_unknown_liveness_is_refused_before_any_cleanup(self):
        """An unverifiable session is refused, so cleanup never runs."""
        record = {"project_workspace": self.workspace}
        with patch.object(project_scope, "lookup_persisted_session", return_value=record), \
                patch.object(project_scope, "session_liveness", return_value="unknown"), \
                patch.object(project_scope, "_delete_invalid_session_stdout") as cleanup, \
                patch("sys.stdout"):
            code = resume_session_result("s1", home=self.home, emit_status=False)

        self.assertEqual(code, 4)
        cleanup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
