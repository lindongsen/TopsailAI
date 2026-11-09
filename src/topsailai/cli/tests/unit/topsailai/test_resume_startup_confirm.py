#!/usr/bin/env python3
"""
Unit tests for the control-channel startup confirmation that follows a resume.

Author: DawsonLin

A launcher exit code only reports what the wrapper did: ``dtach`` and ``tmux``
exit as soon as they have detached, and a background submission only proves
delivery. The resumed process itself must answer on the control channel it
publishes, so these tests pin that the heartbeat is the authority and that a
leftover PID is never mistaken for the process this resume started.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_topsailai import project_scope
from cli_topsailai.project_scope import (
    RESUME_STARTUP_CONFIRM_SECONDS,
    RESUME_STARTUP_POLL_SECONDS,
    _confirm_resumed_startup,
    _new_session_pids,
    _session_socket_pids,
)


def _make_task_dir(home):
    """Create the task directory a session publishes its runtime files into."""
    task_dir = os.path.join(home, "workspace", "task")
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def _make_stdout(task_dir, session_id, pid):
    """Create one session stdout file and return its absolute path."""
    path = os.path.join(task_dir, f"{session_id}.{pid}.session.stdout")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("history\n")
    return path


def _make_socket(task_dir, session_id, pid):
    """Create one session control socket file and return its absolute path."""
    path = os.path.join(task_dir, f"{session_id}.{pid}.session.sock")
    with open(path, "w", encoding="utf-8"):
        pass
    return path


class SessionSocketPidTest(unittest.TestCase):
    """Pin the socket enumeration used to find the resumed process."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.task_dir = _make_task_dir(self.home)

    def tearDown(self):
        self._tmp.cleanup()

    def test_only_matching_session_sockets_are_returned(self):
        """A socket of another session must never be a candidate."""
        _make_socket(self.task_dir, "s1", 11)
        _make_socket(self.task_dir, "s2", 22)

        self.assertEqual(_session_socket_pids(self.task_dir, "s1"), [11])

    def test_non_numeric_pid_is_ignored(self):
        """A socket without a numeric PID cannot identify a process."""
        _make_socket(self.task_dir, "s1", "abc")

        self.assertEqual(_session_socket_pids(self.task_dir, "s1"), [])

    def test_missing_directory_yields_no_candidates(self):
        """An unreadable directory must not raise."""
        missing = os.path.join(self.home, "nope")

        self.assertEqual(_session_socket_pids(missing, "s1"), [])


