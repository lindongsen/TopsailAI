#!/usr/bin/env python3
"""
Unit tests for print helpers and help text in cli_topsailai.
"""

import os
import sys
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
    """Tests for print_table PID display using filename pid + os.kill."""

    def _capture_print_table(self, files):
        captured = StringIO()
        with patch("sys.stdout", new=captured):
            print_table(files)
        return captured.getvalue()

    @patch("cli_topsailai.formatting.os.kill")
    def test_live_pid_shown(self, mock_kill):
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
        self.assertIn("1234", output)
        self.assertIn(Colors.GREEN, output)
        mock_kill.assert_called_once_with(1234, 0)

    @patch("cli_topsailai.formatting.os.kill")
    def test_dead_pid_shows_idle(self, mock_kill):
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
        self.assertNotIn("1234", output)
        self.assertIn("-", output)
        self.assertIn(Colors.GRAY, output)

    def test_missing_pid_shows_idle(self):
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
        self.assertIn("-", output)
        self.assertIn(Colors.GRAY, output)


if __name__ == "__main__":
    unittest.main()
