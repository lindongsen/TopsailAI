#!/usr/bin/env python3
"""
Unit tests for project scope support in cli_topsailai.
"""

import io
import json
import os
import re
import shlex
from types import SimpleNamespace
import sys
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import cli_topsailai.state as cli_state
from cli_topsailai import core, project_scope
from cli_topsailai.colors import Colors
from cli_topsailai.core import prompt_selection
from cli_topsailai.process_liveness import ProcessState, is_pid_alive, pid_state

class MockCompletedProcess:
    """Minimal mock for subprocess.CompletedProcess."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestBuildProjectList(unittest.TestCase):
    """Tests for build_project_list."""

    def setUp(self):
        # ai_list_sessions --sort desc returns newest-first; build_project_list
        # reverses the list so the oldest entry is displayed at the top.
        self.sample_sessions = [
            {
                "session_id": "s2",
                "session_name": "session two",
                "create_time": "2026-07-06T11:30:00",
                "task": "task two",
                "project_workspace": "/work/project-b",
                "pwd": "/work/project-b",
                "topsailai_home": "/home/user/.topsailai",
            },
            {
                "session_id": "s1",
                "session_name": "session one",
                "create_time": "2026-07-06T10:00:00",
                "task": "task one",
                "project_workspace": "/work/project-a",
                "pwd": "/work/project-a",
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
        self.assertEqual(entries[0]["modified_time"], "07-06 10:00")
        self.assertEqual(entries[0]["modified_time_raw"], "2026-07-06T10:00:00")
        self.assertEqual(entries[0]["task"], "task one")
        self.assertEqual(entries[1]["session_id"], "s2")

        mock_run.assert_called_once_with(
            [
                "topsailai_list_sessions",
                "--json",
                "--has-project",
                "--sort",
                "desc",
                "--limit",
                "10",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("cli_topsailai.project_scope._resolve_session_mtime")
    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_keeps_oldest_first_order(self, mock_run, mock_mtime):
        """Sessions are sorted by stdout mtime ascending (oldest on top)."""
        sessions = [
            {
                "session_id": "newest",
                "session_name": "newest session",
                "create_time": "2026-07-06T12:00:00",
                "task": "new task",
                "project_workspace": "/work/new",
                "pwd": "/work/new",
                "topsailai_home": "/home/user/.topsailai",
            },
            {
                "session_id": "oldest",
                "session_name": "oldest session",
                "create_time": "2026-07-06T09:00:00",
                "task": "old task",
                "project_workspace": "/work/old",
                "pwd": "/work/old",
                "topsailai_home": "/home/user/.topsailai",
            },
        ]
        # Even though create_time says otherwise, stdout mtime decides order.
        mock_mtime.side_effect = lambda _task_dir, session_id, index=None: {
            "newest": 1751454000.0,  # 2026-07-06 11:00:00
            "oldest": 1751446800.0,  # 2026-07-06 09:00:00
        }.get(session_id)
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
    def test_build_project_list_filters_by_session_without_limit(self, mock_run):
        """A direct session lookup passes its ID and omits the list limit."""
        mock_run.return_value = MockCompletedProcess(stdout="[]")
        project_scope.build_project_list(limit=None, session_id="session-a")

        call_args = mock_run.call_args[0][0]
        self.assertIn("session-a", call_args)
        self.assertNotIn("--limit", call_args)

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
    def test_marks_running_when_pid_alive(self, mock_home, mock_run):
        """A session with a live PID is marked Running."""
        session = self._make_session("s-alive")
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps([session]))

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-alive", os.getpid())
            mock_home.return_value = tmp

            entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "Running")

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_marks_idle_when_pid_dead(self, mock_home, mock_run):
        """A session whose PID no longer exists is marked Idle."""
        session = self._make_session("s-dead")
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps([session]))

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-dead", _absent_pid())
            mock_home.return_value = tmp

            entries = project_scope.build_project_list(limit=10)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "Idle")

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_marks_idle_when_no_stdout_file(self, mock_home, mock_run):
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

    @patch("cli_topsailai.project_scope.subprocess.run")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_marks_mixed_sessions_correctly(self, mock_home, mock_run):
        """Multiple sessions are checked concurrently with correct results."""
        sessions = [
            self._make_session("s-running", "2026-07-06T12:00:00"),
            self._make_session("s-idle", "2026-07-06T11:00:00"),
            self._make_session("s-no-file", "2026-07-06T10:00:00"),
        ]
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps(sessions))

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-running", os.getpid())
            self._write_stdout(task_dir, "s-idle", _absent_pid())
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
    def test_uses_most_recent_stdout_file(self, mock_home, mock_run):
        """When multiple stdout files exist, the most recent live PID wins."""
        session = self._make_session("s-multi")
        mock_run.return_value = MockCompletedProcess(stdout=json.dumps([session]))

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            old_path = self._write_stdout(task_dir, "s-multi", _absent_pid())
            new_path = self._write_stdout(task_dir, "s-multi", os.getpid())
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
                "modified_time": "07-06 10:00",
                "modified_time_raw": "2026-07-06T10:00:00",
                "task": "task one",
                "status": "Running",
            }
        ]
        project_scope.print_project_table(entries)
        output = mock_stdout.getvalue()
        self.assertNotIn("Status", output)
        self.assertIn("Session ID", output)
        self.assertIn("Project Workspace", output)
        self.assertIn("Modified", output)
        self.assertIn("s1", output)
        self.assertIn("/work/project-a", output)
        self.assertIn("07-06 10:00", output)
        self.assertIn("session one", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_project_table_column_order(self, mock_stdout):
        """Project Workspace is last while Session Name follows No."""
        entries = [
            {
                "no": 1,
                "session_id": "session-id",
                "session_name": "session-name",
                "project_workspace": "/work/project-a",
                "modified_time": "07-06 10:00",
                "status": "Idle",
            }
        ]

        project_scope.print_project_table(entries)
        header, _, row = mock_stdout.getvalue().splitlines()[:3]
        ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
        header_columns = [
            column.strip() for column in ansi_escape.sub("", header).split("|")
        ]
        row_columns = [
            column.strip() for column in ansi_escape.sub("", row).split("|")
        ]

        self.assertEqual(header_columns, [
            "No", "Session Name", "Session ID", "Modified", "Project Workspace"
        ])
        self.assertEqual(row_columns, [
            "1", "session-name", "session-id", "07-06 10:00", "/work/project-a"
        ])

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_print_project_table_empty(self, mock_stdout):
        project_scope.print_project_table([])
        output = mock_stdout.getvalue()
        self.assertIn("No sessions with project_workspace found", output)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_project_table_matches_workspace_text_column_formatting(self, mock_stdout):
        """Name and workspace match workspace-scope widths and truncation."""
        entries = [
            {
                "no": 1,
                "session_id": "session-id",
                "session_name": "session-name-prefix-中文-tail",
                "project_workspace": "/discarded/中文/path/project-tail",
                "modified_time": "07-06 10:00",
                "status": "Idle",
            }
        ]

        project_scope.print_project_table(entries)
        header, _, row = mock_stdout.getvalue().splitlines()[:3]
        ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

        def display_width(value):
            return sum(
                2 if unicodedata.east_asian_width(character) in ("F", "W") else 1
                for character in value
                if not unicodedata.combining(character)
            )

        header_columns = ansi_escape.sub("", header).split("|")
        row_columns = ansi_escape.sub("", row).split("|")
        self.assertEqual(display_width(header_columns[1]), 25)
        self.assertEqual(display_width(row_columns[1]), 25)
        self.assertEqual(display_width(header_columns[-1]), 26)
        self.assertEqual(display_width(row_columns[-1]), 26)
        self.assertIn("session-name-prefix", row_columns[1])
        self.assertNotIn("tail", row_columns[1])
        self.assertIn("...", row_columns[1])
        self.assertNotIn("/discarded", row_columns[-1])
        self.assertIn("path/project-tail", row_columns[-1])
        self.assertIn("...", row_columns[-1])

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_running_row_is_green(self, mock_stdout):
        entries = [
            {
                "no": 1,
                "session_id": "s-running",
                "session_name": "running session",
                "project_workspace": "/work/running",
                "modified_time": "07-06 10:00",
                "modified_time_raw": "2026-07-06T10:00:00",
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
                "modified_time": "07-06 10:00",
                "modified_time_raw": "2026-07-06T10:00:00",
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


class TestResolveAgentFolder(unittest.TestCase):
    """Tests for resolve_agent_folder."""

    def _make_entries(self):
        return [
            {"no": 1, "project_workspace": "/work/project-a"},
            {"no": 2, "project_workspace": "/work/project-b"},
        ]

    def test_resolve_numeric_argument(self):
        entries = self._make_entries()
        folder = project_scope.resolve_agent_folder("2", entries)
        self.assertEqual(folder, "/work/project-b")

    def test_resolve_numeric_with_whitespace(self):
        entries = self._make_entries()
        folder = project_scope.resolve_agent_folder("  1  ", entries)
        self.assertEqual(folder, "/work/project-a")

    def test_resolve_direct_folder_path(self):
        entries = self._make_entries()
        folder = project_scope.resolve_agent_folder("/custom/folder", entries)
        self.assertEqual(folder, "/custom/folder")

    def test_resolve_invalid_number_too_large(self):
        entries = self._make_entries()
        folder = project_scope.resolve_agent_folder("5", entries)
        self.assertIsNone(folder)

    def test_resolve_invalid_number_zero(self):
        entries = self._make_entries()
        folder = project_scope.resolve_agent_folder("0", entries)
        self.assertIsNone(folder)

    def test_resolve_empty_entries_numeric(self):
        folder = project_scope.resolve_agent_folder("1", [])
        self.assertIsNone(folder)

    @patch("cli_topsailai.project_scope.load_project_workspace_lookup")
    def test_resolve_workspace_log_entry_by_session_id(self, mock_lookup):
        mock_lookup.return_value = {"session-1": "/work/from-history"}
        entries = [
            {
                "no": 1,
                "session_id": "session-1",
                "filename": "session-1.1234.session.stdout",
            }
        ]
        folder = project_scope.resolve_agent_folder("1", entries)
        self.assertEqual(folder, "/work/from-history")
        mock_lookup.assert_called_once()

    @patch("cli_topsailai.project_scope.load_project_workspace_lookup")
    def test_resolve_workspace_log_entry_without_project_workspace(self, mock_lookup):
        mock_lookup.return_value = {}
        entries = [
            {
                "no": 1,
                "session_id": "session-1",
                "filename": "session-1.1234.session.stdout",
            }
        ]
        folder = project_scope.resolve_agent_folder("1", entries)
        self.assertIsNone(folder)

    def test_resolve_workspace_log_entry_with_project_workspace(self):
        entries = [
            {
                "no": 1,
                "session_id": "session-1",
                "project_workspace": "/work/direct",
            }
        ]
        folder = project_scope.resolve_agent_folder("1", entries)
        self.assertEqual(folder, "/work/direct")

    @patch("cli_topsailai.project_scope.load_project_workspace_lookup")
    def test_resolve_temp_session_returns_none(self, mock_lookup):
        entries = [
            {
                "no": 1,
                "session_id": "(temp)",
                "filename": "topsailai.1234.session.stdout",
            }
        ]
        folder = project_scope.resolve_agent_folder("1", entries)
        self.assertIsNone(folder)
        mock_lookup.assert_not_called()


class FakeLaunchChild:
    """Finite child double for compatibility-adapter launch tests."""

    def __init__(self, returncode=0):
        self.returncode = returncode
        self.calls = []

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        return self.returncode

    def poll(self):
        self.calls.append(("poll", None))
        return self.returncode

    def terminate(self):
        self.calls.append(("terminate", None))

    def kill(self):
        self.calls.append(("kill", None))


class TestLaunchAgentInFolder(unittest.TestCase):
    """Tests for the compatibility launch adapter."""

    def _launch(self, folder="/tmp", mode="raw", returncode=0):
        child = FakeLaunchChild(returncode)
        calls = []

        def spawn(argv, **kwargs):
            calls.append((argv, kwargs))
            return child

        with patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=({}, set())), \
             patch("cli_topsailai.agent_launch._session_id", return_value="fixed-session"):
            result = project_scope.launch_agent_in_folder(folder, agent_mode=mode, spawn=spawn)
        return result, child, calls

    def test_launches_agent_through_injected_boundary(self):
        result, child, calls = self._launch()
        self.assertEqual(result, None)
        self.assertEqual(calls[0][0], ["topsailai_launch_agent", "--subprocess", "--session-id", "fixed-session"])
        self.assertEqual(calls[0][1]["cwd"], "/tmp")
        self.assertEqual(calls[0][1]["env"]["TOPSAILAI_PWD"], "/tmp")
        self.assertEqual(child.calls, [("wait", None)])

    def test_delegation_forwards_folder_mode_and_spawn(self):
        child = FakeLaunchChild()
        spawn = lambda *args, **kwargs: child
        with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=17) as launch:
            project_scope.launch_agent_in_folder("relative-project", agent_mode="raw", spawn=spawn)
        launch.assert_called_once_with(
            os.path.abspath("relative-project"), mode="raw", background=False, spawn=spawn
        )

    def test_restores_cwd_and_environment_after_launch(self):
        old_cwd = os.getcwd()
        old_values = {key: os.environ.get(key) for key in ("PWD", "TOPSAILAI_PWD", "TOPSAILAI_SESSION_ID")}
        self._launch()
        self.assertEqual(os.getcwd(), old_cwd)
        for key, value in old_values.items():
            self.assertEqual(os.environ.get(key), value)

    def test_restores_state_when_model_preparation_fails(self):
        old_cwd = os.getcwd()
        with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=RuntimeError("bad model")):
            project_scope.launch_agent_in_folder("/tmp", agent_mode="raw", spawn=lambda *a, **k: self.fail("spawned"))
        self.assertEqual(os.getcwd(), old_cwd)

    def test_relative_folder_is_absolute_in_child(self):
        _, _, calls = self._launch(folder=".")
        self.assertEqual(calls[0][1]["cwd"], os.path.abspath("."))

    def test_stale_identity_is_replaced_during_launch(self):
        os.environ["TOPSAILAI_SESSION_ID"] = "stale-session-id"
        try:
            _, _, calls = self._launch()
            self.assertEqual(calls[0][1]["env"]["TOPSAILAI_SESSION_ID"], "fixed-session")
            self.assertEqual(os.environ["TOPSAILAI_SESSION_ID"], "stale-session-id")
        finally:
            os.environ.pop("TOPSAILAI_SESSION_ID", None)


class TestLaunchAgentInFolderWithMode(unittest.TestCase):
    """Tests for terminal-mode compatibility launches."""

    def _launch(self, mode):
        child = FakeLaunchChild()
        calls = []
        def spawn(argv, **kwargs):
            calls.append((argv, kwargs))
            return child
        with patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=({}, set())), \
             patch("cli_topsailai.agent_launch._session_id", return_value="fixed-session"):
            project_scope.launch_agent_in_folder("/tmp", agent_mode=mode, spawn=spawn)
        return child, calls

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    def test_default_dtach_falls_back_to_raw_when_unavailable(self, _which):
        child, calls = self._launch("dtach")
        self.assertEqual(calls[0][0], "topsailai_launch_agent --subprocess --session-id fixed-session")
        self.assertEqual(child.calls, [("wait", None)])

    @patch("cli_topsailai.project_scope.shutil.which", return_value="/usr/bin/dtach")
    @patch("cli_topsailai.project_scope._build_dtach_socket_path", return_value="/tmp/fixed.dtach")
    def test_default_dtach_uses_dtach_when_available(self, _socket, _which):
        _, calls = self._launch("dtach")
        self.assertEqual(calls[0][0], "dtach -A /tmp/fixed.dtach topsailai_launch_agent --subprocess --session-id fixed-session")

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    def test_raw_mode_invokes_command_directly(self, _which):
        _, calls = self._launch("raw")
        self.assertEqual(calls[0][0], ["topsailai_launch_agent", "--subprocess", "--session-id", "fixed-session"])

    @patch("cli_topsailai.project_scope.shutil.which", return_value="/usr/bin/tmux")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option", return_value=True)
    @patch("cli_topsailai.project_scope._generate_agent_session_name", return_value="fixed-tmux")
    def test_tmux_mode_wraps_command(self, _name, _supports, _which):
        deterministic_environment = {
            "HOME": "/home/test",
            "PATH": "/bin",
            "PWD": "/tmp",
            "SHELL": "/bin/sh",
            "USER": "tester",
            "TOPSAILAI_SESSION_ID": "fixed-session",
        }
        isolated_os = SimpleNamespace(environ=deterministic_environment, path=os.path)
        child, calls = None, None
        with patch("cli_topsailai.project_scope.os", isolated_os):
            child, calls = self._launch("tmux")
        self.assertEqual(
            calls[0][0],
            "tmux new-session -e HOME=/home/test -e PATH=/bin -e PWD=/tmp "
            "-e SHELL=/bin/sh -e TOPSAILAI_SESSION_ID=fixed-session -e USER=tester "
            "-s fixed-tmux topsailai_launch_agent --subprocess "
            "--session-id fixed-session",
        )
        self.assertEqual(child.calls, [("wait", None)])

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    def test_tmux_without_tmux_fails_before_spawn(self, _which):
        def fail_spawn(*args, **kwargs):
            raise AssertionError("consumer-local fail-fast guard: real spawn attempted")
        with patch("cli_topsailai.agent_launch._apply_selected_model_environment", return_value=({}, set())):
            result = project_scope.launch_agent_in_folder("/tmp", agent_mode="tmux", spawn=fail_spawn)
        self.assertIsNone(result)

class TestBuildDtachSocketPath(unittest.TestCase):
    """Tests for _build_dtach_socket_path."""

    @patch("cli_topsailai.project_scope.os.makedirs")
    @patch("cli_topsailai.project_scope.get_topsailai_home")
    @patch("cli_topsailai.project_scope.datetime")
    def test_creates_task_dir_and_timestamped_socket(
        self, mock_dt, mock_home, mock_makedirs
    ):
        mock_home.return_value = "/home/user/.topsailai"
        mock_dt.now.return_value.strftime.return_value = "20260707T221748.169974"
        path = project_scope._build_dtach_socket_path()
        self.assertEqual(
            path,
            "/home/user/.topsailai/workspace/task/20260707T221748.169974.dtach",
        )
        mock_makedirs.assert_called_once_with(
            "/home/user/.topsailai/workspace/task", exist_ok=True
        )


class TestWrapCommandForAgentMode(unittest.TestCase):
    """Tests for _wrap_command_for_agent_mode."""

    def test_raw_mode_returns_command_unchanged(self):
        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent", "raw"
        )
        self.assertEqual(result, "topsailai_launch_agent")

    @patch("cli_topsailai.project_scope.shutil.which")
    def test_dtach_mode_without_dtach_falls_back_to_raw(self, mock_which):
        mock_which.return_value = None
        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent", "dtach"
        )
        self.assertEqual(result, "topsailai_launch_agent")
        mock_which.assert_called_once_with("dtach")

    @patch("cli_topsailai.project_scope._build_dtach_socket_path")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_dtach_mode_wraps_with_dtach(
        self, mock_which, mock_build_socket
    ):
        mock_which.return_value = "/usr/bin/dtach"
        mock_build_socket.return_value = "/home/user/.topsailai/workspace/task/20260707T221748.169974.dtach"
        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent", "dtach"
        )
        expected = (
            "dtach -A "
            + shlex.quote("/home/user/.topsailai/workspace/task/20260707T221748.169974.dtach")
            + " topsailai_launch_agent"
        )
        self.assertEqual(result, expected)

    @patch("cli_topsailai.project_scope._build_dtach_socket_path")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_dtach_mode_quotes_socket_path_with_spaces(
        self, mock_which, mock_build_socket
    ):
        mock_which.return_value = "/usr/bin/dtach"
        mock_build_socket.return_value = "/home/user/weird path/task/20260707T221748.169974.dtach"
        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent", "dtach"
        )
        self.assertTrue(result.startswith("dtach -A "))
        self.assertIn(
            shlex.quote("/home/user/weird path/task/20260707T221748.169974.dtach"),
            result,
        )
        self.assertIn(" topsailai_launch_agent", result)

    @patch.dict(
        os.environ,
        {
            "TOPSAILAI_SESSION_ID": "s-123",
            "TOPSAILAI_PWD": "/work/project-a",
            "PWD": "/work/project-a",
            "PATH": "/usr/local/bin:/usr/bin",
            "HOME": "/home/user",
            "SHELL": "/bin/bash",
            "USER": "user",
        },
        clear=True,
    )
    @patch("cli_topsailai.project_scope._generate_agent_session_name")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_tmux_mode_wraps_with_tmux(
        self, mock_which, mock_supports_environment_option, mock_generate_name
    ):
        mock_which.return_value = "/usr/bin/tmux"
        mock_supports_environment_option.return_value = True
        mock_generate_name.return_value = "topsailai-20260707T221748.169974"
        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent", "tmux"
        )
        self.assertTrue(result.startswith("tmux new-session"))
        self.assertIn("-e TOPSAILAI_SESSION_ID=s-123", result)
        self.assertIn("-e TOPSAILAI_PWD=/work/project-a", result)
        self.assertIn("-e PWD=/work/project-a", result)
        self.assertIn("-e PATH=/usr/local/bin:/usr/bin", result)
        self.assertIn("-e HOME=/home/user", result)
        self.assertIn("-e SHELL=/bin/bash", result)
        self.assertIn("-e USER=user", result)
        self.assertIn(
            " -s " + shlex.quote("topsailai-20260707T221748.169974") + " ",
            result,
        )
        self.assertIn(" topsailai_launch_agent", result)

    @patch.dict(
        os.environ,
        {"OPENAI_MODEL": "gpt-selected"},
        clear=True,
    )
    @patch("cli_topsailai.project_scope._generate_agent_session_name")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_tmux_forwards_selected_model_when_value_is_unchanged(
        self, mock_which, mock_supports_environment_option, mock_generate_name
    ):
        """Selected model keys are explicit even when their values did not change."""
        mock_which.return_value = "/usr/bin/tmux"
        mock_supports_environment_option.return_value = True
        mock_generate_name.return_value = "topsailai-model-test"

        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent",
            "tmux",
            {"OPENAI_MODEL"},
        )

        self.assertIn("-e OPENAI_MODEL=gpt-selected", result)

    @patch("cli_topsailai.project_scope.shutil.which")
    def test_tmux_mode_without_tmux_raises_runtime_error(self, mock_which):
        mock_which.return_value = None
        with self.assertRaises(RuntimeError) as ctx:
            project_scope._wrap_command_for_agent_mode(
                "topsailai_launch_agent", "tmux"
            )
        self.assertIn("tmux is not installed", str(ctx.exception))

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_tmux_environment_option_supports_version_3_2(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout="tmux 3.2")

        supported = project_scope._tmux_supports_environment_option("/usr/bin/tmux")

        self.assertTrue(supported)
        mock_run.assert_called_once_with(
            ["/usr/bin/tmux", "-V"],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_tmux_environment_option_rejects_legacy_version(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout="tmux 3.0a")

        supported = project_scope._tmux_supports_environment_option("/usr/bin/tmux")

        self.assertFalse(supported)

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_tmux_environment_option_supports_suffixed_version(self, mock_run):
        mock_run.return_value = MockCompletedProcess(stdout="tmux 3.5a")

        supported = project_scope._tmux_supports_environment_option("/usr/bin/tmux")

        self.assertTrue(supported)

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_tmux_environment_option_rejects_unusable_versions(self, mock_run):
        unusable_results = (
            MockCompletedProcess(stdout="tmux 3.1-rc2"),
            MockCompletedProcess(stdout="tmux 3.2", returncode=1),
            MockCompletedProcess(stdout="tmux version unknown"),
        )

        for result in unusable_results:
            with self.subTest(stdout=result.stdout, returncode=result.returncode):
                mock_run.return_value = result
                self.assertFalse(
                    project_scope._tmux_supports_environment_option("/usr/bin/tmux")
                )

    @patch("cli_topsailai.project_scope.subprocess.run", side_effect=OSError)
    def test_tmux_environment_option_rejects_execution_error(self, mock_run):
        supported = project_scope._tmux_supports_environment_option("/usr/bin/tmux")

        self.assertFalse(supported)
        mock_run.assert_called_once_with(
            ["/usr/bin/tmux", "-V"],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("cli_topsailai.project_scope._build_dtach_socket_path")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_unsupported_tmux_falls_back_to_dtach(
        self, mock_which, mock_supports_environment_option, mock_build_socket
    ):
        mock_which.side_effect = ["/usr/bin/tmux", "/usr/bin/dtach"]
        mock_supports_environment_option.return_value = False
        mock_build_socket.return_value = "/tmp/agent.dtach"

        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent", "tmux"
        )

        self.assertEqual(result, "dtach -A /tmp/agent.dtach topsailai_launch_agent")
        mock_supports_environment_option.assert_called_once_with("/usr/bin/tmux")
        self.assertEqual(mock_which.call_args_list[0].args, ("tmux",))
        self.assertEqual(mock_which.call_args_list[1].args, ("dtach",))

    @patch("cli_topsailai.project_scope._tmux_supports_environment_option")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_unsupported_tmux_falls_back_to_raw_without_dtach(
        self, mock_which, mock_supports_environment_option
    ):
        mock_which.side_effect = ["/usr/bin/tmux", None]
        mock_supports_environment_option.return_value = False

        result = project_scope._wrap_command_for_agent_mode(
            "topsailai_launch_agent", "tmux"
        )

        self.assertEqual(result, "topsailai_launch_agent")

    def test_unsupported_mode_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            project_scope._wrap_command_for_agent_mode(
                "topsailai_launch_agent", "unsupported"
            )
        self.assertIn("Unsupported agent launch mode", str(ctx.exception))


class TestLoadProjectWorkspaceLookup(unittest.TestCase):
    """Tests for load_project_workspace_lookup."""

    def _write_history(self, home, lines):
        """Write project history lines to the home directory."""
        history_path = os.path.join(home, ".project_history.jsonl")
        with open(history_path, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")

    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_missing_history_file_returns_empty(self, mock_home):
        with tempfile.TemporaryDirectory() as tmp:
            mock_home.return_value = tmp
            lookup = project_scope.load_project_workspace_lookup()
            self.assertEqual(lookup, {})

    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_empty_history_file_returns_empty(self, mock_home):
        with tempfile.TemporaryDirectory() as tmp:
            mock_home.return_value = tmp
            self._write_history(tmp, [])
            lookup = project_scope.load_project_workspace_lookup()
            self.assertEqual(lookup, {})

    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_newest_entry_wins_for_session(self, mock_home):
        with tempfile.TemporaryDirectory() as tmp:
            mock_home.return_value = tmp
            # File order determines newest-first; the last written line wins.
            self._write_history(
                tmp,
                [
                    '{"ts": 1, "session_id": "s1", "project_workspace": "/work/old", "pwd": "/work/old"}',
                    '{"ts": 2, "session_id": "s1", "project_workspace": "/work/new", "pwd": "/work/new"}',
                    '{"ts": 3, "session_id": "s1", "project_workspace": "/work/newest", "pwd": "/work/newest"}',
                ],
            )
            lookup = project_scope.load_project_workspace_lookup()
            self.assertEqual(lookup, {"s1": "/work/newest"})

    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_multiple_sessions_in_lookup(self, mock_home):
        with tempfile.TemporaryDirectory() as tmp:
            mock_home.return_value = tmp
            self._write_history(
                tmp,
                [
                    '{"ts": 1, "session_id": "s1", "project_workspace": "/work/a", "pwd": "/work/a"}',
                    '{"ts": 2, "session_id": "s2", "project_workspace": "/work/b", "pwd": "/work/b"}',
                ],
            )
            lookup = project_scope.load_project_workspace_lookup()
            self.assertEqual(lookup, {"s1": "/work/a", "s2": "/work/b"})

    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_malformed_lines_are_skipped(self, mock_home):
        with tempfile.TemporaryDirectory() as tmp:
            mock_home.return_value = tmp
            self._write_history(
                tmp,
                [
                    "not-json",
                    '{"ts": 1, "session_id": "s1", "project_workspace": "/work/a", "pwd": "/work/a"}',
                    "",
                    '{"ts": 2, "session_id": "s2"}',
                ],
            )
            lookup = project_scope.load_project_workspace_lookup()
            self.assertEqual(lookup, {"s1": "/work/a"})

    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_temp_session_included(self, mock_home):
        with tempfile.TemporaryDirectory() as tmp:
            mock_home.return_value = tmp
            self._write_history(
                tmp,
                [
                    '{"ts": 1, "session_id": "topsailai", "project_workspace": "/work/temp", "pwd": "/work/temp"}',
                ],
            )
            lookup = project_scope.load_project_workspace_lookup()
            self.assertEqual(lookup, {"topsailai": "/work/temp"})

    @patch("cli_topsailai.project_scope.get_topsailai_home")
    def test_empty_workspace_skipped(self, mock_home):
        with tempfile.TemporaryDirectory() as tmp:
            mock_home.return_value = tmp
            self._write_history(
                tmp,
                [
                    '{"ts": 1, "session_id": "s1", "project_workspace": "", "pwd": "/work/a"}',
                    '{"ts": 2, "session_id": "s2", "project_workspace": null, "pwd": "/work/b"}',
                ],
            )
            lookup = project_scope.load_project_workspace_lookup()
            self.assertEqual(lookup, {})


class TestPromptForDriver(unittest.TestCase):
    """Tests for _prompt_for_driver."""

    @patch("builtins.input", side_effect=[""])
    def test_default_selection(self, mock_input):
        driver = project_scope._prompt_for_driver()
        self.assertEqual(driver, "topsailai_agent_chats")

    def test_default_selection_matches_resume_default(self):
        """Pressing Enter must agree with the non-interactive resume default."""
        with patch("builtins.input", side_effect=[""]):
            driver = project_scope._prompt_for_driver()
        self.assertEqual(driver, project_scope._RESUME_DEFAULT_DRIVER)

    @patch("builtins.input", side_effect=["1"])
    def test_select_first_option(self, mock_input):
        driver = project_scope._prompt_for_driver()
        self.assertEqual(driver, "topsailai_agent_chats")

    @patch("builtins.input", side_effect=["3"])
    def test_select_third_option(self, mock_input):
        driver = project_scope._prompt_for_driver()
        self.assertEqual(driver, "ai-team-flow-dev")

    @patch("builtins.input", side_effect=["4", "my-custom-driver"])
    def test_select_custom_input(self, mock_input):
        driver = project_scope._prompt_for_driver()
        self.assertEqual(driver, "my-custom-driver")

    @patch("builtins.input", side_effect=["4", "", "2"])
    def test_custom_empty_then_default(self, mock_input):
        driver = project_scope._prompt_for_driver()
        self.assertEqual(driver, "topsailai_agent_plan_tasks")

    @patch("builtins.input", side_effect=["invalid", "0", "5", "2"])
    def test_invalid_then_valid_selection(self, mock_input):
        driver = project_scope._prompt_for_driver()
        self.assertEqual(driver, "topsailai_agent_plan_tasks")


class _FakeChild:
    """Minimal owned-child stand-in exposing the reaping contract."""

    def __init__(self, code=0, interrupt=False):
        self.code = code
        self.interrupt = interrupt
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        if self.interrupt:
            raise KeyboardInterrupt()
        return self.code

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class TestLaunchAgentDriver(unittest.TestCase):
    """Tests for launch_agent_driver.

    Every test here exercises the production path: ``spawn`` is left unset so
    the real ``_spawn_owned_child`` factory is used, and only
    ``subprocess.Popen`` itself is replaced.
    """

    def _which(self, driver_present=True):
        """Resolve the driver and any wrapper tool without touching the host."""

        def _resolve(name):
            if name == "topsailai_agent_plan_tasks":
                return "/usr/bin/topsailai_agent_plan_tasks" if driver_present else None
            if name in ("dtach", "tmux"):
                return f"/usr/bin/{name}"
            return None

        return _resolve

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_launches_driver_directly_without_dtach(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="raw",
        )
        self.assertEqual(code, 0)
        self.assertEqual(mock_popen.call_args.args[0], ["topsailai_agent_plan_tasks"])
        self.assertEqual(mock_popen.call_args.kwargs["cwd"], "/work/project-a")
        mock_chdir.assert_any_call("/work/project-a")
        mock_chdir.assert_any_call("/TopsailAI/cli")

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_sets_both_session_id_env_aliases(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="raw",
        )
        child_env = mock_popen.call_args.kwargs["env"]
        self.assertEqual(child_env["TOPSAILAI_SESSION_ID"], "s-123")
        self.assertEqual(child_env["SESSION_ID"], "s-123")
        self.assertEqual(child_env["PWD"], "/work/project-a")
        self.assertEqual(child_env["TOPSAILAI_PWD"], "/work/project-a")

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._build_dtach_socket_path")
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_launches_with_dtach_when_available(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen,
        mock_build_socket, _mock_model
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_build_socket.return_value = "/home/user/.topsailai/workspace/task/x.dtach"
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123"
        )
        called_command = mock_popen.call_args.args[0]
        self.assertTrue(called_command.startswith("dtach -A "))
        self.assertIn("topsailai_agent_plan_tasks", called_command)
        self.assertTrue(mock_popen.call_args.kwargs["shell"])

    @patch.dict(
        os.environ,
        {
            "TOPSAILAI_SESSION_ID": "s-123",
            "TOPSAILAI_PWD": "/work/project-a",
            "PWD": "/work/project-a",
        },
        clear=False,
    )
    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._generate_agent_session_name")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option")
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_tmux_mode_forwards_both_identity_aliases(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen,
        mock_supports_environment_option, mock_generate_name, _mock_model
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_supports_environment_option.return_value = True
        mock_generate_name.return_value = "topsailai-20260707T221748.169974"
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="tmux"
        )
        called_command = mock_popen.call_args.args[0]
        self.assertTrue(called_command.startswith("tmux new-session"))
        self.assertIn("-e TOPSAILAI_SESSION_ID=s-123", called_command)
        self.assertIn("-e SESSION_ID=s-123", called_command)
        self.assertIn("-e TOPSAILAI_PWD=/work/project-a", called_command)
        self.assertIn("-e PWD=/work/project-a", called_command)
        self.assertIn("topsailai_agent_plan_tasks", called_command)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_raw_mode_invokes_driver_directly(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="raw"
        )
        self.assertEqual(mock_popen.call_args.args[0], ["topsailai_agent_plan_tasks"])
        self.assertNotIn("shell", mock_popen.call_args.kwargs)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_restores_original_env_values_after_launch(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        original_pwd = os.environ.get("PWD")
        original_topsailai_pwd = os.environ.get("TOPSAILAI_PWD")
        original_session_id = os.environ.get("TOPSAILAI_SESSION_ID")
        original_alias = os.environ.get("SESSION_ID")
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="raw"
        )
        self.assertEqual(os.environ.get("PWD"), original_pwd)
        self.assertEqual(os.environ.get("TOPSAILAI_PWD"), original_topsailai_pwd)
        self.assertEqual(os.environ.get("TOPSAILAI_SESSION_ID"), original_session_id)
        self.assertEqual(os.environ.get("SESSION_ID"), original_alias)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_missing_executable_is_a_launch_failure(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """A missing driver must not leak the shell's 127 status."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which(driver_present=False)
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="raw"
        )
        self.assertEqual(code, 5)
        mock_popen.assert_not_called()

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._stop_owned_driver", return_value=True)
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_interrupt_stops_owned_child_and_returns_130(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen,
        mock_stop, _mock_model
    ):
        """The production path must reap the owned child on interruption."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        child = _FakeChild(interrupt=True)
        mock_popen.return_value = child
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="raw"
        )
        self.assertEqual(code, 130)
        mock_stop.assert_called_once()
        self.assertIs(mock_stop.call_args.args[1], child)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._stop_owned_driver", return_value=False)
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_unresolved_custody_returns_6(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen,
        _mock_stop, _mock_model
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(interrupt=True)
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="raw"
        )
        self.assertEqual(code, 6)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._wrap_command_for_agent_mode",
           side_effect=RuntimeError("tmux unavailable"))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_wrapper_preparation_failure_returns_4(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen,
        _mock_wrap, _mock_model
    ):
        """A wrapper preparation error must not escape the status boundary."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="tmux"
        )
        self.assertEqual(code, 4)
        mock_popen.assert_not_called()

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_cwd_restoration_failure_fails_closed(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """A launch that cannot restore the caller cwd is not a clean success."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)

        def _chdir(target):
            if target == "/TopsailAI/cli":
                raise OSError("restore denied")

        mock_chdir.side_effect = _chdir
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123", agent_mode="raw"
        )
        self.assertEqual(code, 6)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_prelaunch_refusal_prevents_spawn(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """The late revalidation runs after preparation and can refuse launch."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        calls = []

        def _refuse():
            calls.append("checked")
            return 4

        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="raw", prelaunch_check=_refuse,
        )
        self.assertEqual(code, 4)
        self.assertEqual(calls, ["checked"])
        mock_popen.assert_not_called()

