#!/usr/bin/env python3
"""
Unit tests for the control-channel heartbeat liveness probe.

Author: DawsonLin

The heartbeat is the first-priority liveness method because a session may run
in a sibling container that shares this filesystem. The local process table
cannot see such an owner, so ``pid_state`` reports ``DEAD`` for a live session
and the delete path would remove a running session's stdout. These tests pin
the three-state contract (``True``/``False``/``None``) and the delete guard
that depends on it.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import process_liveness
from cli_topsailai.process_liveness import (
    HEARTBEAT_TIMEOUT_SECONDS,
    ProcessState,
    socket_heartbeat_alive,
)
from cli_topsailai.session_cli import _invalid_stdout_target


class _FakeResult:
    """Minimal stand-in for the control transport result object."""

    def __init__(self, response):
        self.response = response


def _ok_response(pid, alive=True, session_id="s1"):
    """Build a heartbeat response shaped like the real handler output."""
    return _FakeResult({
        "request_id": "req",
        "status": "ok",
        "result": {
            "alive": alive,
            "pid": pid,
            "hostname": "topsail",
            "session_id": session_id,
        },
    })


class HeartbeatTimeoutTest(unittest.TestCase):
    """Pin the approved three-second budget."""

    def test_timeout_is_three_seconds(self):
        self.assertEqual(HEARTBEAT_TIMEOUT_SECONDS, 3.0)


class HeartbeatProbeTest(unittest.TestCase):
    """Pin the three-state contract of the heartbeat probe."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="hb-home-")
        self.task_dir = os.path.join(self.home, "workspace", "task")
        os.makedirs(self.task_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.home, ignore_errors=True)

    def _socket(self, session_id, pid):
        path = os.path.join(self.task_dir, f"{session_id}.{pid}.session.sock")
        with open(path, "w", encoding="utf-8"):
            pass
        return path

    def test_missing_socket_returns_none(self):
        """An absent socket must fall back instead of claiming absence."""
        self.assertIsNone(socket_heartbeat_alive("s1", 4242, home=self.home))

    def test_invalid_pid_returns_none(self):
        """A non-positive or non-integer PID cannot identify an endpoint."""
        for bad in (0, -1, None, "4242", True):
            self.assertIsNone(socket_heartbeat_alive("s1", bad, home=self.home))

    def test_empty_session_id_returns_none(self):
        self.assertIsNone(socket_heartbeat_alive("", 4242, home=self.home))

    def test_matching_answer_returns_true(self):
        """A live endpoint answering for the expected identity proves liveness."""
        self._socket("s1", 4242)
        with patch("cli_topsailai.runtime_control.send_to_control",
                   return_value=_ok_response(4242)):
            self.assertIs(socket_heartbeat_alive("s1", 4242, home=self.home), True)

    def test_refused_connection_returns_false(self):
        """A refused connection proves the listener is gone."""
        import errno
        from cli_topsailai.runtime_control import ControlDeliveryError

        self._socket("s1", 4242)
        error = ControlDeliveryError("refused", "transport_error", 1)
        error.__cause__ = OSError(errno.ECONNREFUSED, "Connection refused")
        with patch("cli_topsailai.runtime_control.send_to_control",
                   side_effect=error):
            self.assertIs(socket_heartbeat_alive("s1", 4242, home=self.home), False)

    def test_timeout_returns_none(self):
        """An unanswered heartbeat must not be read as absence."""
        from cli_topsailai.runtime_control import ControlDeliveryError

        self._socket("s1", 4242)
        error = ControlDeliveryError("no answer", "timeout", 1)
        with patch("cli_topsailai.runtime_control.send_to_control",
                   side_effect=error):
            self.assertIsNone(socket_heartbeat_alive("s1", 4242, home=self.home))

    def test_pid_mismatch_still_returns_true(self):
        """A session that answers is alive even when its recorded PID differs."""
        self._socket("s1", 4242)
        with patch("cli_topsailai.runtime_control.send_to_control",
                   return_value=_ok_response(9999)):
            self.assertIs(socket_heartbeat_alive("s1", 4242, home=self.home), True)

    def test_alive_false_still_returns_true(self):
        """A correlated ok answer proves a live owner regardless of its payload."""
        self._socket("s1", 4242)
        with patch("cli_topsailai.runtime_control.send_to_control",
                   return_value=_ok_response(4242, alive=False)):
            self.assertIs(socket_heartbeat_alive("s1", 4242, home=self.home), True)

    def test_missing_result_payload_still_returns_true(self):
        """A correlated ok answer is proof of life even without a result body."""
        self._socket("s1", 4242)
        with patch("cli_topsailai.runtime_control.send_to_control",
                   return_value=_FakeResult({"status": "ok"})):
            self.assertIs(socket_heartbeat_alive("s1", 4242, home=self.home), True)


