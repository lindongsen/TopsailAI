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
    build_command_env,
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


class TestControlCommand(unittest.TestCase):
    """Tests for runtime control-command matching and dispatch."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _control_instruction(self):
        return {
            "cmd": "/control {command} {args}",
            "scopes": ["session", "runtime"],
            "shell": "topsailai_send_control -s '{session_id}' -c '{command}' -a '{args}'",
        }

    def test_control_matches_without_optional_args(self):
        """The control payload may be omitted and defaults to an empty string."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._control_instruction()]

        result = match_yaml_command("/control hard_interrupt", "/task")

        self.assertIsNotNone(result)
        self.assertEqual(result[1].get("command"), "hard_interrupt")
        self.assertEqual(result[1].get("args"), "")

    @patch("cli_topsailai.process.run_external_command")
    def test_control_preserves_json_args_as_one_argument(self, mock_run):
        """JSON payload syntax must survive command-list construction unchanged."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        instruction = self._control_instruction()
        variables = {
            "session_id": "s1",
            "task_dir": "/task",
            "command": "hard_interrupt",
            "args": '{"reason":"timeout"}',
        }

        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        command = mock_run.call_args[0][0]
        self.assertEqual(command[-2:], ["-a", '{"reason":"timeout"}'])

    def _subcommand_instruction(self, cmd):
        return {
            "cmd": cmd,
            "scopes": ["session", "runtime"],
            "shell": "topsailai_send_control -s '{session_id}' -c 'dummy' -a '{args}'",
        }

    def test_control_hard_interrupt_subcommand_matches(self):
        """/control.hard_interrupt must match as a fixed subcommand."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._subcommand_instruction("/control.hard_interrupt")]
        result = match_yaml_command("/control.hard_interrupt", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/control.hard_interrupt")

    def test_control_soft_interrupt_subcommand_matches(self):
        """/control.soft_interrupt must match and extract optional args."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._subcommand_instruction("/control.soft_interrupt {args}")]
        result = match_yaml_command("/control.soft_interrupt", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/control.soft_interrupt {args}")
        self.assertEqual(result[1].get("args"), "")

        result = match_yaml_command("/control.soft_interrupt {\"reason\":\"timeout\"}", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[1].get("args"), '{"reason":"timeout"}')

    def test_control_clear_interrupt_subcommand_matches(self):
        """/control.clear_interrupt must match as a fixed subcommand."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._subcommand_instruction("/control.clear_interrupt")]
        result = match_yaml_command("/control.clear_interrupt", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/control.clear_interrupt")

    def test_control_get_runtime_messages_subcommand_matches(self):
        """/control.get_runtime_messages must match as a fixed subcommand."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._subcommand_instruction("/control.get_runtime_messages")]
        result = match_yaml_command("/control.get_runtime_messages", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/control.get_runtime_messages")

    def test_control_call_instruction_subcommand_matches(self):
        """/control.call_instruction must match and extract JSON args."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._subcommand_instruction("/control.call_instruction {args}")]
        result = match_yaml_command(
            "/control.call_instruction {\"instruction\":\"ctx.history\"}", "/task"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/control.call_instruction {args}")
        self.assertEqual(result[1].get("args"), '{"instruction":"ctx.history"}')

    @patch("cli_topsailai.process.run_external_command")
    def test_control_subcommand_preserves_json_args(self, mock_run):
        """Subcommand JSON payload must survive command-list construction unchanged."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        instruction = self._subcommand_instruction("/control.call_instruction {args}")
        variables = {
            "session_id": "s1",
            "task_dir": "/task",
            "args": '{"instruction":"ctx.history"}',
        }
        result = handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        command = mock_run.call_args[0][0]
        self.assertEqual(command[-2:], ["-a", '{"instruction":"ctx.history"}'])

    @patch("cli_topsailai.process.run_external_command")
    def test_control_generic_path_backward_compatible(self, mock_run):
        """The generic /control {command} {args} path must remain usable."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        instruction = self._control_instruction()
        variables = {
            "session_id": "s1",
            "task_dir": "/task",
            "command": "call_instruction",
            "args": '{"instruction":"ctx.history"}',
        }
        result = handle_yaml_command(instruction, variables)
        self.assertEqual(result, "yaml_handled")
        command = mock_run.call_args[0][0]
        self.assertEqual(command[-4:], ["-c", "call_instruction", "-a", '{"instruction":"ctx.history"}'])


class TestCallInstructionWizard(unittest.TestCase):
    """Tests for the interactive call_instruction wizard."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    @patch("cli_topsailai.yaml_commands.input", side_effect=["ctx.history", "arg1", "", "key=value", ""])
    def test_wizard_builds_payload(self, mock_input):
        """Wizard assembles instruction + args + kwargs into a JSON payload."""
        from cli_topsailai.yaml_commands import _prompt_call_instruction_wizard
        result = _prompt_call_instruction_wizard()
        self.assertEqual(
            result,
            '{"instruction": "ctx.history", "args": ["arg1"], "kwargs": {"key": "value"}}',
        )

    @patch("cli_topsailai.yaml_commands.input", side_effect=["ctx.history", "", ""])
    def test_wizard_only_instruction(self, mock_input):
        """Wizard with no args/kwargs returns instruction-only payload."""
        from cli_topsailai.yaml_commands import _prompt_call_instruction_wizard
        result = _prompt_call_instruction_wizard()
        self.assertEqual(result, '{"instruction": "ctx.history"}')

    @patch("cli_topsailai.yaml_commands.input", side_effect=[""])
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_wizard_empty_instruction_returns_none(self, mock_print_error, mock_input):
        """Empty instruction must return None and print an error."""
        from cli_topsailai.yaml_commands import _prompt_call_instruction_wizard
        result = _prompt_call_instruction_wizard()
        self.assertIsNone(result)
        mock_print_error.assert_called_once()

    @patch("cli_topsailai.yaml_commands.input", side_effect=KeyboardInterrupt)
    @patch("cli_topsailai.yaml_commands.print_warning")
    def test_wizard_ctrl_c_cancels(self, mock_print_warning, mock_input):
        """Ctrl+C during the first prompt must cancel and return None."""
        from cli_topsailai.yaml_commands import _prompt_call_instruction_wizard
        result = _prompt_call_instruction_wizard()
        self.assertIsNone(result)
        mock_print_warning.assert_called_once()

    @patch("cli_topsailai.yaml_commands.input", side_effect=["ctx.history", "", "badline", ""])
    @patch("cli_topsailai.yaml_commands.print_warning")
    def test_wizard_ignores_invalid_kwarg(self, mock_print_warning, mock_input):
        """A kwarg line without '=' must be ignored with a warning."""
        from cli_topsailai.yaml_commands import _prompt_call_instruction_wizard
        result = _prompt_call_instruction_wizard()
        self.assertEqual(result, '{"instruction": "ctx.history"}')
        mock_print_warning.assert_called_once()


class TestGitStatusCommand(unittest.TestCase):
    """Tests for the /git.status session-scope and runtime-scope command."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _git_status_instruction(self):
        return {
            "cmd": "/git.status",
            "scopes": ["session", "runtime"],
            "shell": "git -C '{project_workspace}' status",
            "use_os_system": 1,
        }

    def test_git_status_matches_in_session_scope(self):
        """/git.status must match in session scope."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_status_instruction()]
        result = match_yaml_command("/git.status", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git.status")

    def test_git_status_matches_in_runtime_scope(self):
        """/git.status must match in runtime scope."""
        cli_state.current_scope = "runtime"
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
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_status_resolves_project_workspace(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace and runs git status via os.system."""
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
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("status", called_cmd)

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_status_resolves_project_workspace_in_runtime_scope(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace in runtime scope and runs git status via os.system."""
        cli_state.current_scope = "runtime"
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
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("status", called_cmd)

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
    """Tests for the /git.diff session-scope and runtime-scope command."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _git_diff_instruction(self):
        return {
            "cmd": "/git.diff",
            "scopes": ["session", "runtime"],
            "shell": "git -C \\'{project_workspace}\\' diff",
            "use_os_system": 1,
        }

    def test_git_diff_matches_in_session_scope(self):
        """/git.diff must match in session scope."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_diff_instruction()]
        result = match_yaml_command("/git.diff", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git.diff")

    def test_git_diff_matches_in_runtime_scope(self):
        """/git.diff must match in runtime scope."""
        cli_state.current_scope = "runtime"
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
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_diff_resolves_project_workspace(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace and runs git diff via os.system."""
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
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("diff", called_cmd)

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_diff_resolves_project_workspace_in_runtime_scope(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace in runtime scope and runs git diff via os.system."""
        cli_state.current_scope = "runtime"
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
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("diff", called_cmd)

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


class TestGitCommand(unittest.TestCase):
    """Tests for the flexible /git session-scope and runtime-scope command."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _git_instruction(self):
        return {
            "cmd": "/git {args}",
            "scopes": ["session", "runtime"],
            "shell": "git -C '{project_workspace}' {args}",
            "use_os_system": 1,
        }

    def test_git_status_matches_in_session_scope(self):
        """/git status must match in session scope and extract args."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_instruction()]
        result = match_yaml_command("/git status", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git {args}")
        self.assertEqual(result[1].get("args"), "status")

    def test_git_status_matches_in_runtime_scope(self):
        """/git status must match in runtime scope and extract args."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_instruction()]
        result = match_yaml_command("/git status", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git {args}")
        self.assertEqual(result[1].get("args"), "status")

    def test_git_diff_cached_matches_in_session_scope(self):
        """/git diff --cached must match and preserve all arguments."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_instruction()]
        result = match_yaml_command("/git diff --cached", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git {args}")
        self.assertEqual(result[1].get("args"), "diff --cached")

    def test_git_diff_cached_matches_in_runtime_scope(self):
        """/git diff --cached must match in runtime scope and preserve all arguments."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_instruction()]
        result = match_yaml_command("/git diff --cached", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git {args}")
        self.assertEqual(result[1].get("args"), "diff --cached")

    def test_git_log_oneline_matches_in_session_scope(self):
        """/git log --oneline -10 must match and preserve all arguments."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_instruction()]
        result = match_yaml_command("/git log --oneline -10", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git {args}")
        self.assertEqual(result[1].get("args"), "log --oneline -10")

    def test_git_log_oneline_matches_in_runtime_scope(self):
        """/git log --oneline -10 must match in runtime scope and preserve all arguments."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        cli_state.yaml_commands = [self._git_instruction()]
        result = match_yaml_command("/git log --oneline -10", "/task")
        self.assertIsNotNone(result)
        self.assertEqual(result[0].get("cmd"), "/git {args}")
        self.assertEqual(result[1].get("args"), "log --oneline -10")

    def test_git_does_not_match_in_workspace_scope(self):
        """/git must not match in workspace scope."""
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = [self._git_instruction()]
        self.assertIsNone(match_yaml_command("/git status", "/task"))

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_status_resolves_project_workspace(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace and runs git status via os.system."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": "/workspace/project"}),
            stderr="",
        )

        instruction = self._git_instruction()
        variables = {"session_id": "s1", "task_dir": "/task", "args": "status"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_subprocess_run.assert_called_once_with(
            ["topsailai_session_info", "--json", "s1"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("status", called_cmd)

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_status_resolves_project_workspace_in_runtime_scope(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace in runtime scope and runs git status via os.system."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": "/workspace/project"}),
            stderr="",
        )

        instruction = self._git_instruction()
        variables = {"session_id": "s1", "task_dir": "/task", "args": "status"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_subprocess_run.assert_called_once_with(
            ["topsailai_session_info", "--json", "s1"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("status", called_cmd)

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_diff_cached_resolves_project_workspace(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace and runs git diff --cached via os.system."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": "/workspace/project"}),
            stderr="",
        )

        instruction = self._git_instruction()
        variables = {"session_id": "s1", "task_dir": "/task", "args": "diff --cached"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("diff --cached", called_cmd)

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.os.system")
    def test_git_diff_cached_resolves_project_workspace_in_runtime_scope(
        self, mock_os_system, mock_subprocess_run
    ):
        """handle_yaml_command resolves project_workspace in runtime scope and runs git diff --cached via os.system."""
        cli_state.current_scope = "runtime"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": "/workspace/project"}),
            stderr="",
        )

        instruction = self._git_instruction()
        variables = {"session_id": "s1", "task_dir": "/task", "args": "diff --cached"}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_os_system.assert_called_once()
        called_cmd = mock_os_system.call_args[0][0]
        self.assertIn("git", called_cmd)
        self.assertIn("-C", called_cmd)
        self.assertIn("/workspace/project", called_cmd)
        self.assertIn("diff --cached", called_cmd)

    @patch("cli_topsailai.yaml_commands.subprocess.run")
    @patch("cli_topsailai.yaml_commands.print_error")
    def test_git_missing_args_prints_usage(
        self, mock_print_error, mock_subprocess_run
    ):
        """/git with no subcommand must print usage and not run os.system."""
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["topsailai_session_info", "--json", "s1"],
            returncode=0,
            stdout=json.dumps({"project_workspace": "/workspace/project"}),
            stderr="",
        )

        instruction = self._git_instruction()
        variables = {"session_id": "s1", "task_dir": "/task", "args": ""}
        result = handle_yaml_command(instruction, variables)

        self.assertEqual(result, "yaml_handled")
        mock_print_error.assert_called_once()
        self.assertIn("Usage: /git", mock_print_error.call_args[0][0])


class TestBuildCommandEnvModelSelection(unittest.TestCase):
    """Tests for workspace-selected model environment merging in build_command_env."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _write_registry_and_selection(self, tmpdir, model_id="m1"):
        """Write a model registry and a workspace selection into tmpdir."""
        registry_path = os.path.join(tmpdir, ".models.jsonl")
        with open(registry_path, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "id": model_id,
                        "name": "Test Model",
                        "provider": "openai",
                        "protocol": "openai-compatible",
                        "model": "gpt-test",
                        "base_url": "https://api.test/v1",
                        "api_key_env": "TEST_API_KEY",
                    }
                )
                + "\n"
            )
        selection_path = os.path.join(tmpdir, ".model_selection.json")
        with open(selection_path, "w", encoding="utf-8") as f:
            json.dump({"workspace": model_id, "projects": {}}, f)
        return registry_path, selection_path

    @patch("cli_topsailai.models.load_models")
    @patch("cli_topsailai.models.resolve_effective_model")
    @patch("cli_topsailai.models.build_model_environment")
    def test_build_command_env_applies_selected_model(
        self, mock_build_env, mock_resolve, mock_load
    ):
        """build_command_env merges the selected model environment."""
        from cli_topsailai.models import EffectiveModel, ModelConfig

        model = ModelConfig(
            id="m1",
            name="Test Model",
            provider="openai",
            protocol="openai-compatible",
            model="gpt-test",
            base_url="https://api.test/v1",
            api_key_env="TEST_API_KEY",
        )
        mock_load.return_value = type("R", (), {"models": (model,)})()
        mock_resolve.return_value = EffectiveModel(model, "workspace", "m1")
        mock_build_env.return_value = (
            {
                "OPENAI_MODEL": "gpt-test",
                "OPENAI_BASE_URL": "https://api.test/v1",
                "OPENAI_API_KEY": "secret-key",
            },
            [],
        )

        with patch.dict(os.environ, {"TEST_API_KEY": "secret-key"}, clear=False):
            env = build_command_env({"environ": {}}, {"session_id": "s1"})

        self.assertEqual(env["OPENAI_MODEL"], "gpt-test")
        self.assertEqual(env["OPENAI_BASE_URL"], "https://api.test/v1")
        self.assertEqual(env["OPENAI_API_KEY"], "secret-key")
        mock_resolve.assert_called_once()
        self.assertEqual(mock_resolve.call_args.kwargs["project_workspace"], None)

    @patch("cli_topsailai.models.load_models")
    @patch("cli_topsailai.models.resolve_effective_model")
    def test_build_command_env_no_selection_unchanged(
        self, mock_resolve, mock_load
    ):
        """build_command_env leaves env unchanged when no model is selected."""
        from cli_topsailai.models import EffectiveModel

        mock_load.return_value = type("R", (), {"models": ()})()
        mock_resolve.return_value = EffectiveModel(None, "inherited", None)

        with patch.dict(os.environ, {"OPENAI_MODEL": "inherited-model"}, clear=False):
            env = build_command_env({"environ": {}}, {"session_id": "s1"})

        self.assertEqual(env["OPENAI_MODEL"], "inherited-model")
        self.assertEqual(env["TOPSAILAI_SESSION_ID"], "s1")

    @patch("cli_topsailai.models.load_models")
    @patch("cli_topsailai.models.resolve_effective_model")
    @patch("cli_topsailai.models.build_model_environment")
    def test_handle_yaml_command_chat_and_agent_share_model_env(
        self, mock_build_env, mock_resolve, mock_load
    ):
        """Both /chat and /agent child envs include the selected model env."""
        from cli_topsailai.models import EffectiveModel, ModelConfig

        model = ModelConfig(
            id="m1",
            name="Test Model",
            provider="openai",
            protocol="openai-compatible",
            model="gpt-test",
            base_url="https://api.test/v1",
            api_key_env="TEST_API_KEY",
        )
        mock_load.return_value = type("R", (), {"models": (model,)})()
        mock_resolve.return_value = EffectiveModel(model, "workspace", "m1")
        mock_build_env.return_value = (
            {
                "OPENAI_MODEL": "gpt-test",
                "OPENAI_BASE_URL": "https://api.test/v1",
                "OPENAI_API_KEY": "secret-key",
            },
            [],
        )

        cli_state.current_scope = "workspace"
        for cmd in ("/chat", "/agent", "/agent_plan"):
            with self.subTest(cmd=cmd):
                instruction = {
                    "cmd": cmd,
                    "scopes": ["workspace"],
                    "shell": "bash -c 'echo hi'",
                    "use_os_system": 1,
                }
                with patch(
                    "cli_topsailai.process.run_external_command"
                ) as mock_run:
                    with patch.dict(
                        os.environ, {"TEST_API_KEY": "secret-key"}, clear=False
                    ):
                        result = handle_yaml_command(instruction, {"session_id": "s1"})
                self.assertEqual(result, "yaml_handled")
                child_env = mock_run.call_args[0][1]
                self.assertEqual(child_env["OPENAI_MODEL"], "gpt-test")
                self.assertEqual(child_env["OPENAI_API_KEY"], "secret-key")


if __name__ == "__main__":
    unittest.main()
