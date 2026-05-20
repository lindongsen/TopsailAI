#!/usr/bin/env python3
"""
Unit tests for YAML command loading and matching in topsailai.py.

Covers:
- load_yaml_commands()
- get_all_command_names()
- match_yaml_command()
"""

import sys
import os
import unittest
from unittest.mock import patch, mock_open, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestLoadYamlCommands(unittest.TestCase):
    """Tests for load_yaml_commands."""

    def tearDown(self):
        cli.yaml_commands = []

    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="instructions:\n  - cmd: /test\n    shell: echo hi\n")
    def test_load_success(self, mock_file, mock_isfile):
        """Load commands from YAML file successfully."""
        mock_isfile.return_value = True
        with patch.dict("sys.modules", {"yaml": MagicMock()}):
            import yaml as mock_yaml_module
            mock_yaml_module.safe_load.return_value = {
                "instructions": [{"cmd": "/test", "shell": "echo hi"}]
            }
            result = cli.load_yaml_commands()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["cmd"], "/test")

    @patch("os.path.isfile")
    def test_file_not_found(self, mock_isfile):
        """Return empty list when YAML file does not exist."""
        mock_isfile.return_value = False
        result = cli.load_yaml_commands()
        self.assertEqual(result, [])

    @patch("os.path.isfile")
    @patch("builtins.print")
    def test_pyyaml_not_installed(self, mock_print, mock_isfile):
        """Warn and return empty list when PyYAML is not installed."""
        mock_isfile.return_value = True
        with patch.dict("sys.modules", {"yaml": None}):
            result = cli.load_yaml_commands()
        self.assertEqual(result, [])
        printed = [str(args[0]) for args, kwargs in mock_print.call_args_list]
        self.assertTrue(any("PyYAML not installed" in p for p in printed))

    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="invalid yaml: [")
    @patch("builtins.print")
    def test_parse_error(self, mock_print, mock_file, mock_isfile):
        """Return empty list on YAML parse error."""
        mock_isfile.return_value = True
        with patch.dict("sys.modules", {"yaml": MagicMock()}):
            import yaml as mock_yaml_module
            mock_yaml_module.safe_load.side_effect = Exception("parse error")
            result = cli.load_yaml_commands()
        self.assertEqual(result, [])

    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="")
    def test_empty_file(self, mock_file, mock_isfile):
        """Return empty list for empty YAML file."""
        mock_isfile.return_value = True
        with patch.dict("sys.modules", {"yaml": MagicMock()}):
            import yaml as mock_yaml_module
            mock_yaml_module.safe_load.return_value = None
            result = cli.load_yaml_commands()
        self.assertEqual(result, [])

    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="not_a_dict: true\n")
    def test_not_dict(self, mock_file, mock_isfile):
        """Return empty list when YAML root is not a dict."""
        mock_isfile.return_value = True
        with patch.dict("sys.modules", {"yaml": MagicMock()}):
            import yaml as mock_yaml_module
            mock_yaml_module.safe_load.return_value = "not a dict"
            result = cli.load_yaml_commands()
        self.assertEqual(result, [])

    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="instructions: not_a_list\n")
    def test_instructions_not_list(self, mock_file, mock_isfile):
        """Return empty list when instructions is not a list."""
        mock_isfile.return_value = True
        with patch.dict("sys.modules", {"yaml": MagicMock()}):
            import yaml as mock_yaml_module
            mock_yaml_module.safe_load.return_value = {"instructions": "not_a_list"}
            result = cli.load_yaml_commands()
        self.assertEqual(result, [])


class TestGetAllCommandNames(unittest.TestCase):
    """Tests for get_all_command_names."""

    def test_cmd_only(self):
        """Extract command name without leading slash."""
        instruction = {"cmd": "/test"}
        result = cli.get_all_command_names(instruction)
        self.assertEqual(result, ["test"])

    def test_cmd_with_alias(self):
        """Extract cmd and aliases."""
        instruction = {"cmd": "/test", "alias": ["t", "tst"]}
        result = cli.get_all_command_names(instruction)
        self.assertEqual(result, ["test", "t", "tst"])

    def test_alias_as_string(self):
        """Handle alias as single string."""
        instruction = {"cmd": "/test", "alias": "t"}
        result = cli.get_all_command_names(instruction)
        self.assertEqual(result, ["test", "t"])

    def test_no_cmd(self):
        """Return empty list when no cmd."""
        instruction = {}
        result = cli.get_all_command_names(instruction)
        self.assertEqual(result, [])

    def test_empty_alias(self):
        """Skip empty aliases."""
        instruction = {"cmd": "/test", "alias": ["", "t"]}
        result = cli.get_all_command_names(instruction)
        self.assertEqual(result, ["test", "t"])


