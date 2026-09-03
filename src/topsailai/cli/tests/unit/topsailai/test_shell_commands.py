#!/usr/bin/env python3
"""Unit tests for interactive ``!`` shell commands."""

import shlex
import unittest
from unittest.mock import patch

import cli_topsailai.state as cli_state
from cli_topsailai.core import prompt_selection
from cli_topsailai.shell_commands import execute_shell_command
from topsailai.utils.env_tool import resolve_python_interpreter


class TestExecuteShellCommand(unittest.TestCase):
    """Tests for shell execution and result reporting."""

    @patch("cli_topsailai.shell_commands.run_external_command")
    def test_executes_via_os_system_like_git(self, mock_run):
        """! must delegate to the shared /git execution path (use_os_system)."""
        result = execute_shell_command("!git status")

        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            ["git", "status"],
            {},
            independent=False,
            async_cmd=False,
            use_os_system=True,
        )

    @patch("cli_topsailai.shell_commands.run_external_command")
    def test_parses_quoted_arguments(self, mock_run):
        """Quoted arguments must survive shell-like parsing."""
        result = execute_shell_command('!echo "hello world"')

        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            ["echo", "hello world"],
            {},
            independent=False,
            async_cmd=False,
            use_os_system=True,
        )

    @patch("cli_topsailai.shell_commands.run_external_command")
    def test_rejects_empty_command(self, mock_run):
        """A bare ! must print usage and not launch a command."""
        with patch("cli_topsailai.shell_commands.print_error") as mock_error:
            result = execute_shell_command("!   ")

        self.assertEqual(result, 1)
        mock_run.assert_not_called()
        mock_error.assert_called_once_with("Usage: !<command>")

    @patch("cli_topsailai.shell_commands.run_external_command")
    def test_reports_parse_error(self, mock_run):
        """An unparsable command line must be reported without execution."""
        with patch("cli_topsailai.shell_commands.print_error") as mock_error:
            result = execute_shell_command('!echo "unterminated')

        self.assertEqual(result, 1)
        mock_run.assert_not_called()
        self.assertIn("Failed to parse command", mock_error.call_args.args[0])

    @patch("cli_topsailai.shell_commands.run_external_command")
    def test_reports_execution_error(self, mock_run):
        """A launch failure must be surfaced as an error."""
        mock_run.side_effect = OSError("unavailable")

        with patch("cli_topsailai.shell_commands.print_error") as mock_error:
            result = execute_shell_command("!echo hello")

        self.assertEqual(result, 1)
        self.assertIn("Failed to execute command", mock_error.call_args.args[0])


def test_real_execution_inherits_cwd_environment_and_reports_status(
    tmp_path, monkeypatch, capfd
):
    """The real os.system path must expose inherited cwd, env, and status."""
    interpreter = resolve_python_interpreter()
    marker = "bang-shell-real-execution"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOPSAILAI_BANG_TEST_MARKER", marker)
    script = (
        "import os, pathlib, sys; "
        "print(pathlib.Path.cwd()); "
        "print(os.environ['TOPSAILAI_BANG_TEST_MARKER']); "
        "sys.exit(7)"
    )
    command = "!{} -c {}".format(shlex.quote(interpreter), shlex.quote(script))

    result = execute_shell_command(command)
    output = capfd.readouterr()

    assert result == 0
    assert str(tmp_path) in output.out
    assert marker in output.out
    assert "Executing (os.system):" in output.out
    assert "Command exited with code" in output.out
    assert "Execution completed." in output.out


class TestShellCommandScopes(unittest.TestCase):
    """Tests that the central prompt accepts shell commands in every scope it owns."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.current_doc_filename = None
        cli_state.workspace_showing_managed_projects = False
        cli_state.yaml_commands = []
        cli_state.history_manager = None

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.current_doc_filename = None
        cli_state.workspace_showing_managed_projects = False
        cli_state.yaml_commands = []
        cli_state.history_manager = None

    @patch("cli_topsailai.shell_commands.execute_shell_command")
    @patch("cli_topsailai.core._read_input_with_prompt")
    def test_available_in_non_runtime_scopes(self, mock_input, mock_execute):
        for scope in ("workspace", "project", "session", "doc"):
            with self.subTest(scope=scope):
                cli_state.current_scope = scope
                cli_state.current_session_id = "s1" if scope == "session" else None
                cli_state.current_doc_filename = "topsailai.md" if scope == "doc" else None
                mock_input.side_effect = ["!git status", "q"]

                action, value = prompt_selection([], "/task")

                self.assertEqual(
                    (action, value),
                    ("leave_scope", None) if scope == "doc" else ("quit", None),
                )
                mock_execute.assert_called_once_with("!git status")
                mock_execute.reset_mock()

    @patch("cli_topsailai.shell_commands.execute_shell_command")
    @patch("cli_topsailai.core._read_input_with_prompt")
    def test_available_in_managed_project_list(self, mock_input, mock_execute):
        cli_state.workspace_showing_managed_projects = True
        mock_input.side_effect = ["!git status", "q"]

        self.assertEqual(prompt_selection([], "/task"), ("quit", None))
        mock_execute.assert_called_once_with("!git status")


if __name__ == "__main__":
    unittest.main()