class TestOwnedDriverSpawn(unittest.TestCase):
    """UNIT 3A: the driver process tree is owned in every launch mode.

    These tests exercise the production seam: ``spawn`` is left unset so the
    real ``_spawn_owned_child`` factory is used, and only
    ``subprocess.Popen`` itself is replaced.
    """

    def _which(self, driver_present=True):
        """Resolve the driver and any wrapper tool without touching the host."""

        def _resolve(name):
            if name == "topsailai_agent_plan_tasks":
                return "/usr/bin/topsailai_agent_plan_tasks" if driver_present else None
            if name in ("dtach", "tmux"):
                return f"/usr/bin/{name}"
            return None

        return _resolve

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._stop_owned_driver", return_value=True)
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_interrupt_in_dtach_mode_stops_owned_driver(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen,
        mock_stop, _mock_model
    ):
        """dtach daemonizes, so the ownership record must be used to stop it."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        child = _FakeChild(interrupt=True)
        mock_popen.return_value = child
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="dtach",
        )
        self.assertEqual(code, 130)
        mock_stop.assert_called_once()
        ownership = mock_stop.call_args.args[0]
        self.assertEqual(ownership.kind, "dtach")
        self.assertTrue(ownership.pidfile)
        self.assertIs(mock_stop.call_args.args[1], child)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._stop_owned_driver", return_value=True)
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option",
           return_value=True)
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_interrupt_in_tmux_mode_stops_owned_driver(
        self, mock_getcwd, mock_chdir, _mock_tmux_env, mock_which, mock_popen,
        mock_stop, _mock_model
    ):
        """tmux runs the driver inside a server, so the session must be owned."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        child = _FakeChild(interrupt=True)
        mock_popen.return_value = child
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="tmux",
        )
        self.assertEqual(code, 130)
        mock_stop.assert_called_once()
        ownership = mock_stop.call_args.args[0]
        self.assertEqual(ownership.kind, "tmux")
        self.assertTrue(ownership.session_name)
        self.assertTrue(ownership.pidfile)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope._stop_owned_driver", return_value=False)
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_interrupt_in_dtach_mode_reports_unproven_custody(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen,
        _mock_stop, _mock_model
    ):
        """A cancellation that cannot prove the driver is gone must return 6."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(interrupt=True)
        code = project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="dtach",
        )
        self.assertEqual(code, 6)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_custom_driver_with_arguments_runs_without_enoent(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """A custom driver command line may carry arguments, as before."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        code = project_scope.launch_agent_driver(
            "/work/project-a",
            "/usr/bin/python3 -c 'raise SystemExit(0)'",
            "s-123",
            agent_mode="raw",
        )
        self.assertEqual(code, 0)
        argv = mock_popen.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/python3")
        self.assertEqual(argv[1], "-c")
        self.assertEqual(argv[2], "raise SystemExit(0)")

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_raw_mode_child_leads_its_own_session(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """The raw driver must lead its own group so the tree is addressable."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="raw",
        )
        self.assertTrue(mock_popen.call_args.kwargs["start_new_session"])

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option",
           return_value=True)
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_tmux_client_does_not_lead_its_own_session(
        self, mock_getcwd, mock_chdir, _mock_tmux_env, mock_which, mock_popen,
        _mock_model
    ):
        """The tmux client shares the caller group; signalling it would kill us."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="tmux",
        )
        self.assertNotIn("start_new_session", mock_popen.call_args.kwargs)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope._tmux_supports_environment_option",
           return_value=True)
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_tmux_forwards_both_identity_aliases(
        self, mock_getcwd, mock_chdir, _mock_tmux_env, mock_which, mock_popen,
        _mock_model
    ):
        """An existing tmux server must not retain a conflicting alias."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="tmux",
        )
        command = mock_popen.call_args.args[0]
        self.assertIn("TOPSAILAI_SESSION_ID=s-123", command)
        self.assertIn("SESSION_ID=s-123", command)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_dtach_wrapper_records_driver_pid(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """The dtach wrapper must record the driver PID before exec."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        mock_popen.return_value = _FakeChild(0)
        project_scope.launch_agent_driver(
            "/work/project-a", "topsailai_agent_plan_tasks", "s-123",
            agent_mode="dtach",
        )
        command = mock_popen.call_args.args[0]
        self.assertIn("echo $$ >", command)
        self.assertIn("exec topsailai_agent_plan_tasks", command)

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_missing_executable_in_custom_command_returns_5(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """A missing custom executable is a launch failure, not a shell 127."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        code = project_scope.launch_agent_driver(
            "/work/project-a", "no_such_driver --flag", "s-123", agent_mode="raw"
        )
        self.assertEqual(code, 5)
        mock_popen.assert_not_called()

    @patch("cli_topsailai.project_scope._apply_selected_model_environment",
           return_value=({}, set()))
    @patch("cli_topsailai.project_scope.subprocess.Popen")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_empty_driver_command_line_returns_4(
        self, mock_getcwd, mock_chdir, mock_which, mock_popen, _mock_model
    ):
        """An unparseable driver command line is a preparation failure."""
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.side_effect = self._which()
        code = project_scope.launch_agent_driver(
            "/work/project-a", "   ", "s-123", agent_mode="raw"
        )
        self.assertEqual(code, 4)
        mock_popen.assert_not_called()


class TestResumeSession(unittest.TestCase):
    """Tests for resume_session."""

    def _make_entry(self, session_id, status, workspace):
        return {
            "no": 1,
            "session_id": session_id,
            "session_name": f"name-{session_id}",
            "project_workspace": workspace,
            "modified_time": "07-06 10:00",
            "modified_time_raw": "2026-07-06T10:00:00",
            "task": "task",
            "status": status,
        }

    @patch("cli_topsailai.project_scope.launch_agent_driver")
    @patch("cli_topsailai.project_scope._prompt_for_driver")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_resume_idle_session_default_driver(
        self, mock_stdout, mock_prompt, mock_launch
    ):
        entries = [self._make_entry("s-idle", "Idle", "/work/project-a")]
        project_scope.resume_session("1", entries, agent_mode="dtach")
        mock_prompt.assert_not_called()
        mock_launch.assert_called_once_with(
            "/work/project-a", "topsailai_agent_chats", "s-idle", agent_mode="dtach"
        )
        output = mock_stdout.getvalue()
        self.assertIn("Resuming session 's-idle'", output)
        self.assertIn("topsailai_agent_chats", output)

    @patch("cli_topsailai.project_scope.launch_agent_driver")
    @patch("cli_topsailai.project_scope._prompt_for_driver")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_resume_idle_session_explicit_driver(
        self, mock_stdout, mock_prompt, mock_launch
    ):
        entries = [self._make_entry("s-idle", "Idle", "/work/project-a")]
        project_scope.resume_session(
            "1", entries, agent_mode="tmux", driver="ai-team-flow-dev"
        )
        mock_prompt.assert_not_called()
        mock_launch.assert_called_once_with(
            "/work/project-a", "ai-team-flow-dev", "s-idle", agent_mode="tmux"
        )
        output = mock_stdout.getvalue()
        self.assertIn("ai-team-flow-dev", output)

    @patch("cli_topsailai.project_scope.launch_agent_driver")
    @patch("cli_topsailai.project_scope._prompt_for_driver")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_refuse_to_resume_running_session(
        self, mock_stdout, mock_prompt, mock_launch
    ):
        entries = [self._make_entry("s-running", "Running", "/work/project-a")]
        project_scope.resume_session("1", entries, agent_mode="raw")
        mock_prompt.assert_not_called()
        mock_launch.assert_not_called()
        output = mock_stdout.getvalue()
        self.assertIn("already running", output)

    @patch("cli_topsailai.project_scope.launch_agent_driver")
    @patch("cli_topsailai.project_scope._prompt_for_driver")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_resume_invalid_number(self, mock_stdout, mock_prompt, mock_launch):
        entries = [self._make_entry("s-idle", "Idle", "/work/project-a")]
        project_scope.resume_session("5", entries, agent_mode="raw")
        mock_prompt.assert_not_called()
        mock_launch.assert_not_called()
        output = mock_stdout.getvalue()
        self.assertIn("Invalid number", output)

    @patch("cli_topsailai.project_scope.launch_agent_driver")
    @patch("cli_topsailai.project_scope._prompt_for_driver")
    @patch("cli_topsailai.project_scope.load_project_workspace_lookup")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_resume_uses_history_workspace_when_missing(
        self, mock_stdout, mock_lookup, mock_prompt, mock_launch
    ):
        mock_lookup.return_value = {"s-idle": "/work/from-history"}
        entries = [self._make_entry("s-idle", "Idle", "")]
        project_scope.resume_session("1", entries, agent_mode="dtach")
        mock_prompt.assert_not_called()
        mock_lookup.assert_called_once()
        mock_launch.assert_called_once_with(
            "/work/from-history", "topsailai_agent_chats", "s-idle", agent_mode="dtach"
        )

    @patch("cli_topsailai.project_scope.launch_agent_driver")
    @patch("cli_topsailai.project_scope._prompt_for_driver")
    @patch("cli_topsailai.project_scope.load_project_workspace_lookup")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_resume_no_workspace_prints_error(
        self, mock_stdout, mock_lookup, mock_prompt, mock_launch
    ):
        mock_lookup.return_value = {}
        entries = [self._make_entry("s-idle", "Idle", "")]
        project_scope.resume_session("1", entries)
        mock_prompt.assert_not_called()
        mock_launch.assert_not_called()
        output = mock_stdout.getvalue()
        self.assertIn("no project workspace", output)






class TestWorkspaceResumeDelegation(unittest.TestCase):
    """Tests for workspace-scope /resume delegating to resume_session."""

    @patch("cli_topsailai.project_scope.resume_session")
    def test_resume_from_log_entry_with_workspace(self, mock_resume):
        log_files = [
            {
                "no": 1,
                "session_id": "s-idle",
                "status": "Idle",
                "project_workspace": "/work/project-a",
            }
        ]
        core._resume_from_workspace_log(
            "1", log_files, agent_mode="dtach", driver="ai-team-flow-dev"
        )
        mock_resume.assert_called_once()
        args = mock_resume.call_args
        self.assertEqual(args[0][0], "1")
        entry = args[0][1][0]
        self.assertEqual(entry["session_id"], "s-idle")
        self.assertEqual(entry["project_workspace"], "/work/project-a")
        self.assertEqual(entry["status"], "Idle")
        self.assertEqual(args[1]["agent_mode"], "dtach")
        self.assertEqual(args[1]["driver"], "ai-team-flow-dev")

    @patch("cli_topsailai.project_scope.load_project_workspace_lookup")
    @patch("cli_topsailai.project_scope.resume_session")
    def test_resume_from_log_entry_uses_history_lookup(
        self, mock_resume, mock_lookup
    ):
        mock_lookup.return_value = {"s-idle": "/work/from-history"}
        log_files = [
            {
                "no": 1,
                "session_id": "s-idle",
                "status": "Idle",
                "project_workspace": "",
            }
        ]
        core._resume_from_workspace_log("1", log_files, agent_mode="tmux")
        mock_lookup.assert_called_once()
        mock_resume.assert_called_once()
        entry = mock_resume.call_args[0][1][0]
        self.assertEqual(entry["project_workspace"], "/work/from-history")

    @patch("cli_topsailai.project_scope.load_project_workspace_lookup")
    @patch("cli_topsailai.project_scope.resume_session")
    @patch("builtins.print")
    def test_resume_from_log_entry_missing_workspace_prints_error(
        self, mock_print, mock_resume, mock_lookup
    ):
        mock_lookup.return_value = {}
        log_files = [
            {
                "no": 1,
                "session_id": "s-idle",
                "status": "Idle",
                "project_workspace": "",
            }
        ]
        result = core._resume_from_workspace_log("1", log_files, agent_mode="raw")
        self.assertFalse(result)
        mock_lookup.assert_called_once()
        mock_resume.assert_not_called()
        self.assertTrue(
            any("Selected session has no project workspace" in str(call) for call in mock_print.call_args_list)
        )
class TestManagedProjectWrappers(unittest.TestCase):
    """Tests for managed-project helpers in project_scope."""

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None
        cli_state._child_processes.clear()

    @patch("cli_topsailai.project_scope._build_managed_project_list")
    def test_build_managed_project_list_wrapper(self, mock_build):
        mock_build.return_value = [
            {"no": 1, "name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"},
        ]
        entries = project_scope.build_managed_project_list()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "a")
        mock_build.assert_called_once_with()

    @patch("sys.stdout", new_callable=io.StringIO)
    @patch("cli_topsailai.project_scope._print_managed_project_table")
    def test_print_managed_project_table_wrapper(self, mock_print_table, mock_stdout):
        entries = [
            {"no": 1, "name": "a", "path": "/work/a", "created_at": "2026-07-25T08:00:00"},
        ]
        project_scope.print_managed_project_table(entries)
        mock_print_table.assert_called_once_with(entries)


class TestResolveAgentFolderManaged(unittest.TestCase):
    """Tests for resolve_agent_folder with managed project entries."""

    def test_resolve_managed_project_by_number(self):
        entries = [
            {"no": 1, "name": "a", "path": "/work/a"},
            {"no": 2, "name": "b", "path": "/work/b"},
        ]
        folder = project_scope.resolve_agent_folder("2", entries)
        self.assertEqual(folder, "/work/b")

    def test_resolve_managed_project_uses_path(self):
        entries = [
            {"no": 1, "name": "a", "path": "/work/managed"},
        ]
        folder = project_scope.resolve_agent_folder("1", entries)
        self.assertEqual(folder, "/work/managed")

    def test_resolve_project_workspace_takes_precedence_over_path(self):
        entries = [
            {"no": 1, "name": "a", "path": "/work/managed", "project_workspace": "/work/session"},
        ]
        folder = project_scope.resolve_agent_folder("1", entries)
        self.assertEqual(folder, "/work/session")

    def test_resolve_managed_project_invalid_number(self):
        entries = [{"no": 1, "name": "a", "path": "/work/a"}]
        folder = project_scope.resolve_agent_folder("5", entries)
        self.assertIsNone(folder)


class TestPromptSelectionManagedProjects(unittest.TestCase):
    """Tests for prompt_selection handling of managed project commands."""

    def setUp(self):
        cli_state.current_scope = "project"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None
        cli_state._child_processes.clear()

    @patch("cli_topsailai.core.input")
    def test_p_shows_managed_projects(self, mock_input):
        mock_input.return_value = "p"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "show_managed_projects")

    @patch("cli_topsailai.core.input")
    def test_projects_alias_shows_managed_projects(self, mock_input):
        mock_input.return_value = "projects"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "show_managed_projects")

    @patch("cli_topsailai.core.input")
    def test_r_shows_recent_projects(self, mock_input):
        mock_input.return_value = "r"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "show_recent_projects")

    @patch("cli_topsailai.core.input")
    def test_recent_alias_shows_recent_projects(self, mock_input):
        mock_input.return_value = "recent"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "show_recent_projects")

    @patch("cli_topsailai.core.input")
    def test_p_add_with_args(self, mock_input):
        mock_input.return_value = "p add /work/my-project my-project"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "add_managed_project")
        self.assertEqual(value, "/work/my-project my-project")

    @patch("cli_topsailai.core.input")
    def test_p_add_without_args(self, mock_input):
        mock_input.return_value = "p add"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "add_managed_project")
        self.assertEqual(value, "")

    @patch("cli_topsailai.core.input")
    def test_p_del_with_number(self, mock_input):
        mock_input.return_value = "p del 2"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "delete_managed_project")
        self.assertEqual(value, "2")

    @patch("builtins.print")
    @patch("cli_topsailai.core.input")
    def test_p_del_without_number_shows_usage(self, mock_input, mock_print):
        mock_input.side_effect = ["p del", "q"]
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")
        self.assertTrue(
            any("Usage: p del <number>" in str(call) for call in mock_print.call_args_list)
        )

    @patch("builtins.print")
    @patch("cli_topsailai.core.input")
    def test_p_unknown_subcommand_shows_error(self, mock_input, mock_print):
        mock_input.side_effect = ["p foo", "q"]
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")
        self.assertTrue(
            any("Unknown project sub-command" in str(call) for call in mock_print.call_args_list)
        )

    @patch("cli_topsailai.core.input")
    def test_agent_number_in_project_managed_mode(self, mock_input):
        mock_input.return_value = "agent 2"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "agent")
        self.assertEqual(value, "2")


class ResumeBackgroundMechanismTests(unittest.TestCase):
    """A background resume forwards the selected mechanism instead of forcing raw."""

    def _resume(self, **options):
        """Run one resume against a stubbed lookup and launch boundary."""
        from cli_topsailai import project_scope as scope

        record = {"session_id": "session-1", "project_workspace": "/work/proj"}
        with patch.object(scope, "lookup_persisted_session", return_value=record), \
             patch.object(scope, "_validate_resume_workspace", return_value="/work/proj"), \
             patch.object(scope, "session_liveness", return_value="idle"), \
             patch("cli_topsailai.agent_launch.launch_configured_agent",
                   return_value=0) as launch:
            status = scope.resume_session_result("session-1", **options)
        return status, launch

    def test_background_defaults_to_raw(self):
        """A background resume without an explicit mode uses the new process."""
        status, launch = self._resume(background=True)
        self.assertEqual(status, 0)
        self.assertEqual(launch.call_args.kwargs["mode"], "raw")
        self.assertTrue(launch.call_args.kwargs["background"])

    def test_background_forwards_each_selected_mechanism(self):
        """Every explicitly selected mechanism reaches the launch boundary."""
        for mechanism in ("raw", "tmux", "dtach"):
            status, launch = self._resume(background=True, agent_mode=mechanism)
            self.assertEqual(status, 0)
            self.assertEqual(launch.call_args.kwargs["mode"], mechanism)

    def test_foreground_default_stays_dtach(self):
        """The foreground default is unchanged by the background selection."""
        from cli_topsailai import project_scope as scope

        record = {"session_id": "session-1", "project_workspace": "/work/proj"}
        with patch.object(scope, "lookup_persisted_session", return_value=record), \
             patch.object(scope, "_validate_resume_workspace", return_value="/work/proj"), \
             patch.object(scope, "session_liveness", return_value="idle"), \
             patch.object(scope, "launch_agent_driver", return_value=0) as launch:
            status = scope.resume_session_result("session-1")
        self.assertEqual(status, 0)
        self.assertEqual(launch.call_args.kwargs["agent_mode"], "dtach")

    def test_background_status_line_reports_selected_mechanism(self):
        """The status line reports the mechanism that will actually be used."""
        from cli_topsailai import project_scope as scope

        record = {"session_id": "session-1", "project_workspace": "/work/proj"}
        with patch.object(scope, "lookup_persisted_session", return_value=record), \
             patch.object(scope, "_validate_resume_workspace", return_value="/work/proj"), \
             patch.object(scope, "session_liveness", return_value="idle"), \
             patch("cli_topsailai.agent_launch.launch_configured_agent",
                   return_value=0), \
             patch("builtins.print") as output:
            scope.resume_session_result("session-1", background=True, agent_mode="tmux")
        printed = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("mode: tmux", printed)


def _spawn_zombie():
    """Fork a child that exits immediately without being reaped.

    Returns the child PID, which the caller must reap. The helper waits until
    the OS actually reports state ``Z``, because a freshly forked child is
    still running for a few milliseconds and probing it early would test the
    race instead of the zombie contract.
    """
    from cli_topsailai.agent_launch_process import _process_state

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


class TestProjectScopeLiveness(unittest.TestCase):
    """Pin the liveness contract of the project-scope status path.

    These tests assert behaviour, not mechanism: the status path must agree
    with the shared primitive on zombies, non-positive PIDs and multiple
    stdout candidates, so a session cannot be reported Running by one command
    and Idle by another.
    """

    def _write_stdout(self, task_dir, session_id, pid):
        """Create a session stdout file for testing."""
        path = os.path.join(task_dir, f"{session_id}.{pid}.session.stdout")
        with open(path, "w") as fh:
            fh.write("log line\n")
        return path

    def test_zombie_session_is_not_running(self):
        """A zombie process must not keep a session Running."""
        pid = _spawn_zombie()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                task_dir = os.path.join(tmp, "workspace", "task")
                os.makedirs(task_dir)
                self._write_stdout(task_dir, "s-zombie", pid)
                self.assertFalse(project_scope._check_session_running(tmp, "s-zombie"))
        finally:
            _reap(pid)

    def test_absent_session_is_not_running(self):
        """A reaped PID must report the session as not running."""
        pid = _absent_pid()
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-dead", pid)
            self.assertFalse(project_scope._check_session_running(tmp, "s-dead"))

    def test_live_session_is_running(self):
        """The current process must keep its session Running."""
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-live", os.getpid())
            self.assertTrue(project_scope._check_session_running(tmp, "s-live"))

    def test_older_live_file_beats_newer_dead_file(self):
        """A newer dead file must not hide an older live process."""
        dead_pid = _absent_pid()
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            live_path = self._write_stdout(task_dir, "s-multi", os.getpid())
            dead_path = self._write_stdout(task_dir, "s-multi", dead_pid)
            os.utime(live_path, (1000, 1000))
            os.utime(dead_path, (2000, 2000))
            self.assertTrue(project_scope._check_session_running(tmp, "s-multi"))

    def test_negative_pid_is_not_running(self):
        """A negative PID must never be probed as a process."""
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-neg", -1)
            self.assertFalse(project_scope._check_session_running(tmp, "s-neg"))

    def test_zero_pid_is_not_running(self):
        """A zero PID addresses the process group, not one process."""
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "workspace", "task")
            os.makedirs(task_dir)
            self._write_stdout(task_dir, "s-zero", 0)
            self.assertFalse(project_scope._check_session_running(tmp, "s-zero"))

    def test_pid_state_negative_is_unknown(self):
        """The shared probe must refuse to classify a non-positive PID."""
        self.assertEqual(pid_state(-1), ProcessState.UNKNOWN)
        self.assertEqual(pid_state(0), ProcessState.UNKNOWN)

    def test_pid_state_zombie_is_dead(self):
        """The shared probe must classify a zombie as dead."""
        pid = _spawn_zombie()
        try:
            self.assertEqual(pid_state(pid), ProcessState.DEAD)
        finally:
            _reap(pid)

    def test_pid_state_absent_is_dead(self):
        """The shared probe must classify a reaped PID as dead."""
        self.assertEqual(pid_state(_absent_pid()), ProcessState.DEAD)

    def test_pid_state_live_is_alive(self):
        """The shared probe must classify the current process as alive."""
        self.assertEqual(pid_state(os.getpid()), ProcessState.ALIVE)

    def test_is_pid_alive_rejects_zombie_and_non_positive(self):
        """The shared probe must reject a zombie and a non-positive PID."""
        pid = _spawn_zombie()
        try:
            self.assertFalse(is_pid_alive(pid))
        finally:
            _reap(pid)
        self.assertFalse(is_pid_alive(-1))
        self.assertFalse(is_pid_alive(0))
        self.assertTrue(is_pid_alive(os.getpid()))


if __name__ == "__main__":
    unittest.main()
