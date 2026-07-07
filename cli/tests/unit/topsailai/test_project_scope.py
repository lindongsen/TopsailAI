#!/usr/bin/env python3
"""
Unit tests for project scope support in cli_topsailai.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai import project_scope
from cli_topsailai.colors import Colors


class MockCompletedProcess:
    """Minimal mock for subprocess.CompletedProcess."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestBuildProjectList(unittest.TestCase):
    """Tests for build_project_list."""

    def setUp(self):
        self.sample_sessions = [
            {
                "session_id": "s1",
                "session_name": "session one",
                "create_time": "2026-07-06T10:00:00",
                "task": "task one",
                "project_workspace": "/work/project-a",
                "pwd": "/work/project-a",
                "topsailai_home": "/home/user/.topsailai",
            },
            {
                "session_id": "s2",
                "session_name": "session two",
                "create_time": "2026-07-06T11:30:00",
                "task": "task two",
                "project_workspace": "/work/project-b",
                "pwd": "/work/project-b",
                "topsailai_home": "/home/user/.topsailai",
            },
        ]

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_parses_json(self, mock_run):
        mock_run.return_value = MockCompletedProcess(
            stdout=json.dumps(self.sample_sessions)
        )
        entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["no"], 1)
        self.assertEqual(entries[0]["session_id"], "s1")
        self.assertEqual(entries[0]["project_workspace"], "/work/project-a")
        self.assertEqual(entries[0]["create_time"], "07-06 10:00")
        self.assertEqual(entries[0]["task"], "task one")
        self.assertEqual(entries[1]["session_id"], "s2")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertIn("--json", call_args)
        self.assertIn("--has-project", call_args)
        self.assertIn("--sort", call_args)
        self.assertIn("asc", call_args)
        self.assertIn("--limit", call_args)
        self.assertIn("10", call_args)

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_keeps_oldest_first_order(self, mock_run):
        """If ai_list_sessions returns ascending order, oldest is row 1."""
        sessions = [
            {
                "session_id": "oldest",
                "session_name": "oldest session",
                "create_time": "2026-07-06T09:00:00",
                "task": "old task",
                "project_workspace": "/work/old",
                "pwd": "/work/old",
                "topsailai_home": "/home/user/.topsailai",
            },
            {
                "session_id": "newest",
                "session_name": "newest session",
                "create_time": "2026-07-06T12:00:00",
                "task": "new task",
                "project_workspace": "/work/new",
                "pwd": "/work/new",
                "topsailai_home": "/home/user/.topsailai",
            },
        ]
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps(sessions))
        entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["session_id"], "oldest")
        self.assertEqual(entries[1]["session_id"], "newest")
        self.assertEqual(entries[0]["no"], 1)
        self.assertEqual(entries[1]["no"], 2)
    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_passes_limit(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout="[]")
        project_scope.build_project_list(limit=5)

        call_args = mock_run.call_args[0][0]
        self.assertIn("--limit", call_args)
        self.assertIn("5", call_args)

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_empty_output(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout="")
        entries = project_scope.build_project_list(limit=10)
        self.assertEqual(entries, [])

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_subprocess_failure(self, mock_run):
        mock_run.return_value = MockCompletedProcess(
            stdout="", stderr="database locked", returncode=1
        )
        entries = project_scope.build_project_list(limit=10)
        self.assertEqual(entries, [])

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_invalid_json(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout="not-json")
        entries = project_scope.build_project_list(limit=10)
        self.assertEqual(entries, [])

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_non_list_json(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout='{"session_id": "s1"}')
        entries = project_scope.build_project_list(limit=10)
        self.assertEqual(entries, [])

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_subprocess_exception(self, mock_run):
        mock_run.side_effect = OSError("failed to execute")
        entries = project_scope.build_project_list(limit=10)
        self.assertEqual(entries, [])


