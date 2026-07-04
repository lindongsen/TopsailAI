#!/usr/bin/env python3
"""
Unit tests for command handling in cli_topsailai.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

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
    def test_help_with_keyword(self, mock_input):
        mock_input.return_value = "/help ctx"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "help")
        self.assertEqual(value, "ctx")

    @patch("cli_topsailai.core.input")
    def test_help_with_keyword_no_slash(self, mock_input):
        mock_input.return_value = "help ctx"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "help")
        self.assertEqual(value, "ctx")

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


class TestPerCommandHelp(unittest.TestCase):
    """Tests for -h/--help suffix on YAML commands."""

    def setUp(self):
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session"],
                "desc": "Add a by-the-way message",
                "example": "",
                "shell": "",
            },
            {
                "cmd": "/task.run {driver} {args}",
                "scopes": ["session"],
                "desc": "Run task for the session",
                "example": "/task.run ai-team-flow-dev",
                "shell": "{driver} {args}",
            },
        ]
        cli_state.history_manager = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []
        cli_state.history_manager = None
        cli_state._child_processes.clear()

    @patch("cli_topsailai.core.input")
    def test_help_flag_short(self, mock_input):
        mock_input.return_value = "/ctx.btw -h"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "help_cmd")
        self.assertEqual(value.get("cmd"), "/ctx.btw")

    @patch("cli_topsailai.core.input")
    def test_help_flag_long(self, mock_input):
        mock_input.return_value = "/ctx.btw --help"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "help_cmd")
        self.assertEqual(value.get("cmd"), "/ctx.btw")

    @patch("cli_topsailai.core.input")
    def test_help_flag_with_alias(self, mock_input):
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.history",
                "alias": ["history"],
                "scopes": ["session"],
                "desc": "show context messages",
                "example": "",
                "shell": "",
            }
        ]
        mock_input.return_value = "history --help"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "help_cmd")
        self.assertEqual(value.get("cmd"), "/ctx.history")

    @patch("cli_topsailai.core.input")
    def test_help_flag_works_across_scopes(self, mock_input):
        """Help for a session-only command should work from workspace scope."""
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session"],
                "desc": "Add a by-the-way message",
                "example": "",
                "shell": "",
            }
        ]
        mock_input.return_value = "/ctx.btw -h"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "help_cmd")
        self.assertEqual(value.get("cmd"), "/ctx.btw")

    @patch("cli_topsailai.process.run_external_command")
    @patch("cli_topsailai.core.input")
    def test_help_flag_passthrough_for_args_command(
        self, mock_input: MagicMock, mock_run: MagicMock
    ) -> None:
        """--help should be passed through for commands that consume {args}."""
        cli_state.yaml_commands = [
            {
                "cmd": "/echo {args}",
                "description": "Echo arguments",
                "scopes": ["session"],
                "shell": "echo '{args}'",
            }
        ]
        mock_input.return_value = "/echo -h"
        action, value = prompt_selection([], "/tmp")
        self.assertEqual(action, "yaml_handled")
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        self.assertIn("echo", call_args[0][0])
        self.assertIn("-h", call_args[0][0])


if __name__ == "__main__":
    unittest.main()
