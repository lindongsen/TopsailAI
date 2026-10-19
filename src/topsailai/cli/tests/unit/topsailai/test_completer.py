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

    def test_runtime_meta_completion(self):
        """Runtime completion must expose the built-in /meta command."""
        cli_state.current_scope = "runtime"
        matches = []
        state = 0
        while True:
            candidate = tab_completer("/me", state)
            if candidate is None:
                break
            matches.append(candidate)
            state += 1
        self.assertEqual(matches, ["/meta"])

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


def test_driver_completion_scope(monkeypatch):
    """Offer all driver commands only in the ordinary workspace list."""
    from cli_topsailai.completer import get_available_completions
    monkeypatch.setattr(cli_state, "yaml_commands", [])
    monkeypatch.setattr(cli_state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(cli_state, "current_scope", "workspace")
    completions = get_available_completions()
    for command in ("/driver", "/driver status", "/driver stop", "/driver log", "/driver meta"):
        assert command in completions
    import readline
    monkeypatch.setattr(readline, "get_line_buffer", lambda: "/driver st")
    monkeypatch.setattr(readline, "get_begidx", lambda: 8)
    assert tab_completer("st", 0) == "status"
    assert tab_completer("st", 1) == "stop"
    assert tab_completer("st", 2) is None
    assert tab_completer("sto", 0) == "stop"
    assert tab_completer("stop", 0) == "stop"
    assert tab_completer("sto", 1) is None
    monkeypatch.setattr(readline, "get_line_buffer", lambda: "/driver lo")
    assert tab_completer("lo", 0) == "log"
    assert tab_completer("lo", 1) is None
    monkeypatch.setattr(readline, "get_line_buffer", lambda: "/driver me")
    assert tab_completer("me", 0) == "meta"
    for scope in ("runtime", "project", "session", "doc"):
        monkeypatch.setattr(cli_state, "current_scope", scope)
        assert "/driver" not in get_available_completions()
    monkeypatch.setattr(cli_state, "current_scope", "workspace")
    monkeypatch.setattr(cli_state, "workspace_showing_managed_projects", True)
    assert "/driver" not in get_available_completions()


def test_meta_completion_scopes(monkeypatch):
    """Offer meta only for runtime and ordinary workspace lists."""
    from cli_topsailai.completer import get_available_completions
    monkeypatch.setattr(cli_state, "yaml_commands", [])
    for scope, managed, expected in [("runtime", False, True), ("workspace", False, True),
            ("workspace", True, False), ("project", False, False),
            ("session", False, False), ("doc", False, False)]:
        monkeypatch.setattr(cli_state, "current_scope", scope)
        monkeypatch.setattr(cli_state, "workspace_showing_managed_projects", managed)
        assert ("/meta" in get_available_completions()) is expected


def test_available_completion_yaml_boundaries(monkeypatch):
    """Filter scopes and normalize optional aliases without duplicates."""
    from cli_topsailai.completer import get_available_completions
    monkeypatch.setattr(cli_state, "current_scope", "workspace")
    monkeypatch.setattr(cli_state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(cli_state, "yaml_commands", [
        {"scopes": ["doc"], "cmd": "/excluded"},
        {"scopes": ["workspace"], "alias": ["", "plain", "/slash"]},
        {"scopes": ["workspace"], "cmd": "/refresh", "alias": "plain"},
    ])
    result = get_available_completions()
    assert "/excluded" not in result
    assert "/plain" in result and "/slash" in result
    assert result.count("/refresh") == result.count("/plain") == 1
    assert result == sorted(set(result))



def test_broadcast_completion_is_runtime_only(monkeypatch):
    """Expose the broadcast command exactly once only in runtime scope."""
    from cli_topsailai.completer import get_available_completions

    monkeypatch.setattr(cli_state, "yaml_commands", [])
    monkeypatch.setattr(cli_state, "workspace_showing_managed_projects", False)
    for scope in ("workspace", "project", "session", "doc"):
        monkeypatch.setattr(cli_state, "current_scope", scope)
        assert "/ctx.btw-all" not in get_available_completions()
    monkeypatch.setattr(cli_state, "current_scope", "runtime")
    completions = get_available_completions()
    assert completions.count("/ctx.btw-all") == 1


def test_live_fbt_tab_completion(monkeypatch):
    """Merge scoped YAML shortcuts with dynamic actions without duplicates."""
    import readline
    from pathlib import Path
    from cli_topsailai import completer, yaml_commands

    monkeypatch.setattr(cli_state, "yaml_commands", yaml_commands.load_yaml_commands(
        str(Path(__file__).resolve().parents[3] / "topsailai.yaml")))
    monkeypatch.setattr(readline, "get_line_buffer", lambda: "")
    monkeypatch.setattr(readline, "get_begidx", lambda: 0)
    monkeypatch.setattr(completer, "_get_control_action_names", lambda: ["hard_interrupt", "llm_control", "hard_interrupt"])
    shortcuts = ["/control.fbt.force_retry", "/control.fbt.hard_interrupt"]
    for scope in ("runtime", "session", "workspace", "project", "doc"):
        monkeypatch.setattr(cli_state, "current_scope", scope)
        matches = []
        for index in range(30):
            value = tab_completer("/control.", index)
            if value is None:
                break
            matches.append(value)
        assert len(matches) == len(set(matches))
        assert "/control.llm_control" in matches
        assert "/control.hard_interrupt" in matches
        expected = shortcuts if scope in ("runtime", "session") else []
        assert [tab_completer("/control.fbt.", index) for index in range(len(expected))] == expected
        assert tab_completer("/control.fbt.", len(expected)) is None
        assert all((command in matches) == (scope in ("runtime", "session")) for command in shortcuts)
        for command in expected:
            assert tab_completer(command, 0) == command
            assert tab_completer(command, 1) is None
            assert tab_completer(command[:-4], 0) == command
    monkeypatch.setattr(cli_state, "current_scope", "runtime")
    assert tab_completer("/control.call_instruction ctx.h", 0) == "ctx.history"
    assert tab_completer("/control.call_instruction ctx.h", 1) is None
    monkeypatch.setattr(completer, "_get_control_action_names", lambda: [])
    assert tab_completer("/control.fbt.", 0) == shortcuts[0]
