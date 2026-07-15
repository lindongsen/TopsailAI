#!/usr/bin/env python3
"""
Unit tests for context message addition in cli_topsailai.
"""

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

import cli_topsailai.state as cli_state
from cli_topsailai.core import prompt_selection


class TestContextAddMessage(unittest.TestCase):
    """Tests for adding context messages."""

    def setUp(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    def tearDown(self):
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None
        cli_state.yaml_commands = []

    @patch("cli_topsailai.core.input")
    def test_prompt_in_workspace_scope(self, mock_input):
        mock_input.return_value = "q"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")

    @patch("cli_topsailai.core.input")
    def test_prompt_in_session_scope(self, mock_input):
        cli_state.current_scope = "session"
        cli_state.current_session_id = "s1"
        mock_input.return_value = "q"
        action, value = prompt_selection([], "/task")
        self.assertEqual(action, "quit")


if __name__ == "__main__":
    unittest.main()
