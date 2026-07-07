#!/usr/bin/env python3
"""
Unit tests for project scope support in cli_topsailai.
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai import project_scope


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
            }
        ]
        project_scope.print_project_table(entries)
        output = mock_stdout.getvalue()
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
            }
        ]
        project_scope.print_project_table(entries)
        output = mock_stdout.getvalue()
        self.assertIn("...", output)


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
