#!/usr/bin/env python3
"""
Unit tests for /ctx.add_msg command handling in topsailai.py.

Covers:
- match_yaml_command() for /ctx.add_msg
- handle_yaml_command() for /ctx.add_msg
  - with initial message
  - with empty initial message (interactive multi-line input)
  - with quoted empty string
  - with Ctrl+D (EOFError)
  - with Ctrl+C (KeyboardInterrupt)
  - with empty message after input
  - subprocess execution and error handling
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestCtxAddMsgMatch(unittest.TestCase):
    """Tests for match_yaml_command with /ctx.add_msg."""

    def setUp(self):
        self.original_commands = cli.yaml_commands
        cli.yaml_commands = [
            {
                "cmd": "/ctx.add_msg",
                "scopes": ["session"],
                "desc": "Add message to context",
                "shell": "topsailai_session_add_message -s '{session_id}' -m '{message}'",
            }
        ]
        self.original_scope = cli.current_scope
        cli.current_scope = "session"
        self.original_session_id = cli.current_session_id
        cli.current_session_id = "test-session"

    def tearDown(self):
        cli.yaml_commands = self.original_commands
        cli.current_scope = self.original_scope
        cli.current_session_id = self.original_session_id

    def test_match_with_message(self):
        """Match /ctx.add_msg with a message."""
        result = cli.match_yaml_command("/ctx.add_msg hello world")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(instruction["cmd"], "/ctx.add_msg")
        self.assertEqual(variables["message"], "hello world")

    def test_match_without_message(self):
        """Match /ctx.add_msg without a message."""
        result = cli.match_yaml_command("/ctx.add_msg")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(instruction["cmd"], "/ctx.add_msg")
        self.assertEqual(variables["message"], "")

    def test_match_multiline_message(self):
        """Match /ctx.add_msg with multiline message."""
        result = cli.match_yaml_command("/ctx.add_msg line1\nline2\nline3")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["message"], "line1\nline2\nline3")

    def test_no_match_in_workspace_scope(self):
        """Do not match when scope is workspace."""
        cli.current_scope = "workspace"
        result = cli.match_yaml_command("/ctx.add_msg hello")
        self.assertIsNone(result)


class TestCtxAddMsgHandle(unittest.TestCase):
    """Tests for handle_yaml_command with /ctx.add_msg."""

    def setUp(self):
        self.original_commands = cli.yaml_commands
        cli.yaml_commands = [
            {
                "cmd": "/ctx.add_msg",
                "scopes": ["session"],
                "desc": "Add message to context",
                "shell": "topsailai_session_add_message -s '{session_id}' -m '{message}'",
            }
        ]
        self.original_scope = cli.current_scope
        cli.current_scope = "session"
        self.original_session_id = cli.current_session_id
        cli.current_session_id = "test-session"

    def tearDown(self):
        cli.yaml_commands = self.original_commands
        cli.current_scope = self.original_scope
        cli.current_session_id = self.original_session_id
        cli._child_processes.clear()

    def _make_instruction(self):
        return cli.yaml_commands[0]

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_handle_with_initial_message(self, mock_print, mock_popen):
        """Handle /ctx.add_msg with an initial message."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = self._make_instruction()
        result = cli.handle_yaml_command(instruction, {"message": "hello world"})
        self.assertEqual(result, "yaml_handled")
        mock_popen.assert_called_once()
        args = mock_popen.call_args.args[0]
        self.assertIn("hello", args)
        self.assertIn("world", args)

    @patch("builtins.input")
    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_handle_empty_message_interactive(self, mock_print, mock_popen, mock_input):
        """Handle /ctx.add_msg with empty initial message (interactive mode)."""
        mock_input.side_effect = ["line1", "line2", EOFError()]
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = self._make_instruction()
        result = cli.handle_yaml_command(instruction, {"message": ""})
        self.assertEqual(result, "yaml_handled")
        mock_popen.assert_called_once()
        args = mock_popen.call_args.args[0]
        self.assertIn("line1", args)
        self.assertIn("line2", args)

    @patch("builtins.input")
    @patch("builtins.print")
    def test_handle_empty_message_after_input(self, mock_print, mock_input):
        """Handle /ctx.add_msg when user provides only empty lines."""
        mock_input.side_effect = ["", "", EOFError()]

        instruction = self._make_instruction()
        result = cli.handle_yaml_command(instruction, {"message": ""})
        self.assertEqual(result, "yaml_handled")
        mock_print.assert_any_call(
            f"{cli.Colors.RED}[ERROR] Message cannot be empty.{cli.Colors.RESET}"
        )

    @patch("builtins.input")
    @patch("builtins.print")
    def test_handle_keyboard_interrupt(self, mock_print, mock_input):
        """Handle /ctx.add_msg when user presses Ctrl+C during input."""
        mock_input.side_effect = KeyboardInterrupt()

        instruction = self._make_instruction()
        result = cli.handle_yaml_command(instruction, {"message": ""})
        self.assertEqual(result, "yaml_handled")
        mock_print.assert_any_call(
            f"{cli.Colors.YELLOW}[INFO] Cancelled.{cli.Colors.RESET}"
        )

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_handle_subprocess_error(self, mock_print, mock_popen):
        """Handle subprocess execution error."""
        mock_popen.side_effect = OSError("command not found")

        instruction = self._make_instruction()
        result = cli.handle_yaml_command(instruction, {"message": "hello"})
        self.assertEqual(result, "yaml_handled")
        mock_print.assert_any_call(
            f"{cli.Colors.RED}[ERROR] Failed to execute command: command not found{cli.Colors.RESET}"
        )

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_handle_subprocess_stderr(self, mock_print, mock_popen):
        """Handle subprocess with stderr output."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error message")
        mock_proc.poll.return_value = 1
        mock_popen.return_value = mock_proc

        instruction = self._make_instruction()
        result = cli.handle_yaml_command(instruction, {"message": "hello"})
        self.assertEqual(result, "yaml_handled")
        mock_print.assert_any_call(
            f"{cli.Colors.RED}error message{cli.Colors.RESET}", end=""
        )

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_handle_strip_quotes(self, mock_print, mock_popen):
        """Handle /ctx.add_msg with quoted string strips quotes."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = self._make_instruction()
        result = cli.handle_yaml_command(instruction, {"message": '"hello"'})
        self.assertEqual(result, "yaml_handled")
        args = mock_popen.call_args.args[0]
        self.assertIn("hello", args)
if __name__ == "__main__":
    unittest.main()
