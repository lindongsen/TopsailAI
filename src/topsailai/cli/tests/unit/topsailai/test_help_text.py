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

from cli_topsailai.help_text import print_help, print_instruction_help, print_scopes


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
        self.assertIn("scopes", output)

    def test_shell_command_is_listed_in_every_scope(self):
        for scope in ("workspace", "runtime", "project", "session", "doc"):
            with self.subTest(scope=scope):
                output = self._capture(print_help, [], scope)
                self.assertIn("!<command>", output)
                self.assertIn("!git status", output)

    def test_print_scopes_describes_all_scopes_and_actions(self):
        output = self._capture(print_scopes)
        self.assertIn("Scope Guide", output)
        for scope in ("workspace", "runtime", "project", "session", "doc"):
            self.assertIn(scope, output)
        self.assertEqual(output.count("Available actions:"), 5)

    def test_print_help_project_scope_shows_session_number(self):
        output = self._capture(print_help, [], "project")
        self.assertIn("Enter the selected session by its number.", output)
        self.assertNotIn(
            "Select a log file by its number to stream output in real-time.", output
        )

    def test_print_help_workspace_scope_shows_log_file_number(self):
        output = self._capture(print_help, [], "workspace")
        self.assertIn(
            "Select a log file by its number to stream output in real-time.", output
        )
        self.assertNotIn("Enter the selected session by its number.", output)

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

    def test_print_help_runtime_scope_lists_meta(self):
        output = self._capture(print_help, [], "runtime")
        self.assertIn("/meta", output)
        self.assertIn("metadata file", output)

    def test_print_help_runtime_scope_mentions_arrow_keys(self):
        output = self._capture(print_help, [], "runtime")
        self.assertIn("Up / Down arrows", output)
        self.assertIn("recall the previous runtime message", output)



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


def test_driver_help_scope(capsys):
    """Keep both driver syntaxes discoverable only in workspace help."""
    print_help([], "workspace")
    output = capsys.readouterr().out
    assert "/driver <number>" in output
    assert "/driver status <number>" in output
    for scope in ("runtime", "project", "session", "doc"):
        print_help([], scope)
        assert "/driver" not in capsys.readouterr().out
    print_scopes()
    assert "/driver status <number>" in capsys.readouterr().out


def test_driver_legend_in_workspace_help_only(capsys):
    """Keep the legend inside the workspace driver description, never the footer."""
    legend = ("Driver: - no record/ineligible; numeric PID means ON with a verified driver; "
              "same-session rows share that display, but may remain ineligible for driver operations; "
              ":( STALE absent process; x( EXIT/FAIL residual terminal record; ? unverified")
    for keyword in (None, "driver"):
        print_help([], "workspace", keyword=keyword)
        output = capsys.readouterr().out
        assert output.count(legend) == 1
        driver_entry = output.split("/driver <number>", 1)[1].split("Example: /driver 3", 1)[0]
        assert "Start a session driver" in driver_entry
        assert legend in driver_entry
        assert "task list only. Driver:" in driver_entry
        assert "Driver:" not in output.split("Example: /driver 3", 1)[1]
    for scope in ("runtime", "project", "session", "doc"):
        for keyword in (None, "driver"):
            print_help([], scope, keyword=keyword)
            assert "Driver:" not in capsys.readouterr().out
    print_help([], "workspace", keyword="refresh")
    assert "Driver:" not in capsys.readouterr().out


def test_driver_stop_help_discovery(capsys):
    """Expose stop and its limits while keeping normal help workspace-only."""
    print_help([], "workspace", keyword="driver")
    output = capsys.readouterr().out
    assert "/driver stop <number>" in output
    assert "not its session" in output and "3 seconds" in output
    for scope in ("project", "runtime", "session", "doc"):
        print_help([], scope)
        assert "/driver stop" not in capsys.readouterr().out
    print_scopes()
    assert "/driver stop" in capsys.readouterr().out


def test_meta_scope_contract(capsys):
    """Workspace row syntax must not replace runtime bare metadata help."""
    print_help([], "workspace", keyword="meta")
    assert "/meta <number>" in capsys.readouterr().out
    print_help([], "runtime")
    output = capsys.readouterr().out
    assert "watched parent session" in output
    assert "/meta <number>" not in output
