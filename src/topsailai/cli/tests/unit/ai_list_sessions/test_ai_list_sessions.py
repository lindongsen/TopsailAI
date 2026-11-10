#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for ai_list_sessions.py."""

import io
import os
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

# Ensure the cli package and src modules are importable.
CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(CLI_ROOT, "..", "src"))
sys.path.insert(0, CLI_ROOT)
sys.path.insert(0, SRC_ROOT)

import ai_list_sessions
import topsailai_session_info
from sqlalchemy import event
from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData


class FakeSession:
    """Minimal session-like object for formatting tests."""

    def __init__(
        self,
        session_id,
        session_name,
        create_time,
        task,
        project_workspace=None,
        pwd=None,
        topsailai_home=None,
        total_tokens=0,
        total_cached_tokens=0,
        total_completion_tokens=0,
        category="",
    ):
        self.session_id = session_id
        self.session_name = session_name
        self.create_time = create_time
        self.task = task
        self.project_workspace = project_workspace
        self.pwd = pwd
        self.topsailai_home = topsailai_home
        self.total_tokens = total_tokens
        self.total_cached_tokens = total_cached_tokens
        self.total_completion_tokens = total_completion_tokens
        self.category = category

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


class TestCacheHitRate(unittest.TestCase):
    """Tests for _cache_hit_rate helper."""

    def test_full_hit(self):
        self.assertEqual(ai_list_sessions._cache_hit_rate(100, 100), "100.0%")

    def test_partial_hit(self):
        self.assertEqual(ai_list_sessions._cache_hit_rate(50, 200), "25.0%")

    def test_no_hit(self):
        self.assertEqual(ai_list_sessions._cache_hit_rate(0, 200), "0.0%")

    def test_zero_total_returns_empty(self):
        self.assertEqual(ai_list_sessions._cache_hit_rate(0, 0), "")
        self.assertEqual(ai_list_sessions._cache_hit_rate(100, 0), "")


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
        self.assertIn("[1] abc123  2026-07-05T10:30:15", output)
        self.assertIn("Name:            test-session", output)
        self.assertIn("Task:            Do something useful.", output)
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
        self.assertIn("Name:            (unnamed)", output)

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
        self.assertIn("[1] abc123  2026-07-05T10:30:15", output)
        self.assertIn("[2] def456  2026-07-05T09:15:00", output)
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

    @mock.patch.object(ai_list_sessions, "_supports_color", return_value=False)
    @mock.patch("shutil.get_terminal_size", return_value=mock.Mock(columns=80))
    def test_extra_fields_displayed(self, _mock_size, _mock_color):
        session = FakeSession(
            session_id="extra001",
            session_name="extra-session",
            create_time=datetime(2026, 7, 5, 10, 30, 15),
            task="Extra task.",
            project_workspace="/workspace/project",
            pwd="/workspace/project/src",
            topsailai_home="/home/user/.topsailai",
            total_tokens=1234,
            total_cached_tokens=567,
            total_completion_tokens=56,
        )
        output = ai_list_sessions.format_sessions([session])
        self.assertIn("Project:         /workspace/project", output)
        self.assertIn("PWD:             /workspace/project/src", output)
        self.assertIn("Home:            /home/user/.topsailai", output)
        self.assertIn("Prompt Tokens:   1234", output)
        self.assertIn("Completion Tokens: 56", output)
        self.assertIn("Usage Tokens:    1290", output)
        self.assertIn("Cached Prompt Tokens: 567", output)
        self.assertIn("Cache Hit Rate:  45.9%", output)
        self.assertNotIn("Total Tokens:", output)

    @mock.patch.object(ai_list_sessions, "_supports_color", return_value=False)
    @mock.patch("shutil.get_terminal_size", return_value=mock.Mock(columns=80))
    def test_extra_fields_omitted_when_empty(self, _mock_size, _mock_color):
        session = FakeSession(
            session_id="noextra001",
            session_name="no-extra-session",
            create_time=datetime(2026, 7, 5, 10, 30, 15),
            task="No extra fields.",
        )
        output = ai_list_sessions.format_sessions([session])
        self.assertNotIn("Project:", output)
        self.assertNotIn("PWD:", output)
        self.assertNotIn("Home:", output)


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
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn, "--no-color"]):
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
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn, "--no-color"]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        self.assertIn("No sessions found.", output)


