#!/usr/bin/env python3
"""
Unit tests for print helpers and help text in cli_topsailai.
"""

import os
import re
import sys
import unicodedata
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

import cli_topsailai.state as cli_state
from cli_topsailai.colors import Colors
from cli_topsailai.formatting import (
    format_command_table,
    format_file_table,
    print_table,
)
from cli_topsailai.help_text import print_help


class TestPrintHelpers(unittest.TestCase):
    """Tests for print helpers."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_help(self, mock_stdout):
        print_help([], cli_state.current_scope)
        output = mock_stdout.getvalue()
        self.assertIn("TopsailAI", output)

    def test_colors(self):
        self.assertTrue(hasattr(Colors, "GREEN"))
        self.assertTrue(hasattr(Colors, "RESET"))

    def test_format_file_table_empty(self):
        output = format_file_table([])
        self.assertIn("No log files", output)

    def test_format_command_table(self):
        commands = [
            {"cmd": "/help", "desc": "Show help"},
            {"cmd": "/quit", "desc": "Quit"},
        ]
        output = format_command_table(commands)
        self.assertIn("/help", output)
        self.assertIn("/quit", output)


class TestPrintTablePidDetection(unittest.TestCase):
    """Tests for print_table PID and status display."""

    def _capture_print_table(self, files):
        captured = StringIO()
        with patch("sys.stdout", new=captured):
            print_table(files)
        return captured.getvalue()

    def _data_line(self, output, session_id="s1"):
        return next(line for line in output.splitlines() if session_id in line)

    @patch("cli_topsailai.formatting.is_session_pipe_open", return_value=False)
    @patch("cli_topsailai.formatting.os.kill")
    def test_live_pid_shows_run_status(self, mock_kill, mock_pipe_open):
        mock_kill.return_value = None
        output = self._capture_print_table(
            [
                {
                    "filename": "s1.1234.session.stdout",
                    "path": "/tmp/s1.1234.session.stdout",
                    "session_id": "s1",
                    "pid": 1234,
                    "size": 100,
                    "mtime": 1700000000.0,
                    "ctime": 1700000000.0,
                }
            ]
        )
        data_line = self._data_line(output)
        self.assertIn("Status", output)
        self.assertIn("1234", data_line)
        self.assertIn("RUN", data_line)
        self.assertNotIn("INPUT", data_line)
        self.assertNotIn("WAIT", data_line)
        self.assertIn(Colors.GREEN, data_line)
        mock_kill.assert_called_once_with(1234, 0)
        mock_pipe_open.assert_called_once()

    @patch("cli_topsailai.formatting.is_session_pipe_open", return_value=True)
    @patch("cli_topsailai.formatting.os.kill")
    def test_open_pipe_shows_input_status_in_yellow(self, mock_kill, mock_pipe_open):
        mock_kill.return_value = None
        output = self._capture_print_table(
            [{
                "filename": "s1.1234.session.stdout",
                "path": "/tmp/s1.1234.session.stdout",
                "session_id": "s1",
                "pid": 1234,
                "ctime": 1700000000.0,
            }]
        )
        data_line = self._data_line(output)
        self.assertIn("Status", output)
        self.assertIn("INPUT", data_line)
        self.assertNotIn("WAIT", data_line)
        self.assertNotIn("RUN", data_line)
        self.assertIn(Colors.YELLOW, data_line)
        self.assertIn("Inputting", output)
        self.assertNotIn("Waiting for input", output)
        mock_pipe_open.assert_called_once()

    @patch("cli_topsailai.formatting.is_session_pipe_open")
    @patch("cli_topsailai.formatting.os.kill")
    def test_dead_pid_shows_idle_status(self, mock_kill, mock_pipe_open):
        mock_kill.side_effect = ProcessLookupError(1234)
        output = self._capture_print_table(
            [
                {
                    "filename": "s1.session.stdout",
                    "path": "/tmp/s1.session.stdout",
                    "session_id": "s1",
                    "pid": 1234,
                    "size": 100,
                    "mtime": 1700000000.0,
                    "ctime": 1700000000.0,
                }
            ]
        )
        data_line = self._data_line(output)
        self.assertNotIn("1234", data_line)
        self.assertNotIn("RUN", data_line)
        self.assertNotIn("WAIT", data_line)
        self.assertIn("-", data_line)
        self.assertIn(Colors.GRAY, data_line)
        mock_pipe_open.assert_not_called()

    @patch("cli_topsailai.formatting.is_session_pipe_open")
    def test_missing_pid_shows_idle_status(self, mock_pipe_open):
        output = self._capture_print_table(
            [
                {
                    "filename": "s1.session.stdout",
                    "path": "/tmp/s1.session.stdout",
                    "session_id": "s1",
                    "size": 100,
                    "mtime": 1700000000.0,
                    "ctime": 1700000000.0,
                }
            ]
        )
        data_line = self._data_line(output)
        self.assertNotIn("RUN", data_line)
        self.assertNotIn("WAIT", data_line)
        self.assertIn("-", data_line)
        self.assertIn(Colors.GRAY, data_line)
        mock_pipe_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestPrintTableProjectWorkspace(unittest.TestCase):
    """Tests for Project Workspace column rendering in print_table."""

    def _capture_print_table(self, files):
        captured = StringIO()
        with patch("sys.stdout", new=captured):
            print_table(files)
        return captured.getvalue()

    @patch("cli_topsailai.formatting.os.kill")
    def test_project_workspace_column_in_header(self, mock_kill):
        mock_kill.return_value = None
        output = self._capture_print_table(
            [
                {
                    "filename": "s1.1234.session.stdout",
                    "path": "/tmp/s1.1234.session.stdout",
                    "session_id": "s1",
                    "pid": 1234,
                    "size": 100,
                    "mtime": 1700000000.0,
                    "ctime": 1700000000.0,
                    "project_workspace": "/work/project-a",
                }
            ]
        )
        self.assertIn("Project Workspace", output)

    def test_session_name_column_follows_number(self):
        """Session Name appears immediately after No in headers and rows."""
        output = self._capture_print_table(
            [
                {
                    "filename": "session-id.1234.session.stdout",
                    "path": "/tmp/session-id.1234.session.stdout",
                    "session_id": "session-id",
                    "session_name": "session-name",
                    "ctime": 1700000000.0,
                }
            ]
        )
        header, _, row = output.splitlines()[:3]
        header_columns = [column.strip() for column in header.split("|")]
        row_columns = [column.strip() for column in row.split("|")]

        self.assertIn("No", header_columns[0])
        self.assertEqual(header_columns[1], "Session Name")
        self.assertEqual(header_columns[2], "Session ID")
        self.assertEqual(row_columns[1], "session-name")
        self.assertEqual(row_columns[2], "session-id")

    def test_table_columns_keep_fixed_display_widths(self):
        """Only truncatable columns retain fixed display widths."""
        output = self._capture_print_table(
            [
                {
                    "filename": "session-id.1234.session.stdout",
                    "path": "/tmp/session-id.1234.session.stdout",
                    "session_id": "session-id-" + "x" * 30,
                    "session_name": "会话名称" * 10,
                    "project_workspace": "/work/" + "项目" * 20,
                    "ctime": 1700000000.0,
                }
            ]
        )
        header, _, row = output.splitlines()[:3]
        ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

        def display_width(value):
            return sum(
                2 if unicodedata.east_asian_width(character) in ("F", "W") else 1
                for character in value
                if not unicodedata.combining(character)
            )

        expected_widths = [4, 18, 20, 5, 8, 15, 26]
        for line in (header, row):
            plain_line = ansi_escape.sub("", line)
            column_widths = [display_width(column) for column in plain_line.split("|")]
            self.assertEqual(column_widths, expected_widths)

        self.assertIn("...", row)

    @patch("cli_topsailai.formatting.is_session_pipe_open", return_value=True)
    @patch("cli_topsailai.formatting.os.kill")
    def test_no_pid_and_status_expand_without_truncation(self, mock_kill, mock_pipe_open):
        """No, PID, and Status widths grow to fit all rendered values."""
        file_info = {
            "filename": "session-id.123456789.session.stdout",
            "path": "/tmp/session-id.123456789.session.stdout",
            "session_id": "session-id",
            "pid": 123456789,
            "ctime": 1700000000.0,
        }
        with patch("builtins.enumerate", return_value=iter([(12345, file_info)])):
            output = self._capture_print_table([file_info])

        header, _, row = output.splitlines()[:3]
        ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
        header_columns = [column.strip() for column in ansi_escape.sub("", header).split("|")]
        row_columns = [column.strip() for column in ansi_escape.sub("", row).split("|")]

        self.assertEqual(header_columns[0], "No")
        self.assertEqual(row_columns[0], "12345")
        self.assertEqual(header_columns[3], "PID")
        self.assertEqual(row_columns[3], "123456789")
        self.assertEqual(header_columns[4], "Status")
        self.assertEqual(row_columns[4], "INPUT")
        self.assertNotIn("...", row_columns[0])
        self.assertNotIn("...", row_columns[3])
        self.assertNotIn("...", row_columns[4])
        mock_kill.assert_called_once_with(123456789, 0)
        mock_pipe_open.assert_called_once_with(file_info)

    @patch("cli_topsailai.formatting.os.kill")
    def test_project_workspace_value_rendered(self, mock_kill):
        mock_kill.return_value = None
        output = self._capture_print_table(
            [
                {
                    "filename": "s1.1234.session.stdout",
                    "path": "/tmp/s1.1234.session.stdout",
                    "session_id": "s1",
                    "pid": 1234,
                    "size": 100,
                    "mtime": 1700000000.0,
                    "ctime": 1700000000.0,
                    "project_workspace": "/work/project-a",
                }
            ]
        )
        self.assertIn("/work/project-a", output)

    @patch("cli_topsailai.formatting.os.kill")
    def test_missing_project_workspace_shows_placeholder(self, mock_kill):
        mock_kill.return_value = None
        output = self._capture_print_table(
            [
                {
                    "filename": "s1.1234.session.stdout",
                    "path": "/tmp/s1.1234.session.stdout",
                    "session_id": "s1",
                    "pid": 1234,
                    "size": 100,
                    "mtime": 1700000000.0,
                    "ctime": 1700000000.0,
                }
            ]
        )
        # The row should contain a placeholder; header does not count.
        lines = output.splitlines()
        data_lines = [line for line in lines if "s1" in line and "Project Workspace" not in line]
        self.assertEqual(len(data_lines), 1)
        self.assertIn("-", data_lines[0])

    @patch("cli_topsailai.formatting.os.kill")
    def test_long_project_workspace_preserves_tail(self, mock_kill):
        mock_kill.return_value = None
        long_workspace = "/very/long/中文/workspace/path/project-tail"
        output = self._capture_print_table(
            [
                {
                    "filename": "s1.1234.session.stdout",
                    "path": "/tmp/s1.1234.session.stdout",
                    "session_id": "s1",
                    "pid": 1234,
                    "size": 100,
                    "mtime": 1700000000.0,
                    "ctime": 1700000000.0,
                    "project_workspace": long_workspace,
                }
            ]
        )
        data_line = next(line for line in output.splitlines() if "s1" in line)
        workspace_cell = data_line.split("|")[-1]
        self.assertIn("...", workspace_cell)
        self.assertIn("path/project-tail", workspace_cell)
        self.assertNotIn("/very/long", workspace_cell)