class NewSessionPidTest(unittest.TestCase):
    """Pin that only PIDs absent from the pre-launch snapshot are new."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.task_dir = _make_task_dir(self.home)

    def tearDown(self):
        self._tmp.cleanup()

    def test_leftover_pid_is_not_new(self):
        """A PID that existed before the launch is a leftover, not this run."""
        leftover = _make_stdout(self.task_dir, "s1", 4242)

        self.assertEqual(
            _new_session_pids("s1", [leftover], home=self.home), []
        )

    def test_new_stdout_pid_is_reported(self):
        """A stdout published after the launch identifies the resumed process."""
        leftover = _make_stdout(self.task_dir, "s1", 4242)
        _make_stdout(self.task_dir, "s1", 5353)

        self.assertEqual(
            _new_session_pids("s1", [leftover], home=self.home), [5353]
        )

    def test_new_socket_pid_is_reported(self):
        """A socket published after the launch is also a new candidate."""
        leftover = _make_stdout(self.task_dir, "s1", 4242)
        _make_socket(self.task_dir, "s1", 6363)

        self.assertEqual(
            _new_session_pids("s1", [leftover], home=self.home), [6363]
        )

    def test_other_session_pid_is_never_reported(self):
        """A sibling session must not be mistaken for this resume."""
        leftover = _make_stdout(self.task_dir, "s1", 4242)
        _make_stdout(self.task_dir, "s2", 7474)

        self.assertEqual(
            _new_session_pids("s1", [leftover], home=self.home), []
        )


class ConfirmResumedStartupTest(unittest.TestCase):
    """Pin the confirmation contract that decides a resume result."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.task_dir = _make_task_dir(self.home)
        self.leftover = _make_stdout(self.task_dir, "s1", 4242)

    def tearDown(self):
        self._tmp.cleanup()

    def _confirm(self, **kwargs):
        """Run one confirmation with a bounded window and no real waiting."""
        options = {
            "code": 0, "mode": "dtach", "background": False,
            "home": self.home, "timeout": 0.0,
        }
        options.update(kwargs)
        return _confirm_resumed_startup("s1", [self.leftover], **options)

    def test_failed_launch_is_never_confirmed(self):
        """A non-zero launcher status cannot be a confirmed startup."""
        result = self._confirm(code=5)

        self.assertFalse(result["startup_confirmed"])
        self.assertEqual(result["startup_reason"], "launch_failed")

    def test_foreground_raw_exit_is_confirmed(self):
        """A foreground raw resume runs the agent itself, so its exit is final."""
        result = self._confirm(mode="raw")

        self.assertTrue(result["startup_confirmed"])
        self.assertEqual(result["startup_reason"], "foreground_raw_exited")

    def test_answered_heartbeat_confirms_the_startup(self):
        """A reachable control channel is the authority for a detached resume."""
        _make_socket(self.task_dir, "s1", 5353)
        with patch.object(
            project_scope, "socket_heartbeat_alive", create=True,
            return_value=True,
        ), patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            return_value=True,
        ):
            result = self._confirm()

        self.assertTrue(result["startup_confirmed"])
        self.assertEqual(result["startup_pid"], 5353)
        self.assertEqual(result["startup_reason"], "heartbeat_answered")

    def test_unreachable_channel_is_not_confirmed(self):
        """A published socket that never answers is not a running agent."""
        _make_socket(self.task_dir, "s1", 5353)
        with patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            return_value=None,
        ):
            result = self._confirm()

        self.assertFalse(result["startup_confirmed"])
        self.assertEqual(result["startup_reason"], "heartbeat_unreachable")

    def test_leftover_socket_is_never_probed(self):
        """A leftover PID from before the launch must not confirm this resume."""
        _make_socket(self.task_dir, "s1", 4242)
        probed = []

        def _heartbeat(session_id, pid, **_kwargs):
            """Record every PID the confirmation actually probes."""
            probed.append(pid)
            return True

        with patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            side_effect=_heartbeat,
        ):
            result = self._confirm()

        self.assertFalse(result["startup_confirmed"])
        self.assertEqual(probed, [])

    def test_background_resume_requires_a_heartbeat(self):
        """A background submission only proves delivery, so it must be probed."""
        with patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            return_value=None,
        ):
            result = self._confirm(mode="raw", background=True)

        self.assertFalse(result["startup_confirmed"])
        self.assertEqual(result["startup_reason"], "heartbeat_unreachable")

    def test_confirmation_window_is_bounded(self):
        """The wait for a control channel must stay bounded."""
        self.assertGreater(RESUME_STARTUP_CONFIRM_SECONDS, 0)
        self.assertLessEqual(RESUME_STARTUP_CONFIRM_SECONDS, 30)

    def test_confirmation_window_and_poll_interval_are_the_agreed_values(self):
        """The window and the poll interval are the operator's stated values."""
        self.assertEqual(RESUME_STARTUP_CONFIRM_SECONDS, 7.0)
        self.assertEqual(RESUME_STARTUP_POLL_SECONDS, 0.2)

    def test_a_late_channel_is_detected_by_periodic_probing(self):
        """A channel published after the first probe must still be confirmed."""
        _make_stdout(self.task_dir, "s1", 6363)
        probes = []

        def _heartbeat(session_id, pid, **_kwargs):
            """Answer only on the third probe, as a slow startup would."""
            probes.append(pid)
            if len(probes) < 3:
                return None
            return True

        with patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            side_effect=_heartbeat,
        ), patch.object(
            project_scope, "RESUME_STARTUP_POLL_SECONDS", 0.0
        ):
            result = _confirm_resumed_startup(
                "s1", [self.leftover], code=0, mode="dtach", background=False,
                home=self.home, timeout=5.0,
            )

        self.assertTrue(result["startup_confirmed"])
        self.assertEqual(result["startup_reason"], "heartbeat_answered")
        self.assertEqual(result["startup_pid"], 6363)
        self.assertGreaterEqual(len(probes), 3)


