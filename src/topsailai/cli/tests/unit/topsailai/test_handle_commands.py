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

    @patch("builtins.print")
    @patch("cli_topsailai.core.input")
    def test_unknown_command_circuit_breaker(self, mock_input, mock_print):
        """Repeated unrecognized commands must not hang the prompt."""
        mock_input.return_value = "/unknown"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")
        self.assertTrue(
            any("infinite loop" in str(call) for call in mock_print.call_args_list)
        )

    @patch("builtins.print")
    @patch("cli_topsailai.core.input")
    def test_total_iteration_limit(self, mock_input, mock_print):
        """Any loop that does not make progress must be bounded."""
        mock_input.return_value = ""
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")
        self.assertTrue(
            any("Maximum prompt iterations" in str(call) for call in mock_print.call_args_list)
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


class TestRuntimeRawArguments(unittest.TestCase):
    """Tests for -r / --runtime-raw argument handling."""

    @patch("cli_topsailai.streaming.stream_file")
    @patch("cli_topsailai.core.prompt_selection")
    @patch("cli_topsailai.log_files.discover_log_files")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.completer.setup_tab_completion")
    def test_runtime_raw_passed_to_stream_file(
        self,
        _mock_setup_tab: MagicMock,
        _mock_load_history: MagicMock,
        _mock_history: MagicMock,
        _mock_header: MagicMock,
        _mock_table: MagicMock,
        _mock_enrich: MagicMock,
        mock_discover: MagicMock,
        mock_prompt: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        """--runtime-raw should be forwarded to stream_file() on watch."""
        from cli_topsailai.core import main

        log_file = {
            "filename": "s1.1234.session.stdout",
            "path": "/task/s1.1234.session.stdout",
            "session_id": "s1",
        }
        mock_discover.return_value = [log_file]
        mock_prompt.side_effect = [("watch", 0), ("quit", None)]

        main(["--runtime-raw", "--tail-lines", "50"])

        mock_stream.assert_called_once()
        _, kwargs = mock_stream.call_args
        self.assertTrue(kwargs["runtime_raw"])
        self.assertEqual(kwargs["tail_lines"], 50)

    @patch("cli_topsailai.streaming.stream_file")
    @patch("cli_topsailai.core.prompt_selection")
    @patch("cli_topsailai.log_files.discover_log_files")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.completer.setup_tab_completion")
    def test_runtime_raw_short_flag_defaults(
        self,
        _mock_setup_tab: MagicMock,
        _mock_load_history: MagicMock,
        _mock_history: MagicMock,
        _mock_header: MagicMock,
        _mock_table: MagicMock,
        _mock_enrich: MagicMock,
        mock_discover: MagicMock,
        mock_prompt: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        """-r without --tail-lines should default to 100."""
        from cli_topsailai.core import main

        log_file = {
            "filename": "s1.1234.session.stdout",
            "path": "/task/s1.1234.session.stdout",
            "session_id": "s1",
        }
        mock_discover.return_value = [log_file]
        mock_prompt.side_effect = [("watch", 0), ("quit", None)]

        main(["-r"])

        _, kwargs = mock_stream.call_args
        self.assertTrue(kwargs["runtime_raw"])
        self.assertEqual(kwargs["tail_lines"], 100)

    @patch("cli_topsailai.streaming.stream_file")
    @patch("cli_topsailai.core.prompt_selection")
    @patch("cli_topsailai.log_files.discover_log_files")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.completer.setup_tab_completion")
    def test_without_runtime_raw_defaults(
        self,
        _mock_setup_tab: MagicMock,
        _mock_load_history: MagicMock,
        _mock_history: MagicMock,
        _mock_header: MagicMock,
        _mock_table: MagicMock,
        _mock_enrich: MagicMock,
        mock_discover: MagicMock,
        mock_prompt: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        """By default, stream_file() receives True (raw mode) and default tail_lines."""
        from cli_topsailai.core import main

        log_file = {
            "filename": "s1.1234.session.stdout",
            "path": "/task/s1.1234.session.stdout",
            "session_id": "s1",
        }
        mock_discover.return_value = [log_file]
        mock_prompt.side_effect = [("watch", 0), ("quit", None)]

        main([])

        _, kwargs = mock_stream.call_args
        self.assertTrue(kwargs["runtime_raw"])
        self.assertEqual(kwargs["tail_lines"], 100)

    @patch("cli_topsailai.streaming.stream_file")
    @patch("cli_topsailai.core.prompt_selection")
    @patch("cli_topsailai.log_files.discover_log_files")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.completer.setup_tab_completion")
    def test_runtime_tui_flag_uses_curses(
        self,
        _mock_setup_tab: MagicMock,
        _mock_load_history: MagicMock,
        _mock_history: MagicMock,
        _mock_header: MagicMock,
        _mock_table: MagicMock,
        _mock_enrich: MagicMock,
        mock_discover: MagicMock,
        mock_prompt: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        """With --tui, stream_file() receives False (curses UI)."""
        from cli_topsailai.core import main

        log_file = {
            "filename": "s1.1234.session.stdout",
            "path": "/task/s1.1234.session.stdout",
            "session_id": "s1",
        }
        mock_discover.return_value = [log_file]
        mock_prompt.side_effect = [("watch", 0), ("quit", None)]

        main(["--tui"])

        _, kwargs = mock_stream.call_args
        self.assertFalse(kwargs["runtime_raw"])
        self.assertEqual(kwargs["tail_lines"], 100)




class TestProjectScopeCommands(unittest.TestCase):
    """Tests for project scope command handling."""

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
    def test_cd_project_switches_scope(self, mock_input):
        cli_state.yaml_commands = [
            {
                "cmd": "/cd project",
                "scopes": ["workspace"],
                "shell": "",
            }
        ]
        mock_input.return_value = "cd project"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")

    @patch("cli_topsailai.core.input")
    def test_numeric_selection_in_project_enters_session(self, mock_input):
        cli_state.current_scope = "project"
        project_entries = [
            {"session_id": "proj-s1", "project_workspace": "/work/a"},
            {"session_id": "proj-s2", "project_workspace": "/work/b"},
        ]
        mock_input.return_value = "2"
        action, value = prompt_selection(project_entries, "/task")
        self.assertEqual(action, "enter_session")
        self.assertEqual(value, "proj-s2")

    @patch("cli_topsailai.core.input")
    def test_cd_session_id_in_project_enters_session(self, mock_input):
        cli_state.current_scope = "project"
        project_entries = [
            {"session_id": "proj-s1", "project_workspace": "/work/a"},
            {"session_id": "proj-s2", "project_workspace": "/work/b"},
        ]
        mock_input.return_value = "cd proj-s1"
        action, value = prompt_selection(project_entries, "/task")
        self.assertEqual(action, "enter_session")
        self.assertEqual(value, "proj-s1")

    @patch("cli_topsailai.core.input")
    def test_session_number_in_project_retrieves_context(self, mock_input):
        cli_state.current_scope = "project"
        project_entries = [
            {"session_id": "proj-s1", "project_workspace": "/work/a"},
            {"session_id": "proj-s2", "project_workspace": "/work/b"},
        ]
        mock_input.return_value = "/session 2"
        action, value = prompt_selection(project_entries, "/task")
        self.assertEqual(action, "session")
        self.assertEqual(value, 1)

    @patch("cli_topsailai.core.input")
    def test_session_id_in_project_retrieves_context(self, mock_input):
        cli_state.current_scope = "project"
        project_entries = [
            {"session_id": "proj-s1", "project_workspace": "/work/a"},
            {"session_id": "proj-s2", "project_workspace": "/work/b"},
        ]
        mock_input.return_value = "/session proj-s1"
        action, value = prompt_selection(project_entries, "/task")
        self.assertEqual(action, "session_id")
        self.assertEqual(value, "proj-s1")

    @patch("builtins.print")
    @patch("cli_topsailai.core.input")
    def test_session_missing_arg_in_project_shows_usage(self, mock_input, mock_print):
        cli_state.current_scope = "project"
        project_entries = [
            {"session_id": "proj-s1", "project_workspace": "/work/a"},
        ]
        mock_input.side_effect = ["/session", "q"]
        action, value = prompt_selection(project_entries, "/task")
        self.assertEqual(action, "quit")
        self.assertTrue(
            any("Usage: /session" in str(call) for call in mock_print.call_args_list)
        )


    @patch("cli_topsailai.core.input")
    def test_cd_from_project_returns_to_workspace(self, mock_input):
        cli_state.current_scope = "project"
        cli_state.yaml_commands = [
            {
                "cmd": "/cd",
                "scopes": ["project"],
                "shell": "",
            }
        ]
        mock_input.return_value = "/cd"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")

    @patch("cli_topsailai.core.input")
    def test_bare_cd_from_project_with_real_yaml(self, mock_input):
        """Bare 'cd' from project scope must match the real topsailai.yaml."""
        from cli_topsailai.yaml_commands import load_yaml_commands

        cli_state.current_scope = "project"
        cli_state.yaml_commands = load_yaml_commands()
        mock_input.return_value = "cd"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")


class TestWorkspaceAgentCommand(unittest.TestCase):
    """Tests for /agent command support in workspace scope."""

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
    def test_prompt_selection_agent_in_workspace(self, mock_input):
        """/agent argument is parsed in workspace scope."""
        mock_input.return_value = "/agent /path/to/project"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "agent")
        self.assertEqual(value, "/path/to/project")

    @patch("cli_topsailai.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.core.input")
    def test_bare_agent_in_workspace_uses_yaml(self, mock_input, mock_handle_yaml):
        """Bare 'agent' in workspace scope must match the real topsailai.yaml."""
        from cli_topsailai.yaml_commands import load_yaml_commands

        cli_state.yaml_commands = load_yaml_commands()
        mock_handle_yaml.return_value = "yaml_handled"
        mock_input.return_value = "agent"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "yaml_handled")
        mock_handle_yaml.assert_called_once()

    @patch("cli_topsailai.core.input")
    def test_agent_with_args_in_workspace(self, mock_input):
        """'agent <folder>' without slash is treated as the new navigation command."""
        mock_input.return_value = "agent /path/to/project"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "agent")
        self.assertEqual(value, "/path/to/project")

    @patch("cli_topsailai.core.input")
    def test_agent_with_args_in_workspace_uses_explicit_branch_with_real_yaml(self, mock_input):
        """'agent <folder>' with real YAML loaded must use explicit branch, not YAML."""
        from cli_topsailai.yaml_commands import load_yaml_commands

        cli_state.yaml_commands = load_yaml_commands()
        mock_input.return_value = "agent /path/to/project"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "agent")
        self.assertEqual(value, "/path/to/project")

    @patch("cli_topsailai.core.input")
    def test_slash_agent_with_args_in_workspace_uses_explicit_branch_with_real_yaml(self, mock_input):
        """'/agent <folder>' with real YAML loaded must use explicit branch, not YAML."""
        from cli_topsailai.yaml_commands import load_yaml_commands

        cli_state.yaml_commands = load_yaml_commands()
        mock_input.return_value = "/agent /path/to/project"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "agent")
        self.assertEqual(value, "/path/to/project")

    @patch("cli_topsailai.project_scope.launch_agent_in_folder")
    @patch("cli_topsailai.project_scope.resolve_agent_folder")
    @patch("cli_topsailai.core.prompt_selection")
    @patch("cli_topsailai.log_files.discover_log_files")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.completer.setup_tab_completion")
    def test_agent_folder_in_workspace(
        self,
        _mock_setup_tab: MagicMock,
        _mock_load_history: MagicMock,
        _mock_history: MagicMock,
        _mock_header: MagicMock,
        _mock_table: MagicMock,
        _mock_enrich: MagicMock,
        mock_discover: MagicMock,
        mock_prompt: MagicMock,
        mock_resolve: MagicMock,
        mock_launch: MagicMock,
    ) -> None:
        """/agent with a folder path launches agent from workspace scope."""
        from cli_topsailai.core import main

        log_file = {
            "filename": "s1.1234.session.stdout",
            "path": "/task/s1.1234.session.stdout",
            "session_id": "s1",
            "project_workspace": "/work/a",
        }
        mock_discover.return_value = [log_file]
        mock_prompt.side_effect = [("agent", "/work/a"), ("quit", None)]
        mock_resolve.return_value = "/work/a"

        main([])

        mock_resolve.assert_called_once_with("/work/a", [log_file])
        mock_launch.assert_called_once_with("/work/a")

    @patch("cli_topsailai.project_scope.launch_agent_in_folder")
    @patch("cli_topsailai.project_scope.resolve_agent_folder")
    @patch("cli_topsailai.core.prompt_selection")
    @patch("cli_topsailai.log_files.discover_log_files")
    @patch("cli_topsailai.session_info.enrich_files_with_session_names")
    @patch("cli_topsailai.formatting.print_table")
    @patch("cli_topsailai.formatting.print_header")
    @patch("cli_topsailai.history.HistoryManager")
    @patch("cli_topsailai.history.load_readline_history")
    @patch("cli_topsailai.completer.setup_tab_completion")
    def test_agent_number_in_workspace(
        self,
        _mock_setup_tab: MagicMock,
        _mock_load_history: MagicMock,
        _mock_history: MagicMock,
        _mock_header: MagicMock,
        _mock_table: MagicMock,
        _mock_enrich: MagicMock,
        mock_discover: MagicMock,
        mock_prompt: MagicMock,
        mock_resolve: MagicMock,
        mock_launch: MagicMock,
    ) -> None:
        """/agent with a number resolves via the workspace log file list."""
        from cli_topsailai.core import main

        log_file = {
            "filename": "s1.1234.session.stdout",
            "path": "/task/s1.1234.session.stdout",
            "session_id": "s1",
            "project_workspace": "/work/a",
        }
        mock_discover.return_value = [log_file]
        mock_prompt.side_effect = [("agent", "1"), ("quit", None)]
        mock_resolve.return_value = "/work/a"

        main([])

        mock_resolve.assert_called_once_with("1", [log_file])
        mock_launch.assert_called_once_with("/work/a")


if __name__ == "__main__":
    unittest.main()