class SessionLivenessHeartbeatTest(unittest.TestCase):
    """Pin that a heartbeat answer outranks an invisible process table."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="hb-live-")
        self.task_dir = os.path.join(self.home, "workspace", "task")
        os.makedirs(self.task_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.home, ignore_errors=True)

    def _stdout(self, session_id, pid):
        path = os.path.join(self.task_dir, f"{session_id}.{pid}.session.stdout")
        with open(path, "w", encoding="utf-8"):
            pass
        return path

    def test_sibling_container_session_is_live(self):
        """A session whose owner is invisible locally is still live."""
        self._stdout("s1", 4242)
        with patch.object(process_liveness, "socket_heartbeat_alive",
                          return_value=True), \
             patch.object(process_liveness, "pid_state",
                          return_value=ProcessState.DEAD):
            self.assertEqual(
                process_liveness.session_liveness("s1", home=self.home), "live")

    def test_no_socket_falls_back_to_process_table(self):
        """Without a control channel the process table still decides."""
        self._stdout("s1", 4242)
        with patch.object(process_liveness, "socket_heartbeat_alive",
                          return_value=None), \
             patch.object(process_liveness, "pid_state",
                          return_value=ProcessState.DEAD):
            self.assertEqual(
                process_liveness.session_liveness("s1", home=self.home), "idle")

    def test_unknown_process_state_still_reports_unknown(self):
        """An unverifiable owner must not be downgraded to idle."""
        self._stdout("s1", 4242)
        with patch.object(process_liveness, "socket_heartbeat_alive",
                          return_value=None), \
             patch.object(process_liveness, "pid_state",
                          return_value=ProcessState.UNKNOWN):
            self.assertEqual(
                process_liveness.session_liveness("s1", home=self.home), "unknown")


class DeleteGuardHeartbeatTest(unittest.TestCase):
    """Pin that the delete guard refuses a session that answers a heartbeat."""

    def setUp(self):
        self.task_dir = tempfile.mkdtemp(prefix="hb-del-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.task_dir, ignore_errors=True)

    def _stdout(self, session_id, pid):
        path = os.path.join(self.task_dir, f"{session_id}.{pid}.session.stdout")
        with open(path, "w", encoding="utf-8"):
            pass
        return path

    def test_heartbeat_blocks_deletion_of_invisible_owner(self):
        """The regression this change fixes: a live sibling session is kept."""
        self._stdout("s1", 4242)
        path, code, message = _invalid_stdout_target(
            self.task_dir, "s1", 4242,
            pid_state=lambda pid: ProcessState.DEAD,
            in_use=lambda path: False,
            heartbeat=lambda session_id, pid: True,
        )
        self.assertIsNone(path)
        self.assertEqual(code, "target_alive")
        self.assertIn("heartbeat", message)

    def test_heartbeat_consulted_before_process_table(self):
        """The heartbeat must be asked first, not after the table says dead."""
        self._stdout("s1", 4242)
        calls = []

        def heartbeat(session_id, pid):
            calls.append("heartbeat")
            return True

        def pid_state(pid):
            calls.append("pid_state")
            return ProcessState.DEAD

        _invalid_stdout_target(
            self.task_dir, "s1", 4242,
            pid_state=pid_state, in_use=lambda path: False, heartbeat=heartbeat,
        )
        self.assertEqual(calls, ["heartbeat"])

    def test_dead_session_without_heartbeat_is_deletable(self):
        """A provably dead session with no channel stays deletable."""
        self._stdout("s1", 4242)
        path, code, message = _invalid_stdout_target(
            self.task_dir, "s1", 4242,
            pid_state=lambda pid: ProcessState.DEAD,
            in_use=lambda path: False,
            heartbeat=lambda session_id, pid: None,
        )
        self.assertIsNotNone(path)
        self.assertIsNone(code)
        self.assertIsNone(message)

    def test_heartbeat_false_does_not_block(self):
        """A refused connection is not liveness, so deletion may proceed."""
        self._stdout("s1", 4242)
        path, code, _ = _invalid_stdout_target(
            self.task_dir, "s1", 4242,
            pid_state=lambda pid: ProcessState.DEAD,
            in_use=lambda path: False,
            heartbeat=lambda session_id, pid: False,
        )
        self.assertIsNotNone(path)
        self.assertIsNone(code)

    def test_file_in_use_still_blocks_without_heartbeat(self):
        """The descriptor probe remains the fallback guard."""
        self._stdout("s1", 4242)
        path, code, _ = _invalid_stdout_target(
            self.task_dir, "s1", 4242,
            pid_state=lambda pid: ProcessState.DEAD,
            in_use=lambda path: True,
            heartbeat=lambda session_id, pid: None,
        )
        self.assertIsNone(path)
        self.assertEqual(code, "file_in_use")

    def test_unknown_owner_still_refused(self):
        """An unverifiable owner is still refused, heartbeat or not."""
        self._stdout("s1", 4242)
        path, code, _ = _invalid_stdout_target(
            self.task_dir, "s1", 4242,
            pid_state=lambda pid: ProcessState.UNKNOWN,
            in_use=lambda path: False,
            heartbeat=lambda session_id, pid: None,
        )
        self.assertIsNone(path)
        self.assertEqual(code, "target_identity_unavailable")

    def test_missing_file_reported_before_any_probe(self):
        """A missing target is reported without probing anything."""
        calls = []
        path, code, _ = _invalid_stdout_target(
            self.task_dir, "s1", 4242,
            pid_state=lambda pid: calls.append("pid_state"),
            in_use=lambda path: calls.append("in_use"),
            heartbeat=lambda session_id, pid: calls.append("heartbeat"),
        )
        self.assertIsNone(path)
        self.assertEqual(code, "target_not_found")
        self.assertEqual(calls, [])

    def test_identity_escaping_task_dir_is_refused(self):
        """A crafted identity must never reach a file outside the task dir."""
        outside = os.path.join(os.path.dirname(self.task_dir),
                               "victim.4242.session.stdout")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("unrelated data")
        calls = []
        path, code, _ = _invalid_stdout_target(
            self.task_dir, "../victim", 4242,
            pid_state=lambda pid: calls.append("pid_state"),
            in_use=lambda path: calls.append("in_use"),
            heartbeat=lambda session_id, pid: calls.append("heartbeat"),
        )
        self.assertIsNone(path)
        self.assertEqual(code, "target_not_found")
        self.assertEqual(calls, [])
        self.assertTrue(os.path.isfile(outside))


if __name__ == "__main__":
    unittest.main()
