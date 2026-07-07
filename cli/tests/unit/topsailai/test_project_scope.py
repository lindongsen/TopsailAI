#!/usr/bin/env python3
"""
Unit tests for project scope support in cli_topsailai.
"""

import io
import json
import os
import shlex
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
        self.assertEqual(entries[0]["create_time"], "07-06 10:00")
        self.assertEqual(entries[0]["task"], "task one")
        self.assertEqual(entries[1]["session_id"], "s2")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertIn("--json", call_args)
        self.assertIn("--has-project", call_args)
        self.assertIn("--sort", call_args)
        self.assertIn("desc", call_args)
        self.assertIn("--limit", call_args)
        self.assertIn("10", call_args)

    @patch("cli_topsailai.project_scope.subprocess.run")
    def test_build_project_list_keeps_oldest_first_order(self, mock_run):
        """Database returns newest-first; after reversal oldest is row 1."""
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


class TestLaunchAgentInFolder(unittest.TestCase):
    """Tests for launch_agent_in_folder."""

    def _assert_env_during_launch(self, expected_folder):
        """Return a side-effect function that checks env vars during os.system."""
        def _side_effect(_cmd):
            self.assertEqual(
                os.environ.get("TOPSAILAI_PWD"),
                expected_folder,
                "TOPSAILAI_PWD must point to the target folder during launch",
            )
            self.assertEqual(
                os.environ.get("PWD"),
                expected_folder,
                "PWD must point to the target folder during launch",
            )
        return _side_effect

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    @patch("cli_topsailai.project_scope.os.system")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_launches_agent_with_os_system_and_env(
        self, mock_getcwd, mock_chdir, mock_system, mock_which
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_system.side_effect = self._assert_env_during_launch("/work/project-a")
        project_scope.launch_agent_in_folder("/work/project-a")
        mock_chdir.assert_any_call("/work/project-a")
        mock_chdir.assert_any_call("/TopsailAI/cli")
        mock_system.assert_called_once_with("topsailai_launch_agent")

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    @patch("cli_topsailai.project_scope.os.system")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_restores_cwd_and_env_on_system_failure(
        self, mock_getcwd, mock_chdir, mock_system, mock_which
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_system.side_effect = OSError("launch failed")
        project_scope.launch_agent_in_folder("/work/project-a")
        mock_chdir.assert_any_call("/work/project-a")
        mock_chdir.assert_any_call("/TopsailAI/cli")

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    @patch("cli_topsailai.project_scope.os.system")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_command_uses_bare_launcher_name(
        self, mock_getcwd, mock_chdir, mock_system, mock_which
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_system.side_effect = self._assert_env_during_launch("/work/weird dir")
        project_scope.launch_agent_in_folder("/work/weird dir")
        mock_chdir.assert_any_call("/work/weird dir")
        mock_chdir.assert_any_call("/TopsailAI/cli")
        mock_system.assert_called_once_with("topsailai_launch_agent")

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    @patch("cli_topsailai.project_scope.os.system")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_restores_original_env_values_after_launch(
        self, mock_getcwd, mock_chdir, mock_system, mock_which
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        original_pwd = os.environ.get("PWD")
        original_topsailai_pwd = os.environ.get("TOPSAILAI_PWD")
        project_scope.launch_agent_in_folder("/work/project-a")
        self.assertEqual(os.environ.get("PWD"), original_pwd)
        self.assertEqual(os.environ.get("TOPSAILAI_PWD"), original_topsailai_pwd)

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    @patch("cli_topsailai.project_scope.os.system")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_converts_relative_folder_to_absolute(
        self, mock_getcwd, mock_chdir, mock_system, mock_which
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_system.side_effect = self._assert_env_during_launch(
            "/TopsailAI/cli/relative-project"
        )
        project_scope.launch_agent_in_folder("relative-project")
        mock_chdir.assert_any_call("/TopsailAI/cli/relative-project")
        mock_chdir.assert_any_call("/TopsailAI/cli")


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


class TestWrapCommandWithDtach(unittest.TestCase):
    """Tests for _wrap_command_with_dtach."""

    @patch("cli_topsailai.project_scope.shutil.which")
    def test_no_dtach_returns_command_unchanged(self, mock_which):
        mock_which.return_value = None
        result = project_scope._wrap_command_with_dtach("topsailai_launch_agent")
        self.assertEqual(result, "topsailai_launch_agent")
        mock_which.assert_called_once_with("dtach")

    @patch("cli_topsailai.project_scope._build_dtach_socket_path")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_dtach_available_wraps_command(
        self, mock_which, mock_build_socket
    ):
        mock_which.return_value = "/usr/bin/dtach"
        mock_build_socket.return_value = "/home/user/.topsailai/workspace/task/20260707T221748.169974.dtach"
        result = project_scope._wrap_command_with_dtach("topsailai_launch_agent")
        expected = (
            "dtach -A "
            + shlex.quote("/home/user/.topsailai/workspace/task/20260707T221748.169974.dtach")
            + " topsailai_launch_agent"
        )
        self.assertEqual(result, expected)

    @patch("cli_topsailai.project_scope._build_dtach_socket_path")
    @patch("cli_topsailai.project_scope.shutil.which")
    def test_dtach_quotes_socket_path_with_spaces(
        self, mock_which, mock_build_socket
    ):
        mock_which.return_value = "/usr/bin/dtach"
        mock_build_socket.return_value = "/home/user/weird path/task/20260707T221748.169974.dtach"
        result = project_scope._wrap_command_with_dtach("topsailai_launch_agent")
        self.assertTrue(result.startswith("dtach -A "))
        self.assertIn(
            shlex.quote("/home/user/weird path/task/20260707T221748.169974.dtach"),
            result,
        )
        self.assertIn(" topsailai_launch_agent", result)


class TestLaunchAgentInFolderWithDtach(unittest.TestCase):
    """Integration tests for launch_agent_in_folder with dtach wrapping."""

    @patch("cli_topsailai.project_scope._build_dtach_socket_path")
    @patch("cli_topsailai.project_scope.shutil.which")
    @patch("cli_topsailai.project_scope.os.system")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_launches_with_dtach_when_available(
        self, mock_getcwd, mock_chdir, mock_system, mock_which, mock_build_socket
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        mock_which.return_value = "/usr/bin/dtach"
        mock_build_socket.return_value = "/home/user/.topsailai/workspace/task/20260707T221748.169974.dtach"
        project_scope.launch_agent_in_folder("/work/project-a")
        mock_system.assert_called_once()
        called_command = mock_system.call_args[0][0]
        self.assertTrue(called_command.startswith("dtach -A "))
        self.assertIn("topsailai_launch_agent", called_command)

    @patch("cli_topsailai.project_scope.shutil.which", return_value=None)
    @patch("cli_topsailai.project_scope.os.system")
    @patch("cli_topsailai.project_scope.os.chdir")
    @patch("cli_topsailai.project_scope.os.getcwd")
    def test_launches_without_dtach_when_unavailable(
        self, mock_getcwd, mock_chdir, mock_system, mock_which
    ):
        mock_getcwd.return_value = "/TopsailAI/cli"
        project_scope.launch_agent_in_folder("/work/project-a")
        mock_system.assert_called_once_with("topsailai_launch_agent")


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
