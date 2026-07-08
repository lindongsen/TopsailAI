#!/usr/bin/env python3
"""
Unit tests for YAML command loading in cli_topsailai.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

import cli_topsailai.state as cli_state
from cli_topsailai.yaml_commands import load_yaml_commands, match_yaml_command


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


if __name__ == "__main__":
    unittest.main()
