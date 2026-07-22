#!/usr/bin/env python3
"""
Unit tests for YAML command loading in cli_topsailai.
"""

import json
import os
import subprocess
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

import cli_topsailai.state as cli_state
from cli_topsailai.yaml_commands import (
    handle_yaml_command,
    load_yaml_commands,
    match_yaml_command,
)


class TestYamlCommands(unittest.TestCase):
    """Tests for YAML command loading."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def test_load_yaml_commands_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "commands.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("commands:\n")
            commands = load_yaml_commands(path)
            self.assertIsInstance(commands, list)

    def test_load_yaml_commands_missing(self):
        commands = load_yaml_commands("/nonexistent/path.yaml")
        self.assertEqual(commands, [])


class TestMatchYamlCommand(unittest.TestCase):
    """Tests for match_yaml_command regex matching."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def test_agent_without_args_matches_yaml(self):
        """Bare /agent in workspace scope must match the YAML /agent command."""
        cli_state.current_scope = "workspace"
        cli_state.yaml_commands = [
            {
                "cmd": "/agent",
                "scopes": ["workspace"],
                "shell": "topsailai_agent_chats",
            }
        ]
        result = match_yaml_command("/agent", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/agent")

        result = match_yaml_command("agent", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/agent")

    def test_agent_with_args_does_not_match_yaml(self):
        """/agent with arguments must not match the no-variable YAML /agent command."""
        cli_state.current_scope = "workspace"
        cli_state.yaml_commands = [
            {
                "cmd": "/agent",
                "scopes": ["workspace"],
                "shell": "topsailai_agent_chats",
            }
        ]
        self.assertIsNone(match_yaml_command("/agent /path/to/project", "/task"))
        self.assertIsNone(match_yaml_command("agent /path/to/project", "/task"))
        self.assertIsNone(match_yaml_command("/agent 3", "/task"))
        self.assertIsNone(match_yaml_command("agent 3", "/task"))

    def test_variable_command_still_matches_with_args(self):
        """Commands with variable placeholders must continue to accept arguments."""
        cli_state.current_scope = "workspace"
        cli_state.yaml_commands = [
            {
                "cmd": "/cd {session_id}",
                "scopes": ["workspace"],
                "shell": "",
            }
        ]
        result = match_yaml_command("/cd 2", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/cd {session_id}")
        self.assertEqual(result[1].get("session_id"), "2")

    def test_message_command_still_matches_with_args(self):
        """Message commands without placeholders must continue to accept trailing text."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session"],
                "shell": "topsailai_session_add_agent2llm_message -s '{session_id}' -m '{message}'",
            }
        ]
        result = match_yaml_command("/ctx.btw hello world", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/ctx.btw")
        self.assertEqual(result[1].get("message"), "hello world")


class TestGitStatusCommand(unittest.TestCase):
    """Tests for the /git.status session-scope command."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _git_status_instruction(self):
        return {
            "cmd": "/git.status",
            "scopes": ["session"],
            "shell": "git -C '{project_workspace}' status",
        }

    def test_git_status_matches_in_session_scope(self):
        """/git.status must match in session scope."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_status_instruction()]
        result = match_yaml_command("/git.status", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git.status")

    def test_git_status_does_not_match_in_workspace_scope(self):
        """/git.status must not match in workspace scope."""
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = [self._git_status_instruction()]
        self.assertIsNone(match_yaml_command("/git.status", "/task"))

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.process.run_external_command")
    def test_git_status_resolves_project_workspace(
        self, mock_run_external, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace and runs git status."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": "/workspace/project"}),
            stderr="",
        )

        instruction = self._git_status_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_subprocess_run.assert_called_once_with(
            ["topsailai_session_info", "--json", "s1"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        mock_run_external.assert_called_once()
        called_cmd_list = mock_run_external.call_args[0][0]
        self.assertEqual(called_cmd_list, ["git", "-C", "/workspace/project", "status"])

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_git_status_missing_project_workspace(
        self, mock_print_error, mock_subprocess_run
    ):
        """handle_yaml_command errors when project_workspace is missing."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": ""}),
            stderr="",
        )

        instruction = self._git_status_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_print_error.assert_called_once()
        self.assertIn("no project workspace", mock_print_error.call_args[0][0])

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_git_status_session_info_nonzero_exit(
        self, mock_print_error, mock_subprocess_run
    ):
        """handle_yaml_command errors when topsailai_session_info fails."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=1,
            stdout="",
            stderr="not found",
        )

        instruction = self._git_status_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_print_error.assert_called_once()
        self.assertIn("Failed to resolve project workspace", mock_print_error.call_args[0][0])

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_git_status_session_info_invalid_json(
        self, mock_print_error, mock_subprocess_run
    ):
        """handle_yaml_command errors when topsailai_session_info returns invalid JSON."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout="not-json",
            stderr="",
        )

        instruction = self._git_status_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_print_error.assert_called_once()
        self.assertIn("Failed to resolve project workspace", mock_print_error.call_args[0][0])


class TestGitDiffCommand(unittest.TestCase):
    """Tests for the /git.diff session-scope command."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _git_diff_instruction(self):
        return {
            "cmd": "/git.diff",
            "scopes": ["session"],
            "shell": "git -C \'{project_workspace}\' diff",
        }

    def test_git_diff_matches_in_session_scope(self):
        """/git.diff must match in session scope."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_diff_instruction()]
        result = match_yaml_command("/git.diff", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git.diff")

    def test_git_diff_does_not_match_in_workspace_scope(self):
        """/git.diff must not match in workspace scope."""
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = [self._git_diff_instruction()]
        self.assertIsNone(match_yaml_command("/git.diff", "/task"))

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.process.run_external_command")
    def test_git_diff_resolves_project_workspace(
        self, mock_run_external, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace and runs git diff."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": "/workspace/project"}),
            stderr="",
        )

        instruction = self._git_diff_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_subprocess_run.assert_called_once_with(
            ["topsailai_session_info", "--json", "s1"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        mock_run_external.assert_called_once()
        called_cmd_list = mock_run_external.call_args[0][0]
        self.assertEqual(called_cmd_list, ["git", "-C", "/workspace/project", "diff"])

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_git_diff_missing_project_workspace(
        self, mock_print_error, mock_subprocess_run
    ):
        """handle_yaml_command errors when project_workspace is missing."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": ""}),
            stderr="",
        )

        instruction = self._git_diff_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_print_error.assert_called_once()
        self.assertIn("no project workspace", mock_print_error.call_args[0][0])

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_git_diff_session_info_nonzero_exit(
        self, mock_print_error, mock_subprocess_run
    ):
        """handle_yaml_command errors when topsailai_session_info fails."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=1,
            stdout="",
            stderr="not found",
        )

        instruction = self._git_diff_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_print_error.assert_called_once()
        self.assertIn("Failed to resolve project workspace", mock_print_error.call_args[0][0])

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_git_diff_session_info_invalid_json(
        self, mock_print_error, mock_subprocess_run
    ):
        """handle_yaml_command errors when topsailai_session_info returns invalid JSON."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout="not-json",
            stderr="",
        )

        instruction = self._git_diff_instruction()
        variables = {"session_id": "s1", "task_dir": "/task"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_print_error.assert_called_once()
        self.assertIn("Failed to resolve project workspace", mock_print_error.call_args[0][0])

if __name__ == "__main__":
    unittest.main()