class BoundedWindowTest(unittest.TestCase):
    """Pin that a silent channel cannot stretch the confirmation window."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.task_dir = _make_task_dir(self.home)
        self.leftover = _make_stdout(self.task_dir, "s1", 4242)

    def tearDown(self):
        self._tmp.cleanup()

    def test_each_probe_is_bounded_by_the_remaining_window(self):
        """A probe must never be granted more time than the window has left."""
        _make_socket(self.task_dir, "s1", 5353)
        granted = []

        def _heartbeat(session_id, pid, **kwargs):
            """Record the timeout each probe was granted, then stay silent."""
            granted.append(kwargs.get("timeout"))
            return None

        with patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            side_effect=_heartbeat,
        ), patch.object(project_scope, "RESUME_STARTUP_POLL_SECONDS", 0.0):
            _confirm_resumed_startup(
                "s1", [self.leftover], code=0, mode="dtach", background=False,
                home=self.home, timeout=0.5,
            )

        self.assertTrue(granted)
        for timeout in granted:
            self.assertIsNotNone(timeout)
            self.assertLessEqual(timeout, 0.5)

    def test_a_silent_channel_does_not_overshoot_the_window(self):
        """A socket that never answers must not extend the total wait."""
        _make_socket(self.task_dir, "s1", 5353)

        def _heartbeat(session_id, pid, **kwargs):
            """Consume the whole granted timeout, as a silent socket would."""
            time.sleep(kwargs.get("timeout") or 0.0)
            return None

        window = 0.5
        started = time.monotonic()
        with patch(
            "cli_topsailai.process_liveness.socket_heartbeat_alive",
            side_effect=_heartbeat,
        ):
            result = _confirm_resumed_startup(
                "s1", [self.leftover], code=0, mode="dtach", background=False,
                home=self.home, timeout=window,
            )
        elapsed = time.monotonic() - started

        self.assertFalse(result["startup_confirmed"])
        self.assertEqual(result["startup_reason"], "heartbeat_unreachable")
        self.assertLess(elapsed, window + 0.3)


class ConfirmWindowEnvironmentTest(unittest.TestCase):
    """Pin how the confirmation window is resolved from the environment."""

    def setUp(self):
        self._saved = os.environ.get(project_scope.RESUME_STARTUP_CONFIRM_ENV)
        os.environ.pop(project_scope.RESUME_STARTUP_CONFIRM_ENV, None)

    def tearDown(self):
        os.environ.pop(project_scope.RESUME_STARTUP_CONFIRM_ENV, None)
        if self._saved is not None:
            os.environ[project_scope.RESUME_STARTUP_CONFIRM_ENV] = self._saved

    def _resolve(self, value):
        """Resolve the window for one configured value."""
        if value is None:
            os.environ.pop(project_scope.RESUME_STARTUP_CONFIRM_ENV, None)
        else:
            os.environ[project_scope.RESUME_STARTUP_CONFIRM_ENV] = value
        return project_scope._resolve_resume_confirm_seconds()

    def test_the_variable_uses_the_cli_namespace(self):
        """A CLI-only knob must carry the TOPSAILAI_CLI_ prefix."""
        self.assertEqual(
            project_scope.RESUME_STARTUP_CONFIRM_ENV,
            "TOPSAILAI_CLI_RESUME_CONFIRM_SECONDS",
        )

    def test_the_minimum_is_seven_seconds(self):
        """The operator set seven seconds as the smallest accepted window."""
        self.assertEqual(project_scope.RESUME_STARTUP_CONFIRM_MIN_SECONDS, 7.0)

    def test_an_unset_variable_uses_the_default(self):
        """No configuration must fall back to the documented default."""
        self.assertEqual(self._resolve(None), 7.0)

    def test_a_value_below_the_minimum_is_raised_to_the_minimum(self):
        """A shorter window would misreport a slow startup, so it is raised."""
        self.assertEqual(self._resolve("3"), 7.0)

    def test_a_value_above_the_minimum_is_honoured(self):
        """A longer window is a legitimate operator choice."""
        self.assertEqual(self._resolve("15"), 15.0)

    def test_a_non_numeric_value_falls_back_to_the_default(self):
        """A malformed value must not disable the confirmation."""
        self.assertEqual(self._resolve("abc"), 7.0)

    def test_a_non_positive_value_falls_back_to_the_default(self):
        """Zero and negative windows cannot bound a wait."""
        self.assertEqual(self._resolve("0"), 7.0)
        self.assertEqual(self._resolve("-5"), 7.0)

    def test_an_explicit_timeout_wins_over_the_variable(self):
        """A caller-supplied window takes precedence over the environment."""
        os.environ[project_scope.RESUME_STARTUP_CONFIRM_ENV] = "20"
        with tempfile.TemporaryDirectory() as home:
            task_dir = _make_task_dir(home)
            leftover = _make_stdout(task_dir, "s1", 4242)
            _make_socket(task_dir, "s1", 5353)
            granted = []

            def _heartbeat(session_id, pid, **kwargs):
                """Record the granted timeout, then stay silent."""
                granted.append(kwargs.get("timeout"))
                return None

            with patch(
                "cli_topsailai.process_liveness.socket_heartbeat_alive",
                side_effect=_heartbeat,
            ), patch.object(project_scope, "RESUME_STARTUP_POLL_SECONDS", 0.0):
                _confirm_resumed_startup(
                    "s1", [leftover], code=0, mode="dtach", background=False,
                    home=home, timeout=0.5,
                )

        self.assertTrue(granted)
        for timeout in granted:
            self.assertLessEqual(timeout, 0.5)


if __name__ == "__main__":
    unittest.main()
