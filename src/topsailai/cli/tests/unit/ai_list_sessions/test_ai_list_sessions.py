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
    def test_invalid_category_logs_error_and_selects_empty(self, _mock_tty):
        """Invalid category values log the original value and select empty rows."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="empty", task="task", category=""))
        manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
        with self.assertLogs("topsailai.context.session_category", level="ERROR") as logs:
            with mock.patch("sys.argv", ["ai_list_sessions.py", "--db-conn", self.db_conn,
                                          "--category", "Agent\n", "--json", "--no-color"]):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                    ai_list_sessions.main()
                    data = json.loads(output.getvalue())
        self.assertTrue(any("Agent\\n" in message for message in logs.output))
        self.assertEqual([row["session_id"] for row in data], ["empty"])

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
    def test_repeated_category_uses_last_value(self, _mock_tty):
        """Argparse uses the last repeated category value."""
        manager = get_session_manager(self.db_conn)
        manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
        manager.create_session(SessionData(session_id="chat", task="task", category="chat"))
        with mock.patch("sys.argv", [
            "ai_list_sessions.py", "--db-conn", self.db_conn, "--json",
            "--category", "agent", "--category", "chat", "--no-color",
        ]):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                ai_list_sessions.main()
                data = json.loads(output.getvalue())
        assert [row["session_id"] for row in data] == ["chat"]
        assert [row["category"] for row in data] == ["chat"]

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


if __name__ == "__main__":
    unittest.main()