class TestMatchYamlCommand(unittest.TestCase):
    """Tests for match_yaml_command."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = [
            {"cmd": "/cd {session_id}", "scopes": ["workspace"], "shell": ""},
            {"cmd": "/env.get {key}", "scopes": ["workspace"], "shell": ""},
            {"cmd": "/env.set {key} {value}", "scopes": ["workspace"], "shell": ""},
            {"cmd": "/ctx.search {keyword}", "scopes": ["session"], "shell": "search {keyword}"},
            {"cmd": "/ctx.history", "scopes": ["session"], "shell": "history", "alias": ["history"]},
            {"cmd": "/task.run {driver}", "scopes": ["session"], "shell": "run {driver}"},
            {"cmd": "/ctx.add_msg", "scopes": ["session"], "shell": "add {message}"},
        ]

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = []

    def test_match_cd_with_args(self):
        """Match /cd with session_id in workspace scope."""
        result = cli.match_yaml_command("/cd my-session")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(instruction["cmd"], "/cd {session_id}")
        self.assertEqual(variables["session_id"], "my-session")

    def test_match_cd_without_args(self):
        """Match /cd without args returns empty session_id."""
        result = cli.match_yaml_command("/cd")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["session_id"], "")

    def test_match_cd_without_slash(self):
        """Match cd without leading slash."""
        result = cli.match_yaml_command("cd my-session")
        self.assertIsNotNone(result)

    def test_match_env_get(self):
        """Match /env.get with key."""
        result = cli.match_yaml_command("/env.get TEST_KEY")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["key"], "TEST_KEY")

    def test_match_env_set(self):
        """Match /env.set with key and value."""
        result = cli.match_yaml_command("/env.set KEY value")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["key"], "KEY")
        self.assertEqual(variables["value"], "value")

    def test_scope_filtering(self):
        """Session-scoped commands not available in workspace."""
        result = cli.match_yaml_command("/ctx.search keyword")
        self.assertIsNone(result)

    def test_scope_match_session(self):
        """Session-scoped commands available in session scope."""
        cli.current_scope = "session"
        cli.current_session_id = "s1"
        result = cli.match_yaml_command("/ctx.search keyword")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["keyword"], "keyword")
        self.assertEqual(variables["session_id"], "s1")

    def test_alias_match(self):
        """Match command by alias."""
        cli.current_scope = "session"
        cli.current_session_id = "s1"
        result = cli.match_yaml_command("history")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(instruction["cmd"], "/ctx.history")

    def test_no_match(self):
        """Return None for unknown command."""
        result = cli.match_yaml_command("/unknown")
        self.assertIsNone(result)

    def test_match_task_run(self):
        """Match /task.run with driver."""
        cli.current_scope = "session"
        cli.current_session_id = "s1"
        result = cli.match_yaml_command("/task.run ai-team-flow-dev")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["driver"], "ai-team-flow-dev")

    def test_match_ctx_add_msg(self):
        """Match /ctx.add_msg with multiline support."""
        cli.current_scope = "session"
        cli.current_session_id = "s1"
        result = cli.match_yaml_command("/ctx.add_msg hello world")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["message"], "hello world")

    def test_match_ctx_add_msg_multiline(self):
        """Match /ctx.add_msg with multiline text."""
        cli.current_scope = "session"
        cli.current_session_id = "s1"
        result = cli.match_yaml_command("/ctx.add_msg line1\nline2")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["message"], "line1\nline2")

    def test_default_session_id(self):
        """Default session_id from current session when not in template."""
        cli.current_scope = "session"
        cli.current_session_id = "default-session"
        result = cli.match_yaml_command("history")
        self.assertIsNotNone(result)
        instruction, variables = result
        self.assertEqual(variables["session_id"], "default-session")


class TestGetAvailableCompletions(unittest.TestCase):
    """Tests for get_available_completions."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = [
            {"cmd": "/cd {session_id}", "scopes": ["workspace"], "shell": ""},
            {"cmd": "/env.get {key}", "scopes": ["workspace"], "shell": ""},
            {"cmd": "/ctx.search {keyword}", "scopes": ["session"], "shell": "search {keyword}"},
            {"cmd": "/ctx.history", "scopes": ["session"], "shell": "history", "alias": ["history"]},
        ]

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = []

    def test_workspace_scope(self):
        """Return workspace-scoped commands and builtins."""
        result = cli.get_available_completions()
        self.assertIn("/refresh", result)
        self.assertIn("/cd", result)
        self.assertIn("/env.get", result)
        self.assertNotIn("/ctx.search", result)
        self.assertNotIn("/ctx.history", result)

    def test_session_scope(self):
        """Return session-scoped commands and builtins."""
        cli.current_scope = "session"
        result = cli.get_available_completions()
        self.assertIn("/refresh", result)
        self.assertIn("/ctx.search", result)
        self.assertIn("/ctx.history", result)
        self.assertIn("/history", result)
        self.assertNotIn("/cd", result)

    def test_sorted_and_unique(self):
        """Results should be sorted and deduplicated."""
        result = cli.get_available_completions()
        self.assertEqual(result, sorted(result))
        self.assertEqual(len(result), len(set(result)))


