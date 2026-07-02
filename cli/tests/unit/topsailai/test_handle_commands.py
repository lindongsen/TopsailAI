#!/usr/bin/env python3
"""
Unit tests for handle_yaml_command in topsailai.py.

Covers:
- handle_yaml_command() for /cd, /env.get, /env.set, external shell commands
- Error handling in command execution
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestHandleYamlCommand(unittest.TestCase):
    """Tests for handle_yaml_command."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli._child_processes.clear()

    @patch("builtins.print")
    def test_cd_enter_session(self, mock_print):
        """Enter session scope with /cd."""
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": "my-session"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        self.assertEqual(cli.current_scope, "session")
        self.assertEqual(cli.current_session_id, "my-session")

    @patch("builtins.print")
    def test_cd_exit_session(self, mock_print):
        """Exit to workspace scope with /cd and no session_id."""
        cli.current_scope = "session"
        cli.current_session_id = "my-session"
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": ""}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        self.assertEqual(cli.current_scope, "workspace")
        self.assertIsNone(cli.current_session_id)

    @patch("topsailai.discover_log_files")
    @patch("builtins.print")
    def test_cd_with_numeric_index(self, mock_print, mock_discover):
        """Enter session scope with /cd using numeric index."""
        mock_discover.return_value = [
            {"filename": "session-abc.1234.session.stdout", "session_id": "session-abc"},
            {"filename": "session-xyz.5678.session.stdout", "session_id": "session-xyz"},
        ]
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": "2", "task_dir": "/tmp/tasks"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        self.assertEqual(cli.current_scope, "session")
        self.assertEqual(cli.current_session_id, "session-xyz")

    @patch("topsailai.discover_log_files")
    @patch("builtins.print")
    def test_cd_with_numeric_index_out_of_range(self, mock_print, mock_discover):
        """Show error for out-of-range numeric index."""
        mock_discover.return_value = [
            {"filename": "session-abc.1234.session.stdout", "session_id": "session-abc"},
        ]
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": "5", "task_dir": "/tmp/tasks"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        self.assertEqual(cli.current_scope, "workspace")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Invalid number" in p for p in printed))

    @patch("topsailai.discover_log_files")
    @patch("builtins.print")
    def test_cd_with_numeric_index_temp_session(self, mock_print, mock_discover):
        """Show error when numeric index points to temp session."""
        mock_discover.return_value = [
            {"filename": "1234.session.stdout", "session_id": "(temp)"},
        ]
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": "1", "task_dir": "/tmp/tasks"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        self.assertEqual(cli.current_scope, "workspace")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("No session ID available" in p for p in printed))
    @patch("builtins.print")
    def test_cd_with_session_id_string(self, mock_print):
        """Enter session scope with /cd using session_id string."""
        instruction = {"cmd": "/cd {session_id}", "shell": ""}
        variables = {"session_id": "20260520T105654", "task_dir": "/tmp/tasks"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        self.assertEqual(cli.current_scope, "session")
        self.assertEqual(cli.current_session_id, "20260520T105654")

    @patch.dict(os.environ, {}, clear=True)
    @patch("builtins.print")
    def test_env_get(self, mock_print):
        """Get environment variable."""
        os.environ["TEST_VAR"] = "test_value"
        instruction = {"cmd": "/env.get {key}", "shell": ""}
        variables = {"key": "TEST_VAR"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("TEST_VAR=test_value" in p for p in printed))

    @patch("builtins.print")
    def test_env_get_empty_key(self, mock_print):
        """Show error when key is empty."""
        instruction = {"cmd": "/env.get {key}", "shell": ""}
        variables = {"key": ""}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Usage: /env.get" in p for p in printed))

    @patch.dict(os.environ, {}, clear=True)
    @patch("builtins.print")
    def test_env_set(self, mock_print):
        """Set environment variable."""
        instruction = {"cmd": "/env.set {key} {value}", "shell": ""}
        variables = {"key": "NEW_VAR", "value": "new_value"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        self.assertEqual(os.environ.get("NEW_VAR"), "new_value")

    @patch("builtins.print")
    def test_env_set_empty_key(self, mock_print):
        """Show error when key is empty for env.set."""
        instruction = {"cmd": "/env.set {key} {value}", "shell": ""}
        variables = {"key": "", "value": "val"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Usage: /env.set" in p for p in printed))

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_external_shell_command(self, mock_print, mock_popen):
        """Execute external shell command."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("output\n", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {"cmd": "/test", "shell": "echo hello"}
        variables = {}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        mock_popen.assert_called_once()

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_external_shell_with_variables(self, mock_print, mock_popen):
        """Substitute variables in shell command."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {"cmd": "/test {name}", "shell": "echo {name}"}
        variables = {"name": "world"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        args = mock_popen.call_args.args[0]
        self.assertIn("world", args)

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_external_shell_stderr(self, mock_print, mock_popen):
        """Print stderr in red."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error msg")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        instruction = {"cmd": "/test", "shell": "echo hello"}
        result = cli.handle_yaml_command(instruction, {})
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("error msg" in p for p in printed))

    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_external_shell_exception(self, mock_print, mock_popen):
        """Handle exception from subprocess."""
        mock_popen.side_effect = OSError("command not found")

        instruction = {"cmd": "/test", "shell": "badcmd"}
        result = cli.handle_yaml_command(instruction, {})
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Failed to execute" in p for p in printed))

    @patch("builtins.print")
    def test_unimplemented_internal(self, mock_print):
        """Warn for unimplemented internal command."""
        instruction = {"cmd": "/unknown", "shell": ""}
        result = cli.handle_yaml_command(instruction, {})
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("not implemented" in p for p in printed))

    @patch("builtins.input")
    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_ctx_add_msg_with_initial(self, mock_print, mock_popen, mock_input):
        """Handle /ctx.add_msg with initial message."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        cli.current_session_id = "s1"
        instruction = {"cmd": "/ctx.add_msg", "shell": "cmd -s '{session_id}' -m '{message}'"}
        variables = {"message": "hello"}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        mock_input.assert_not_called()

    @patch("builtins.input", side_effect=["line1", "line2", EOFError()])
    @patch("topsailai.subprocess.Popen")
    @patch("builtins.print")
    def test_ctx_add_msg_interactive(self, mock_print, mock_popen, mock_input):
        """Handle /ctx.add_msg in interactive mode."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        cli.current_session_id = "s1"
        instruction = {"cmd": "/ctx.add_msg", "shell": "cmd -s '{session_id}' -m '{message}'"}
        variables = {"message": ""}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")

    @patch("builtins.input", side_effect=KeyboardInterrupt())
    @patch("builtins.print")
    def test_ctx_add_msg_cancelled(self, mock_print, mock_input):
        """Handle /ctx.add_msg cancelled by Ctrl+C."""
        cli.current_session_id = "s1"
        instruction = {"cmd": "/ctx.add_msg", "shell": "cmd -s '{session_id}' -m '{message}'"}
        variables = {"message": ""}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("Cancelled" in p for p in printed))

    @patch("builtins.input", side_effect=[EOFError()])
    @patch("builtins.print")
    def test_ctx_add_msg_empty(self, mock_print, mock_input):
        """Handle /ctx.add_msg with empty message."""
        cli.current_session_id = "s1"
        instruction = {"cmd": "/ctx.add_msg", "shell": "cmd -s '{session_id}' -m '{message}'"}
        variables = {"message": ""}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("cannot be empty" in p for p in printed))

    @patch("builtins.input", side_effect=[EOFError()])
    @patch("builtins.print")
    def test_ctx_add_msg_strip_quotes(self, mock_print, mock_input):
        """Strip surrounding quotes from empty quoted strings."""
        cli.current_session_id = "s1"
        instruction = {"cmd": "/ctx.add_msg", "shell": ""}
        variables = {"message": '""'}
        result = cli.handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")


if __name__ == "__main__":
    unittest.main()
