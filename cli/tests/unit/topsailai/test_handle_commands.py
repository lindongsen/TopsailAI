#!/usr/bin/env python3
"""
Unit tests for command handling in cli_topsailai.
"""

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

import cli_topsailai.state as cli_state
from cli_topsailai.core import prompt_selection


class TestHandleCommands(unittest.TestCase):
    """Tests for prompt_selection command handling."""

    def setUp(self):
        cli_state.current_scope = "workspace"
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
    def test_quit(self, mock_input):
        mock_input.return_value = "q"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")

    @patch("cli_topsailai.core.input")
    def test_help(self, mock_input):
        mock_input.return_value = "help"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "help")

    @patch("cli_topsailai.core.input")
    def test_refresh(self, mock_input):
        mock_input.return_value = "refresh"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "refresh")

    @patch("cli_topsailai.core.input")
    def test_cd_workspace_to_session(self, mock_input):
        cli_state.yaml_commands = [
            {
                "cmd": "/cd {session_id}",
                "scopes": ["workspace"],
                "shell": "",
            }
        ]
        mock_input.return_value = "/cd s1"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")

    @patch("cli_topsailai.core.input")
    def test_cd_session_to_workspace(self, mock_input):
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/cd",
                "scopes": ["session"],
                "shell": "",
            }
        ]
        mock_input.return_value = "/cd"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")

    @patch("cli_topsailai.core.input")
    def test_session_command(self, mock_input):
        files = [
            {"filename": "s1.1234.session.stdout", "session_id": "s1"},
        ]
        mock_input.return_value = "/session 1"
        action, value = prompt_selection(files, "/task")
        self.assertEqual(action, "session")
        self.assertEqual(value, 0)

    @patch("cli_topsailai.core.input")
    def test_stream_command(self, mock_input):
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_input.return_value = "/stream"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "stream")

    @patch("cli_topsailai.core.input")
    def test_retrieve_command(self, mock_input):
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_input.return_value = "/retrieve"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "retrieve")

    @patch("cli_topsailai.core.input")
    def test_clean_command(self, mock_input):
        mock_input.return_value = "/clean"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "clean")

    @patch("cli_topsailai.core.input")
    def test_clean_numbers_command(self, mock_input):
        mock_input.return_value = "/clean 1 2"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "clean_numbers")
        self.assertEqual(value, [0, 1])

    @patch("builtins.print")
    @patch("cli_topsailai.core.input")
    def test_unknown_command(self, mock_input, mock_print):
        mock_input.side_effect = ["/unknown", "q"]
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")
        self.assertTrue(
            any("Unknown command" in str(call) for call in mock_print.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