class TestTabCompleter(unittest.TestCase):
    """Tests for tab_completer."""

    def setUp(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = [
            {"cmd": "/cd {session_id}", "scopes": ["workspace"], "shell": ""},
            {"cmd": "/env.get {key}", "scopes": ["workspace"], "shell": ""},
            {"cmd": "/env.set {key} {value}", "scopes": ["workspace"], "shell": ""},
        ]

    def tearDown(self):
        cli.current_scope = "workspace"
        cli.current_session_id = None
        cli.yaml_commands = []

    @patch("topsailai.readline.get_line_buffer", return_value="/e")
    def test_match_prefix(self, mock_buffer):
        """Return matching command for prefix."""
        result = cli.tab_completer("/e", 0)
        self.assertTrue(result.startswith("/e"))

    @patch("topsailai.readline.get_line_buffer", return_value="/e")
    def test_no_match(self, mock_buffer):
        """Return None when no matches."""
        result = cli.tab_completer("/xyz", 0)
        self.assertIsNone(result)

    @patch("topsailai.readline.get_line_buffer", return_value="/e")
    def test_state_increment(self, mock_buffer):
        """Return different matches for different state values."""
        r0 = cli.tab_completer("/e", 0)
        r1 = cli.tab_completer("/e", 1)
        self.assertNotEqual(r0, r1)
        r2 = cli.tab_completer("/e", 2)
        self.assertIsNone(r2)

    @patch("topsailai.readline.get_line_buffer", return_value="")
    def test_empty_text(self, mock_buffer):
        """Return first completion when text is empty."""
        result = cli.tab_completer("", 0)
        self.assertIsNotNone(result)

    @patch("topsailai.readline.get_line_buffer", return_value="e")
    def test_match_without_leading_slash(self, mock_buffer):
        """Match commands when user omits leading '/'."""
        result = cli.tab_completer("e", 0)
        self.assertTrue(result.startswith("e"))
        self.assertFalse(result.startswith("/"))

    @patch("topsailai.readline.get_line_buffer", return_value="re")
    def test_match_builtin_without_slash(self, mock_buffer):
        """Match builtin command without leading '/'."""
        result = cli.tab_completer("re", 0)
        self.assertEqual(result, "refresh")

class TestSetupTabCompletion(unittest.TestCase):
    """Tests for setup_tab_completion."""

    @patch("topsailai.readline.set_completer")
    @patch("topsailai.readline.parse_and_bind")
    def test_setup_calls(self, mock_parse, mock_set):
        """Verify readline functions are called."""
        cli.setup_tab_completion()
        mock_set.assert_called_once()
        mock_parse.assert_called_once_with("tab: complete")

    @patch("topsailai.readline.set_completer", side_effect=AttributeError())
    def test_setup_graceful(self, mock_set):
        """Handle missing readline gracefully."""
        cli.setup_tab_completion()


if __name__ == "__main__":
    unittest.main()
