#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for ai_list_sessions.py."""

import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

# Ensure the cli package and src modules are importable.
CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(CLI_ROOT, "..", "src"))
sys.path.insert(0, CLI_ROOT)
sys.path.insert(0, SRC_ROOT)

import ai_list_sessions
from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData

class FakeSession:
    """Minimal session-like object for formatting tests."""

    def __init__(self, session_id, session_name, create_time, task):
        self.session_id = session_id
        self.session_name = session_name
        self.create_time = create_time
        self.task = task


class TestRelativeTime(unittest.TestCase):
    """Tests for _relative_time helper."""

    def test_just_now(self):
        now = datetime.now()
        self.assertEqual(ai_list_sessions._relative_time(now), "just now")

    def test_minutes_ago(self):
        past = datetime.now() - timedelta(minutes=5)
        self.assertEqual(ai_list_sessions._relative_time(past), "5 minutes ago")

    def test_one_minute_ago(self):
        past = datetime.now() - timedelta(minutes=1)
        self.assertEqual(ai_list_sessions._relative_time(past), "1 minute ago")

    def test_hours_ago(self):
        past = datetime.now() - timedelta(hours=3)
        self.assertEqual(ai_list_sessions._relative_time(past), "3 hours ago")

    def test_days_ago(self):
        past = datetime.now() - timedelta(days=2)
        self.assertEqual(ai_list_sessions._relative_time(past), "2 days ago")

    def test_none_create_time(self):
        self.assertEqual(ai_list_sessions._relative_time(None), "")


class TestColorSupport(unittest.TestCase):
    """Tests for _supports_color helper."""

    def test_no_color_env_disables_color(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            with mock.patch.object(sys.stdout, "isatty", return_value=True):
                self.assertFalse(ai_list_sessions._supports_color())

    def test_force_color_env_enables_color(self):
        with mock.patch.dict(os.environ, {"FORCE_COLOR": "1", "NO_COLOR": ""}, clear=True):
            with mock.patch.object(sys.stdout, "isatty", return_value=False):
                self.assertTrue(ai_list_sessions._supports_color())

    def test_tty_supports_color(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "", "FORCE_COLOR": ""}, clear=True):
            with mock.patch.object(sys.stdout, "isatty", return_value=True):
                self.assertTrue(ai_list_sessions._supports_color())

    def test_non_tty_no_color(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "", "FORCE_COLOR": ""}, clear=True):
            with mock.patch.object(sys.stdout, "isatty", return_value=False):
                self.assertFalse(ai_list_sessions._supports_color())


class TestFormatSessions(unittest.TestCase):
    """Tests for format_sessions output."""

    def test_empty_sessions(self):
        self.assertEqual(ai_list_sessions.format_sessions([]), "No sessions found.")

    @mock.patch.object(ai_list_sessions, "_supports_color", return_value=False)
    @mock.patch("shutil.get_terminal_size", return_value=mock.Mock(columns=80))
    def test_single_session(self, _mock_size, _mock_color):
        session = FakeSession(
            session_id="abc123",
            session_name="test-session",
            create_time=datetime(2026, 7, 5, 10, 30, 15),
            task="Do something useful.",
        )
        output = ai_list_sessions.format_sessions([session])
        self.assertIn("Sessions (Total: 1)", output)
        self.assertIn("[1] abc123", output)
        self.assertIn("Name:    test-session", output)
        self.assertIn("Created: 2026-07-05 10:30:15", output)
        self.assertIn("Task:    Do something useful.", output)
        self.assertIn("Total: 1 session", output)

    @mock.patch.object(ai_list_sessions, "_supports_color", return_value=False)
    @mock.patch("shutil.get_terminal_size", return_value=mock.Mock(columns=80))
    def test_unnamed_session(self, _mock_size, _mock_color):
        session = FakeSession(
            session_id="def456",
            session_name=None,
            create_time=datetime(2026, 7, 5, 10, 30, 15),
            task="Another task.",
        )
        output = ai_list_sessions.format_sessions([session])
        self.assertIn("Name:    (unnamed)", output)

    @mock.patch.object(ai_list_sessions, "_supports_color", return_value=False)
    @mock.patch("shutil.get_terminal_size", return_value=mock.Mock(columns=80))
    def test_session_separator_between_records(self, _mock_size, _mock_color):
        sessions = [
            FakeSession(
                session_id="abc123",
                session_name="first",
                create_time=datetime(2026, 7, 5, 10, 30, 15),
                task="First task.",
            ),
            FakeSession(
                session_id="def456",
                session_name="second",
                create_time=datetime(2026, 7, 5, 9, 15, 0),
                task="Second task.",
            ),
        ]
        output = ai_list_sessions.format_sessions(sessions)
        # There should be a line of dashes between the two session blocks.
        lines = output.split("\n")
        separator_count = sum(1 for line in lines if line.startswith("-") and set(line) == {"-"})
        self.assertGreaterEqual(separator_count, 1)
        self.assertIn("[1] abc123", output)
        self.assertIn("[2] def456", output)

    @mock.patch.object(ai_list_sessions, "_supports_color", return_value=False)
    @mock.patch("shutil.get_terminal_size", return_value=mock.Mock(columns=40))
    def test_long_task_wrapping(self, _mock_size, _mock_color):
        long_task = "A" * 100
        session = FakeSession(
            session_id="wrap123",
            session_name="wrap",
            create_time=datetime(2026, 7, 5, 10, 30, 15),
            task=long_task,
        )
        output = ai_list_sessions.format_sessions([session])
        lines = output.split("\n")
        task_lines = [line for line in lines if "Task:" in line or line.strip().startswith("A")]
        self.assertGreaterEqual(len(task_lines), 2)


class TestMainIntegration(unittest.TestCase):
    """Integration tests using a temporary SQLite database."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.db_conn = f"sqlite:///{self.db_path}"

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_main_lists_created_sessions_oldest_first(self, _mock_tty):
        manager = get_session_manager(self.db_conn)
        manager.create_session(
            SessionData(session_id="s1", task="Task one")
        )
        # Ensure s2 is created strictly after s1.
        import time
        time.sleep(0.01)
        manager.create_session(
            SessionData(session_id="s2", task="Task two")
        )
        with mock.patch("sys.argv", ["ai_list_sessions.py", self.db_conn, "--no-color"]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        self.assertIn("Sessions (Total: 2)", output)
        self.assertIn("s1", output)
        self.assertIn("s2", output)
        self.assertIn("Task one", output)
        self.assertIn("Task two", output)
        # Oldest session should appear before newest session.
        self.assertLess(output.index("s1"), output.index("s2"))

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_main_no_sessions(self, _mock_tty):
        with mock.patch("sys.argv", ["ai_list_sessions.py", self.db_conn, "--no-color"]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        self.assertIn("No sessions found.", output)


if __name__ == "__main__":
    unittest.main()