class TestRunningStatusDetection(unittest.TestCase):
    """Tests for concurrent running-status enrichment."""

    def _write_stdout(self, task_dir, session_id, pid):
        """Create a session stdout file for testing."""
        path = os.path.join(task_dir, f"{session_id}.{pid}.session.stdout")
        with open(path, "w") as fh:
            fh.write("log line\n")
        return path

    def _make_session(self, session_id, create_time="2026-07-06T10:00:00"):
        return {
            "session_id": session_id,
            "session_name": f"name-{session_id}",
            "create_time": create_time,
            "task": "task",
            "project_workspace": "/work/project",
            "pwd": "/work/project",
            "topsailai_home": "/home/user/.topsailai",
        }

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    @patch("cli_topsailai.project_scope.os.kill")
    def test_marks_running_when_pid_alive(self, mock_kill, mock_home, mock_run):
        """A session with a live PID is marked Running."""
        session = self._make_session("s-alive")
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps([session]))
        mock_kill.side_effect = lambda pid, sig: None

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-alive", 1234)
            mock_home.return_value = tmp

            entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "Running")

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    @patch("cli_topsailai.project_scope.os.kill")
    def test_marks_idle_when_pid_dead(self, mock_kill, mock_home, mock_run):
        """A session whose PID no longer exists is marked Idle."""
        session = self._make_session("s-dead")
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps([session]))
        mock_kill.side_effect = ProcessLookupError("no such process")

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-dead", 5678)
            mock_home.return_value = tmp

            entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "Idle")

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    @patch("cli_topsailai.project_scope.os.kill")
    def test_marks_idle_when_no_stdout_file(self, mock_kill, mock_home, mock_run):
        """A session with no stdout file is marked Idle."""
        session = self._make_session("s-missing")
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps([session]))

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            mock_home.return_value = tmp

            entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "Idle")
        mock_kill.assert_not_called()

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    @patch("cli_topsailai.project_scope.os.kill")
    def test_marks_mixed_sessions_correctly(self, mock_kill, mock_home, mock_run):
        """Multiple sessions are checked concurrently with correct results."""
        sessions = [
            self._make_session("s-running", "2026-07-06T12:00:00"),
            self._make_session("s-idle", "2026-07-06T11:00:00"),
            self._make_session("s-no-file", "2026-07-06T10:00:00"),
        ]
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps(sessions))

        alive_pids = {1111}

        def fake_kill(pid, sig):
            if pid not in alive_pids:
                raise ProcessLookupError("dead")

        mock_kill.side_effect = fake_kill

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-running", 1111)
            self._write_stdout(task_dir, "s-idle", 2222)
            # s-no-file intentionally has no stdout file
            mock_home.return_value = tmp

            entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 3)
        by_id = {e["session_id"]: e["status"] for e in entries}
        self.assertEqual(by_id["s-running"], "Running")
        self.assertEqual(by_id["s-idle"], "Idle")
        self.assertEqual(by_id["s-no-file"], "Idle")

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    @patch("cli_topsailai.project_scope.os.kill")
    def test_uses_most_recent_stdout_file(self, mock_kill, mock_home, mock_run):
        """When multiple stdout files exist, the most recent PID is checked."""
        session = self._make_session("s-multi")
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps([session]))

        alive_pids = {9999}

        def fake_kill(pid, sig):
            if pid not in alive_pids:
                raise ProcessLookupError("dead")

        mock_kill.side_effect = fake_kill

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            old_path = self._write_stdout(task_dir, "s-multi", 1111)
            new_path = self._write_stdout(task_dir, "s-multi", 9999)
            # Ensure mtime ordering even on fast filesystems.
            os.utime(old_path, (1000, 1000))
            os.utime(new_path, (2000, 2000))
            mock_home.return_value = tmp

            entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "Running")


class TestPrintProjectTable(unittest.TestCase):
    """Tests for print_project_table."""

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_project_table_renders_entries(self, mock_stdout):
        entries = [
            {
                "no": 1,
                "session_id": "s1",
                "session_name": "session one",
                "project_workspace": "/work/project-a",
                "create_time": "07-06 10:00",
                "create_time_raw": "2026-07-06T10:00:00",
                "task": "task one",
                "status": "Running",
            }
        ]
        project_scope.print_project_table(entries)
        output = mock_stdout.getvalue()
        self.assertNotIn("Status", output)
        self.assertIn("Session ID", output)
        self.assertIn("Project Workspace", output)
        self.assertIn("s1", output)
        self.assertIn("/work/project-a", output)
        self.assertIn("07-06 10:00", output)
        self.assertIn("session one", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_project_table_empty(self, mock_stdout):
        project_scope.print_project_table([])
        output = mock_stdout.getvalue()
        self.assertIn("No sessions with project_workspace found", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_project_table_truncates_long_fields(self, mock_stdout):
        entries = [
            {
                "no": 1,
                "session_id": "s" * 50,
                "session_name": "n" * 50,
                "project_workspace": "/work/" + "p" * 50,
                "create_time": "07-06 10:00",
                "create_time_raw": "2026-07-06T10:00:00",
                "task": "task",
                "status": "Idle",
            }
        ]
        project_scope.print_project_table(entries)
        output = mock_stdout.getvalue()
        self.assertIn("...", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_running_row_is_green(self, mock_stdout):
        entries = [
            {
                "no": 1,
                "session_id": "s-running",
                "session_name": "running session",
                "project_workspace": "/work/running",
                "create_time": "07-06 10:00",
                "create_time_raw": "2026-07-06T10:00:00",
                "task": "task",
                "status": "Running",
            }
        ]
        project_scope.print_project_table(entries)
        output = mock_stdout.getvalue()
        self.assertIn(Colors.GREEN, output)
        self.assertIn(Colors.RESET, output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_idle_row_is_not_green(self, mock_stdout):
        entries = [
            {
                "no": 1,
                "session_id": "s-idle",
                "session_name": "idle session",
                "project_workspace": "/work/idle",
                "create_time": "07-06 10:00",
                "create_time_raw": "2026-07-06T10:00:00",
                "task": "task",
                "status": "Idle",
            }
        ]
        project_scope.print_project_table(entries)
        output = mock_stdout.getvalue()
        # The header contains no green; the idle row should not contain GREEN.
        # Split output into header and data portions by the separator line.
        lines = output.splitlines()
        data_lines = [line for line in lines if "s-idle" in line]
        self.assertEqual(len(data_lines), 1)
        self.assertNotIn(Colors.GREEN, data_lines[0])


class TestRefreshProjectList(unittest.TestCase):
    """Tests for refresh_project_list."""

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_refresh_project_list_returns_fresh_list(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout="[]")
        old_entries = [{"session_id": "old"}]
        new_entries = project_scope.refresh_project_list(old_entries, limit=10)
        self.assertEqual(new_entries, [])


if __name__ == "__main__":
    unittest.main()
