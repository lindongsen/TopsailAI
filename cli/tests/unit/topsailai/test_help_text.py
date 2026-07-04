#!/usr/bin/env python3
"""
Unit tests for help text rendering in cli_topsailai.
"""

import io
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

from cli_topsailai.help_text import print_help, print_instruction_help


class TestPrintHelp(unittest.TestCase):
    """Tests for print_help keyword filtering."""

    def _capture(self, func, *args, **kwargs):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            func(*args, **kwargs)
            return mock_stdout.getvalue()

    def test_print_help_without_keyword_lists_all(self):
        output = self._capture(print_help, [], "workspace")
        self.assertIn("Available Commands", output)
        self.assertIn("/help", output)
        self.assertIn("/refresh", output)

    def test_print_help_with_keyword_matches_builtin(self):
        output = self._capture(print_help, [], "workspace", keyword="refresh")
        self.assertIn("Commands matching 'refresh'", output)
        self.assertIn("/refresh", output)
        self.assertNotIn("/clean", output)

    def test_print_help_with_keyword_matches_yaml(self):
        yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session"],
                "desc": "Add a by-the-way message",
                "example": "",
            },
            {
                "cmd": "/task.run {driver}",
                "scopes": ["session"],
                "desc": "Run task for the session",
                "example": "/task.run ai-team-flow-dev",
            },
        ]
        output = self._capture(print_help, yaml_commands, "session", keyword="btw")
        self.assertIn("Commands matching 'btw'", output)
        self.assertIn("/ctx.btw", output)
        self.assertNotIn("/task.run", output)

    def test_print_help_keyword_searches_across_scopes(self):
        yaml_commands = [
            {
                "cmd": "/ctx.btw",
                "scopes": ["session"],
                "desc": "Add a by-the-way message",
                "example": "",
            },
            {
                "cmd": "/task.run {driver}",
                "scopes": ["session"],
                "desc": "Run task for the session",
                "example": "/task.run ai-team-flow-dev",
            },
        ]
        # Request from workspace scope should still find session-only commands.
        output = self._capture(print_help, yaml_commands, "workspace", keyword="ctx")
        self.assertIn("Commands matching 'ctx'", output)
        self.assertIn("/ctx.btw", output)
        self.assertNotIn("/task.run", output)


    def test_print_help_with_keyword_matches_alias(self):
        yaml_commands = [
            {
                "cmd": "/ctx.history",
                "alias": ["history"],
                "scopes": ["session"],
                "desc": "show context messages",
                "example": "",
            }
        ]
        output = self._capture(print_help, yaml_commands, "session", keyword="history")
        self.assertIn("/ctx.history", output)
        self.assertIn("alias: history", output)

    def test_print_help_no_matches(self):
        output = self._capture(print_help, [], "workspace", keyword="xyznonexistent")
        self.assertIn("No commands found matching 'xyznonexistent'", output)


class TestPrintInstructionHelp(unittest.TestCase):
    """Tests for print_instruction_help."""

    def test_print_instruction_help(self):
        instruction = {
            "cmd": "/ctx.btw",
            "alias": ["btw"],
            "scopes": ["session"],
            "desc": "Add a by-the-way message to Agent2LLM runtime inject source",
            "example": "",
        }
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            print_instruction_help(instruction)
            output = mock_stdout.getvalue()
        self.assertIn("Command Help", output)
        self.assertIn("/ctx.btw", output)
        self.assertIn("btw", output)
        self.assertIn("Agent2LLM", output)


if __name__ == "__main__":
    unittest.main()