class TestJsonAndFilterFlags(unittest.TestCase):
    """Tests for --json, --has-project, --limit, and --sort flags."""

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
    def test_json_output_format(self, _mock_tty):
        manager = get_session_manager(self.db_conn)
        manager.create_session(
            SessionData(
                session_id="json-s1",
                session_name="json session",
                task="json task",
                project_workspace="/work/project-json",
                pwd="/work/project-json",
                topsailai_home="/home/user/.topsailai",
            )
        )
        with mock.patch(
            "sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn, "--json", "--no-color"]
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        data = json.loads(output)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["session_id"], "json-s1")
        self.assertEqual(data[0]["session_name"], "json session")
        self.assertEqual(data[0]["task"], "json task")
        self.assertEqual(data[0]["project_workspace"], "/work/project-json")
        self.assertEqual(data[0]["pwd"], "/work/project-json")
        self.assertEqual(data[0]["topsailai_home"], "/home/user/.topsailai")
        self.assertIn("create_time", data[0])
        self.assertNotIn("total_tokens", data[0])
        self.assertIn("total_prompt_tokens", data[0])
        self.assertIn("total_completion_tokens", data[0])
        self.assertIn("total_usage_tokens", data[0])
        self.assertIn("total_cached_tokens", data[0])
        self.assertIn("cache_hit_rate", data[0])
        self.assertEqual(data[0]["cache_hit_rate"], "")

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_has_project_filter(self, _mock_tty):
        manager = get_session_manager(self.db_conn)
        manager.create_session(
            SessionData(session_id="with-project", task="t1", project_workspace="/work/a")
        )
        manager.create_session(
            SessionData(session_id="without-project", task="t2")
        )
        with mock.patch(
            "sys.argv",
            ["ai_list_sessions.py", "--db-conn", self.db_conn, "--json", "--has-project", "--no-color"],
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        data = json.loads(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["session_id"], "with-project")

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_limit_sessions(self, _mock_tty):
        manager = get_session_manager(self.db_conn)
        for i in range(5):
            manager.create_session(
                SessionData(session_id=f"limit-{i}", task=f"task {i}")
            )
        with mock.patch(
            "sys.argv",
            ["ai_list_sessions.py", "--db-conn", self.db_conn, "--json", "--limit", "2", "--no-color"],
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        data = json.loads(output)
        self.assertEqual(len(data), 2)

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_sort_descending(self, _mock_tty):
        manager = get_session_manager(self.db_conn)
        manager.create_session(
            SessionData(session_id="older", task="older task")
        )
        import time
        time.sleep(0.01)
        manager.create_session(
            SessionData(session_id="newer", task="newer task")
        )
        with mock.patch(
            "sys.argv",
            [
                "ai_list_sessions.py",
                "--db-conn",
                self.db_conn,
                "--json",
                "--sort",
                "desc",
                "--no-color",
            ],
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        data = json.loads(output)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["session_id"], "newer")
        self.assertEqual(data[1]["session_id"], "older")

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_combined_flags_project_recent_asc(self, _mock_tty):
        manager = get_session_manager(self.db_conn)
        for i in range(5):
            manager.create_session(
                SessionData(
                    session_id=f"proj-{i}",
                    task=f"task {i}",
                    project_workspace=f"/work/proj-{i}",
                )
            )
            import time
            time.sleep(0.005)
        with mock.patch(
            "sys.argv",
            [
                "ai_list_sessions.py",
                "--db-conn",
                self.db_conn,
                "--json",
                "--has-project",
                "--limit",
                "3",
                "--sort",
                "asc",
                "--no-color",
            ],
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        data = json.loads(output)
        self.assertEqual(len(data), 3)
        # asc order: oldest first, newest last.
        self.assertEqual(data[0]["session_id"], "proj-0")
        self.assertEqual(data[2]["session_id"], "proj-2")

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_positional_session_ids(self, _mock_tty):
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="pos-s1", task="t1"))
        manager.create_session(SessionData(session_id="pos-s2", task="t2"))
        manager.create_session(SessionData(session_id="pos-s3", task="t3"))
        with mock.patch(
            "sys.argv",
            [
                "ai_list_sessions.py",
                "--db-conn",
                self.db_conn,
                "--json",
                "pos-s1",
                "pos-s3",
                "--no-color",
            ],
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()

        data = json.loads(output)
        self.assertEqual(len(data), 2)
        self.assertEqual({session["session_id"] for session in data}, {"pos-s1", "pos-s3"})

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_main_filters_by_since_until(self, _mock_tty):
        """--since and --until filter sessions by create_time."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(
            SessionData(session_id="early", task="early task")
        )
        import time
        time.sleep(0.2)
        cutoff = datetime.now()
        time.sleep(0.2)
        manager.create_session(
            SessionData(session_id="late", task="late task")
        )
        since = cutoff.strftime("%Y-%m-%dT%H:%M:%S.%f")
        until = (cutoff + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")
        with mock.patch(
            "sys.argv",
            [
                "ai_list_sessions.py",
                "--db-conn", self.db_conn,
                "--json",
                "--since", since,
                "--until", until,
                "--no-color",
            ],
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ai_list_sessions.main()
                output = mock_stdout.getvalue()
        data = json.loads(output)
        ids = {s["session_id"] for s in data}
        self.assertNotIn("early", ids)
        self.assertIn("late", ids)

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_category_filter_and_matched_total(self, _mock_tty):
        """Category filtering occurs before pagination and reports the match count."""
        manager = get_session_manager(self.db_conn)
        for session_id, category in (("agent-1", "agent"), ("chat-1", "chat"), ("agent-2", "agent")):
            manager.create_session(SessionData(session_id=session_id, task="task", category=category))
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                      "--category", "agent", "--offset", "1", "--limit", "1", "--no-color"]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
                text = output.getvalue()
        self.assertIn("agent-2", text)
        self.assertNotIn("chat-1", text)
        self.assertIn("Total: 1 session", text)
        self.assertIn("Matched Total: 2", text)

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_category_empty_pages_keep_matched_total(self, _mock_tty):
        """Filtered empty pages expose the pre-pagination matched total."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="agent-1", task="task", category="agent"))
        manager.create_session(SessionData(session_id="agent-2", task="task", category="agent"))

        scenarios = [
            (["--category", "missing"], "Matched Total: 0"),
            (["--category", "agent", "--offset", "99"], "Matched Total: 2"),
            (["--category", "agent", "--limit", "0"], "Matched Total: 2"),
        ]
        for options, expected in scenarios:
            with self.subTest(options=options):
                with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                              "--no-color", *options]):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                        ai_list_sessions.main()
                self.assertIn(expected, output.getvalue())

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_unfiltered_empty_page_keeps_legacy_output(self, _mock_tty):
        """An omitted category filter preserves the legacy empty output."""
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn, "--no-color"]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
        self.assertEqual(output.getvalue().strip(), "No sessions found.")

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_category_json_and_empty_filter(self, _mock_tty):
        """JSON exposes category and an empty value selects uncategorized rows."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
        manager.create_session(SessionData(session_id="empty", task="task", category=""))
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                      "--category", "", "--json", "--no-color"]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
                data = json.loads(output.getvalue())
        self.assertEqual([row["session_id"] for row in data], ["empty"])
        self.assertEqual(data[0]["category"], "")

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_invalid_category_is_rejected(self, _mock_tty):
        """Invalid category values fail instead of selecting uncategorized rows."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="empty", task="task", category=""))
        manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
        invalid_values = ["Agent", "agent,chat", "agent chat", "agent-1", "agent\n", "agent!"]
        for invalid_value in invalid_values:
            with self.subTest(value=invalid_value):
                with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                              "--category", invalid_value, "--json", "--no-color"]):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                        with self.assertRaises(SystemExit) as raised:
                            ai_list_sessions.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(output.getvalue(), "")

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_valid_category_values_are_accepted(self, _mock_tty):
        """Lowercase letters, digits, and underscores are accepted as one value."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="a", task="task", category="agent"))
        manager.create_session(SessionData(session_id="b", task="task", category="agent_2"))
        manager.create_session(SessionData(session_id="c", task="task", category="123"))
        for valid_value, expected in (("agent", ["a"]), ("agent_2", ["b"]), ("123", ["c"])):
            with self.subTest(value=valid_value):
                with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                              "--category", valid_value, "--json", "--no-color"]):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                        ai_list_sessions.main()
                        data = json.loads(output.getvalue())
                self.assertEqual([row["session_id"] for row in data], expected)

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_category_text_and_omitted_filter_ignore_environment(self, _mock_tty):
        """Text displays category while omitted filtering remains independent of environment."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
        manager.create_session(SessionData(session_id="empty", task="task", category=""))
        with mock.patch.dict(os.environ, {"TOPSAILAI_SESSION_CATEGORY": "agent"}, clear=False):
            with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn, "--no-color"]):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                    ai_list_sessions.main()
                    text = output.getvalue()
        self.assertIn("Category:", text)
        self.assertIn("agent", text)
        self.assertIn("empty", text)


    @mock.patch.object(ai_list_sessions, "_supports_color", return_value=False)
    @mock.patch("shutil.get_terminal_size", return_value=mock.Mock(columns=80))
    def test_list_format_missing_category_attribute_displays_none(self, _mock_size, _mock_color):
        """Legacy list session-like objects without category remain renderable."""
        class LegacySession:
            session_id = "legacy-list"
            session_name = None
            create_time = datetime(2026, 7, 5, 10, 30, 15)
            task = "legacy task"
            project_workspace = None
            pwd = None
            topsailai_home = None
            total_tokens = 0
            total_cached_tokens = 0
            total_completion_tokens = 0

        output = ai_list_sessions.format_sessions([LegacySession()])
        self.assertIn("legacy-list", output)
        self.assertIn("Category:", output)
        self.assertIn("(none)", output)


    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_repeated_category_is_rejected(self, _mock_tty):
        """A repeated category option fails instead of silently keeping the last."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
        manager.create_session(SessionData(session_id="chat", task="task", category="chat"))
        with mock.patch("sys.argv", [
            "ai_list_sessions.py", "--db-conn", self.db_conn, "--json",
            "--category", "agent", "--category", "chat", "--no-color",
        ]):
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as raised:
                    ai_list_sessions.main()
        self.assertEqual(raised.exception.code, 2)

    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_category_combined_with_project_filter(self, _mock_tty):
        """Category remains restrictive when combined with page-local project filtering."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(
            session_id="agent-project", task="task", category="agent",
            project_workspace="/work/project",
        ))
        manager.create_session(SessionData(
            session_id="agent-no-project", task="task", category="agent",
        ))
        manager.create_session(SessionData(
            session_id="chat-project", task="task", category="chat",
            project_workspace="/work/project",
        ))
        with mock.patch("sys.argv", [
            "ai_list_sessions.py", "--db-conn", self.db_conn, "--json",
            "--category", "agent", "--has-project", "--no-color",
        ]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
                data = json.loads(output.getvalue())
        assert [row["session_id"] for row in data] == ["agent-project"]
        assert all(row["category"] == "agent" for row in data)


    @mock.patch.object(sys.stdout, "isatty", return_value=False)
    def test_cli_list_and_detail_do_not_write_rows_schema_or_meta(self, _mock_tty):
        """Listing and detail reads preserve database, schema, file, and meta state."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(
            session_id="readonly-agent", task="task", category="agent",
            project_workspace="/work/project",
        ))
        manager.create_session(SessionData(
            session_id="readonly-chat", task="task", category="chat",
        ))
        home = Path(tempfile.mkdtemp())
        meta_dir = home / "workspace" / "task"
        meta_dir.mkdir(parents=True)
        meta_file = meta_dir / "readonly-agent.1.session.meta"
        meta_file.write_bytes(b"meta-before\n")

        def snapshot():
            import sqlite3
            with sqlite3.connect(self.db_path) as connection:
                rows = connection.execute(
                    "SELECT * FROM session ORDER BY session_id"
                ).fetchall()
                schema = connection.execute(
                    "PRAGMA table_info(session)"
                ).fetchall()
            return rows, schema, Path(self.db_path).read_bytes()

        def meta_snapshot():
            return {
                path.relative_to(home): path.read_bytes()
                for path in home.rglob("*")
                if path.is_file()
            }

        def meta_paths_snapshot():
            return sorted(path.relative_to(home) for path in home.rglob("*"))

        before = snapshot()
        before_meta = meta_snapshot()
        with mock.patch("sys.argv", [
            "ai_list_sessions.py", "--db-conn", self.db_conn,
            "--category", "agent", "--json", "--no-color",
        ]):
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                ai_list_sessions.main()

        with mock.patch("sys.stdout", new_callable=io.StringIO):
            assert topsailai_session_info.main([
                "readonly-agent", "--db-conn", self.db_conn,
                "--home", str(home), "--json",
            ]) == 0

        assert snapshot() == before
        assert meta_snapshot() == before_meta
        assert meta_paths_snapshot() == sorted({Path("workspace"), Path("workspace/task"), *before_meta})
        import shutil
        shutil.rmtree(home)


class TestExcludedCategories(unittest.TestCase):
    """Tests for the database-side --excluded-categories filter."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.db_conn = f"sqlite:///{self.db_path}"
        manager = get_session_manager(self.db_conn)
        for session_id, category in (
            ("driver-1", "agent_driver"),
            ("driver-2", "agent_driver"),
            ("agent-1", "agent"),
            ("chat-1", "chat"),
            ("plain-1", ""),
        ):
            manager.create_session(
                SessionData(session_id=session_id, task="task", category=category)
            )

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _run(self, options):
        """Run main() with *options* and return its stdout."""
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                     "--no-color", *options]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
                return output.getvalue()

    def test_parse_accepts_comma_separated_and_repeated_values(self):
        """Comma-separated and repeated options accumulate into one set."""
        parsed = ai_list_sessions._parse_excluded_categories(
            ["agent_driver,agent", "chat"]
        )
        self.assertEqual(parsed, {"agent_driver", "agent", "chat"})

    def test_parse_returns_empty_set_when_omitted(self):
        """An omitted option must not change the unfiltered query path."""
        self.assertEqual(ai_list_sessions._parse_excluded_categories(None), set())

    def test_parse_keeps_empty_value_as_uncategorized(self):
        """An empty value excludes uncategorized sessions instead of nothing."""
        self.assertEqual(ai_list_sessions._parse_excluded_categories([""]), {""})

    def test_parse_logs_invalid_name_and_excludes_uncategorized(self):
        """An invalid name is rejected instead of excluding uncategorized rows."""
        with self.assertLogs("topsailai.context.session_category", level="ERROR") as logs:
            with self.assertRaises(ValueError):
                ai_list_sessions._parse_excluded_categories(["Agent\n"])
        self.assertTrue(any("Agent\\n" in message for message in logs.output))

    def test_excluded_categories_are_removed_from_json(self):
        """Every listed category disappears from the JSON output."""
        data = json.loads(self._run(["--json", "--excluded-categories", "agent_driver,agent"]))
        self.assertEqual({row["session_id"] for row in data}, {"chat-1", "plain-1"})

    def test_repeated_option_excludes_every_listed_category(self):
        """A repeated option behaves like one comma-separated value."""
        data = json.loads(self._run([
            "--json", "--excluded-categories", "agent_driver", "--excluded-categories", "chat",
        ]))
        self.assertEqual({row["session_id"] for row in data}, {"agent-1", "plain-1"})

    def test_empty_value_excludes_uncategorized_sessions(self):
        """An empty value removes only the uncategorized rows."""
        data = json.loads(self._run(["--json", "--excluded-categories", ""]))
        self.assertEqual({row["session_id"] for row in data},
                         {"driver-1", "driver-2", "agent-1", "chat-1"})

    def test_pagination_applies_after_exclusion(self):
        """A limit must select a full page of surviving rows, not a short one."""
        data = json.loads(self._run([
            "--json", "--excluded-categories", "agent_driver", "--limit", "3",
        ]))
        self.assertEqual(len(data), 3)
        self.assertNotIn("agent_driver", {row["category"] for row in data})

    def test_offset_applies_after_exclusion(self):
        """Offset counts surviving rows, so no excluded row consumes a slot."""
        data = json.loads(self._run([
            "--json", "--excluded-categories", "agent_driver", "--offset", "1",
        ]))
        self.assertEqual({row["session_id"] for row in data}, {"chat-1", "plain-1"})

    def test_text_output_reports_matched_total_after_exclusion(self):
        """Text mode reports the pre-pagination count of surviving rows."""
        text = self._run(["--excluded-categories", "agent_driver", "--limit", "1"])
        self.assertIn("Total: 1 session", text)
        self.assertIn("Matched Total: 3", text)

    def test_exclusion_combines_with_category_inclusion(self):
        """Inclusion and exclusion compose: the inclusion filter still applies."""
        data = json.loads(self._run([
            "--json", "--category", "agent", "--excluded-categories", "agent_driver",
        ]))
        self.assertEqual([row["session_id"] for row in data], ["agent-1"])

    def test_omitted_exclusion_keeps_every_row(self):
        """Without the option the previous unfiltered output is unchanged."""
        data = json.loads(self._run(["--json"]))
        self.assertEqual(len(data), 5)

    def test_pagination_is_pushed_down_to_the_database(self):
        """The requested offset and limit reach the query instead of being rewritten."""
        manager = get_session_manager(self.db_conn)
        captured = {}

        original = manager.list_sessions

        def recording_list_sessions(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        with mock.patch.object(manager, "list_sessions", side_effect=recording_list_sessions):
            with mock.patch.object(ai_list_sessions, "get_session_manager", return_value=manager):
                self._run(["--json", "--excluded-categories", "agent_driver",
                           "--offset", "1", "--limit", "2"])

        self.assertEqual(captured["offset"], 1)
        self.assertEqual(captured["limit"], 2)
        self.assertEqual(captured["excluded_categories"], {"agent_driver"})

    def test_exclusion_predicate_reaches_the_sql_statement(self):
        """The exclusion is a SQL predicate, so no excluded row is ever read."""
        statements = []
        manager = get_session_manager(self.db_conn)
        engine = manager.storage.engine

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            with mock.patch.object(ai_list_sessions, "get_session_manager", return_value=manager):
                self._run(["--json", "--excluded-categories", "agent_driver", "--limit", "2"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        page_statements = [s for s in statements if "FROM session" in s and "LIMIT" in s.upper()]
        self.assertTrue(page_statements)
        self.assertIn("coalesce", page_statements[0].lower())
        self.assertIn("not in", page_statements[0].lower())


class TestIncludedCategories(unittest.TestCase):
    """Tests for the database-side --included-categories filter."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.db_conn = f"sqlite:///{self.db_path}"
        manager = get_session_manager(self.db_conn)
        for session_id, category in (
            ("driver-1", "agent_driver"),
            ("driver-2", "agent_driver"),
            ("agent-1", "agent"),
            ("chat-1", "chat"),
            ("plain-1", ""),
        ):
            manager.create_session(
                SessionData(session_id=session_id, task="task", category=category)
            )

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _run(self, options):
        """Run main() with *options* and return its stdout."""
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                     "--no-color", *options]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
                return output.getvalue()

    def test_parse_accepts_comma_separated_and_repeated_values(self):
        """Comma-separated and repeated options accumulate into one set."""
        parsed = ai_list_sessions._parse_included_categories(["agent,chat", "agent_driver"])
        self.assertEqual(parsed, {"agent", "chat", "agent_driver"})

    def test_parse_returns_empty_set_when_omitted(self):
        """An omitted option must not change the unfiltered query path."""
        self.assertEqual(ai_list_sessions._parse_included_categories(None), set())

    def test_parse_keeps_empty_value_as_uncategorized(self):
        """An empty value includes uncategorized sessions instead of nothing."""
        self.assertEqual(ai_list_sessions._parse_included_categories([""]), {""})

    def test_parse_rejects_invalid_name(self):
        """An invalid name is rejected instead of including uncategorized rows."""
        with self.assertLogs("topsailai.context.session_category", level="ERROR") as logs:
            with self.assertRaises(ValueError):
                ai_list_sessions._parse_included_categories(["Agent\n"])
        self.assertTrue(any("Agent\\n" in message for message in logs.output))

    def test_included_categories_keep_only_listed_rows(self):
        """Only the listed categories survive the filter."""
        data = json.loads(self._run(["--json", "--included-categories", "agent,chat"]))
        self.assertEqual({row["session_id"] for row in data}, {"agent-1", "chat-1"})

    def test_repeated_option_includes_every_listed_category(self):
        """A repeated option behaves like one comma-separated value."""
        data = json.loads(self._run([
            "--json", "--included-categories", "agent", "--included-categories", "chat",
        ]))
        self.assertEqual({row["session_id"] for row in data}, {"agent-1", "chat-1"})

    def test_empty_value_includes_uncategorized_sessions(self):
        """An empty value keeps only the uncategorized rows."""
        data = json.loads(self._run(["--json", "--included-categories", ""]))
        self.assertEqual({row["session_id"] for row in data}, {"plain-1"})

    def test_pagination_applies_after_inclusion(self):
        """A limit must select a full page of surviving rows, not a short one."""
        data = json.loads(self._run([
            "--json", "--included-categories", "agent,chat,", "--limit", "2",
        ]))
        self.assertEqual(len(data), 2)
        self.assertTrue({row["category"] for row in data} <= {"agent", "chat", ""})

    def test_text_output_reports_matched_total_after_inclusion(self):
        """Text mode reports the pre-pagination count of surviving rows."""
        text = self._run(["--included-categories", "agent,chat", "--limit", "1"])
        self.assertIn("Total: 1 session", text)
        self.assertIn("Matched Total: 2", text)

    def test_inclusion_combines_with_exclusion(self):
        """Inclusion and exclusion compose into one database predicate."""
        data = json.loads(self._run([
            "--json", "--included-categories", "agent,agent_driver",
            "--excluded-categories", "agent_driver",
        ]))
        self.assertEqual([row["session_id"] for row in data], ["agent-1"])

    def test_omitted_inclusion_keeps_every_row(self):
        """Without the option the previous unfiltered output is unchanged."""
        data = json.loads(self._run(["--json"]))
        self.assertEqual(len(data), 5)

    def test_inclusion_is_pushed_down_to_the_database(self):
        """The inclusion set reaches the query instead of being filtered in memory."""
        manager = get_session_manager(self.db_conn)
        captured = {}

        original = manager.list_sessions

        def recording_list_sessions(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        with mock.patch.object(manager, "list_sessions", side_effect=recording_list_sessions):
            with mock.patch.object(ai_list_sessions, "get_session_manager", return_value=manager):
                self._run(["--json", "--included-categories", "agent,chat",
                           "--offset", "1", "--limit", "1"])

        self.assertEqual(captured["offset"], 1)
        self.assertEqual(captured["limit"], 1)
        self.assertEqual(captured["included_categories"], {"agent", "chat"})

    def test_inclusion_predicate_reaches_the_sql_statement(self):
        """The inclusion is a SQL predicate, so no unlisted row is ever read."""
        statements = []
        manager = get_session_manager(self.db_conn)
        engine = manager.storage.engine

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            with mock.patch.object(ai_list_sessions, "get_session_manager", return_value=manager):
                self._run(["--json", "--included-categories", "agent", "--limit", "2"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        page_statements = [s for s in statements if "FROM session" in s and "LIMIT" in s.upper()]
        self.assertTrue(page_statements)
        self.assertIn("coalesce", page_statements[0].lower())
        self.assertIn(" in ", page_statements[0].lower())
        self.assertNotIn("not in", page_statements[0].lower())


class TestProjectAndTimeFilters(unittest.TestCase):
    """Tests for the database-side --has-project and --since/--until filters."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.db_conn = f"sqlite:///{self.db_path}"
        manager = get_session_manager(self.db_conn)
        rows = (
            ("proj-early", "/work/a", datetime(2026, 1, 1, 0, 0, 0)),
            ("proj-mid", "/work/b", datetime(2026, 1, 2, 0, 0, 0)),
            ("proj-late", "/work/c", datetime(2026, 1, 3, 0, 0, 0)),
            ("empty-ws", "", datetime(2026, 1, 4, 0, 0, 0)),
            ("blank-ws", "   ", datetime(2026, 1, 5, 0, 0, 0)),
            ("null-ws", None, datetime(2026, 1, 6, 0, 0, 0)),
        )
        for session_id, workspace, created in rows:
            data = SessionData(session_id=session_id, task="task", project_workspace=workspace)
            data.create_time = created
            manager.create_session(data)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _run(self, options):
        """Run main() with *options* and return its stdout."""
        with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                     "--no-color", *options]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
                return output.getvalue()

    def test_has_project_keeps_only_rows_with_a_workspace(self):
        """The project filter drops NULL and empty workspaces."""
        data = json.loads(self._run(["--json", "--has-project"]))
        self.assertEqual({row["session_id"] for row in data},
                         {"proj-early", "proj-mid", "proj-late", "blank-ws"})

    def test_has_project_limit_returns_a_full_page(self):
        """A limit must select a full page of rows that have a workspace."""
        data = json.loads(self._run(["--json", "--has-project", "--limit", "2"]))
        self.assertEqual(len(data), 2)
        for row in data:
            self.assertTrue(row["project_workspace"])

    def test_has_project_reports_matched_total(self):
        """Text mode counts the filtered rows instead of the whole table."""
        text = self._run(["--has-project", "--limit", "1"])
        self.assertIn("Total: 1 session", text)
        self.assertIn("Matched Total: 4", text)

    def test_since_keeps_rows_at_or_after_the_bound(self):
        """since is an inclusive lower bound on create_time."""
        data = json.loads(self._run(["--json", "--since", "2026-01-03T00:00:00"]))
        self.assertEqual({row["session_id"] for row in data},
                         {"proj-late", "empty-ws", "blank-ws", "null-ws"})

    def test_until_keeps_rows_at_or_before_the_bound(self):
        """until is an inclusive upper bound on create_time."""
        data = json.loads(self._run(["--json", "--until", "2026-01-02T00:00:00"]))
        self.assertEqual({row["session_id"] for row in data}, {"proj-early", "proj-mid"})

    def test_time_window_limit_returns_a_full_page(self):
        """A limit must select a full page of rows inside the window."""
        data = json.loads(self._run([
            "--json", "--since", "2026-01-02T00:00:00", "--limit", "2",
        ]))
        self.assertEqual(len(data), 2)

    def test_time_window_reports_matched_total(self):
        """Text mode counts the rows inside the window."""
        text = self._run(["--since", "2026-01-02T00:00:00", "--limit", "1"])
        self.assertIn("Total: 1 session", text)
        self.assertIn("Matched Total: 5", text)

    def test_window_later_than_every_row_returns_nothing(self):
        """A window past every row selects no row instead of a short page."""
        data = json.loads(self._run(["--json", "--since", "2030-01-01T00:00:00"]))
        self.assertEqual(data, [])

    def test_project_and_time_filters_combine(self):
        """Both filters compose into one query."""
        data = json.loads(self._run([
            "--json", "--has-project", "--since", "2026-01-02T00:00:00",
            "--until", "2026-01-03T00:00:00",
        ]))
        self.assertEqual({row["session_id"] for row in data}, {"proj-mid", "proj-late"})

    def test_filters_are_pushed_down_to_the_database(self):
        """Every selection value reaches the query instead of being applied later."""
        manager = get_session_manager(self.db_conn)
        captured = {}

        original = manager.list_sessions

        def recording_list_sessions(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        with mock.patch.object(manager, "list_sessions", side_effect=recording_list_sessions):
            with mock.patch.object(ai_list_sessions, "get_session_manager", return_value=manager):
                self._run([
                    "--json", "--has-project", "--since", "2026-01-02T00:00:00",
                    "--until", "2026-01-04T00:00:00", "--offset", "1", "--limit", "2",
                ])

        self.assertTrue(captured["has_project"])
        self.assertEqual(captured["since"], datetime(2026, 1, 2, 0, 0, 0))
        self.assertEqual(captured["until"], datetime(2026, 1, 4, 0, 0, 0))
        self.assertEqual(captured["offset"], 1)
        self.assertEqual(captured["limit"], 2)

    def test_project_and_time_predicates_reach_the_sql_statement(self):
        """The predicates are SQL-side, so no filtered row is ever read."""
        statements = []
        manager = get_session_manager(self.db_conn)
        engine = manager.storage.engine

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            with mock.patch.object(ai_list_sessions, "get_session_manager", return_value=manager):
                self._run([
                    "--json", "--has-project", "--since", "2026-01-02T00:00:00",
                    "--until", "2026-01-04T00:00:00", "--limit", "2",
                ])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        page_statements = [s for s in statements if "FROM session" in s and "LIMIT" in s.upper()]
        self.assertTrue(page_statements)
        lowered = page_statements[0].lower()
        self.assertIn("project_workspace !=", lowered)
        self.assertIn("create_time >=", lowered)
        self.assertIn("create_time <=", lowered)


if __name__ == "__main__":
    unittest.main()
