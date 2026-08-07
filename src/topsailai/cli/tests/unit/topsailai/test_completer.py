#!/usr/bin/env python3
"""
Unit tests for tab-completion helpers in cli_topsailai.completer.
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
from cli_topsailai.completer import (
    get_control_instruction_names,
    tab_completer,
)


class TestControlCompleter(unittest.TestCase):
    """Tests for /control subcommand and instruction-name completion."""

    def tearDown(self):
        cli_state.yaml_commands = []
        cli_state.current_scope = "workspace"
        cli_state.current_session_id = None

    def _yaml_commands(self):
        return [
            {
                "cmd": "/control {command} {args}",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_send_control -s '{session_id}' -c '{command}' -a '{args}'",
            },
            {
                "cmd": "/control.hard_interrupt",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_send_control -s '{session_id}' -c 'hard_interrupt' -a '{}'",
            },
            {
                "cmd": "/control.call_instruction {args}",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_send_control -s '{session_id}' -c 'call_instruction' -a '{args}'",
            },
            {
                "cmd": "/ctx.history",
                "scopes": ["session"],
                "shell": "topsailai_retrieve_messages {session_id}",
            },
            {
                "cmd": "/ctx.search {keyword}",
                "scopes": ["session"],
                "shell": "topsailai_agent_call_instruction -s '{session_id}' -i '/ctx.search' -p '{keyword}'",
            },
        ]

    def test_get_control_instruction_names_excludes_control(self):
        """Instruction names must exclude /control commands themselves."""
        cli_state.yaml_commands = self._yaml_commands()
        names = get_control_instruction_names()
        self.assertIn("ctx.history", names)
        self.assertIn("ctx.search", names)
        self.assertNotIn("control", names)
        self.assertNotIn("control.hard_interrupt", names)
        self.assertNotIn("control.call_instruction", names)

    @patch("cli_topsailai.completer._get_control_action_names")
    def test_tab_completer_control_action(self, mock_actions):
        """TAB completion for /control.<action> must list registered actions."""
        mock_actions.return_value = [
            "call_instruction",
            "clear_interrupt",
            "get_runtime_messages",
            "hard_interrupt",
            "soft_interrupt",
        ]
        matches = []
        state = 0
        while True:
            candidate = tab_completer("/control.hard", state)
            if candidate is None:
                break
            matches.append(candidate)
            state += 1
        self.assertEqual(matches, ["/control.hard_interrupt"])

    @patch("cli_topsailai.completer._get_control_action_names")
    def test_tab_completer_control_action_all(self, mock_actions):
        """TAB completion for /control. must list all registered actions."""
        mock_actions.return_value = [
            "call_instruction",
            "clear_interrupt",
            "get_runtime_messages",
            "hard_interrupt",
            "soft_interrupt",
        ]
        matches = []
        state = 0
        while True:
            candidate = tab_completer("/control.", state)
            if candidate is None:
                break
            matches.append(candidate)
            state += 1
        self.assertEqual(
            matches,
            [
                "/control.call_instruction",
                "/control.clear_interrupt",
                "/control.get_runtime_messages",
                "/control.hard_interrupt",
                "/control.soft_interrupt",
            ],
        )

    def test_tab_completer_call_instruction_name(self):
        """TAB completion for /control.call_instruction <name> must list instruction names."""
        cli_state.yaml_commands = self._yaml_commands()
        matches = []
        state = 0
        while True:
            candidate = tab_completer("/control.call_instruction ctx.", state)
            if candidate is None:
                break
            matches.append(candidate)
            state += 1
        self.assertEqual(matches, ["ctx.history", "ctx.search"])

    def test_tab_completer_call_instruction_no_prefix(self):
        """TAB completion with empty prefix must list all instruction names."""
        cli_state.yaml_commands = self._yaml_commands()
        matches = []
        state = 0
        while True:
            candidate = tab_completer("/control.call_instruction ", state)
            if candidate is None:
                break
            matches.append(candidate)
            state += 1
        self.assertEqual(matches, ["ctx.history", "ctx.search"])


if __name__ == "__main__":
    unittest.main()
