#!/usr/bin/env python3
"""Verify the runtime-scope command aliases ``btw`` and ``model``.

``btw`` is an alias of ``ctx.btw`` and ``model`` is an alias of
``agent.models``. Both are accepted with and without the leading ``/`` and
expand to the canonical spelling before any handler runs, so the handlers keep
receiving exactly one spelling. The aliases are declared once in
``cli_topsailai.constants.RUNTIME_COMMAND_ALIASES`` and consumed by the
recognizer, the completer and the help text, so a spelling cannot be accepted
without being discoverable.

Author: DawsonLin
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

import cli_topsailai.state as cli_state
from cli_topsailai import yaml_commands
from cli_topsailai.completer import get_available_completions
from cli_topsailai.constants import RUNTIME_COMMAND_ALIASES
from cli_topsailai.help_text import print_help, print_scopes
from cli_topsailai.streaming import _runtime_command_line


class TestRuntimeCommandAliasDeclaration(unittest.TestCase):
    """The alias table is the single source of truth for both aliases."""

    def test_declares_both_aliases(self):
        self.assertEqual(
            RUNTIME_COMMAND_ALIASES,
            {"btw": "ctx.btw", "model": "agent.models"},
        )


class TestRuntimeCommandAliasRecognition(unittest.TestCase):
    """The recognizer expands an alias to its canonical command line."""

    def setUp(self):
        self.previous_commands = cli_state.yaml_commands
        self.previous_scope = cli_state.current_scope
        cli_state.yaml_commands = yaml_commands.load_yaml_commands()
        cli_state.current_scope = "runtime"

    def tearDown(self):
        cli_state.yaml_commands = self.previous_commands
        cli_state.current_scope = self.previous_scope

    def test_btw_alias_expands_with_and_without_slash(self):
        for text, expected in (
            ("btw hello", "/ctx.btw hello"),
            ("/btw hello", "/ctx.btw hello"),
            ("btw", "/ctx.btw"),
            ("/btw", "/ctx.btw"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_model_alias_expands_with_and_without_slash(self):
        for text, expected in (
            ("model", "/agent.models"),
            ("/model", "/agent.models"),
            ("model 1", "/agent.models 1"),
            ("/model 1", "/agent.models 1"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_alias_keeps_the_remainder_unchanged(self):
        """A message body, JSON payload or path is never rewritten."""
        for text, expected in (
            ("btw remember to check the logs", "/ctx.btw remember to check the logs"),
            ("btw  double  space", "/ctx.btw  double  space"),
            ("model 1 2 3", "/agent.models 1 2 3"),
            ("btw a/b/c", "/ctx.btw a/b/c"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_alias_token_is_case_insensitive(self):
        for text, expected in (
            ("BTW hello", "/ctx.btw hello"),
            ("Btw hello", "/ctx.btw hello"),
            ("MODEL 2", "/agent.models 2"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_canonical_spellings_are_unchanged(self):
        """The alias must not alter the canonical command behavior."""
        for text, expected in (
            ("/ctx.btw hi", "/ctx.btw hi"),
            ("/agent.models 1", "/agent.models 1"),
            ("agent.models 1", "/agent.models 1"),
            ("send hello", "/send hello"),
            ("ctx.btw-all note", "/ctx.btw-all note"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_unknown_input_keeps_its_existing_behavior(self):
        """An alias must not turn unknown input into a command."""
        for text in ("hello world", "q", "quit", "!git status", "btwx hello"):
            with self.subTest(text=text):
                self.assertIsNone(_runtime_command_line(text, "/task"))

    def test_unknown_slash_command_is_still_reported_as_unknown(self):
        self.assertEqual(_runtime_command_line("/unknown", "/task"), "/unknown")


class TestRuntimeCommandAliasCompletion(unittest.TestCase):
    """The aliases are advertised only where they are accepted."""

    def setUp(self):
        self.previous_commands = cli_state.yaml_commands
        self.previous_scope = cli_state.current_scope
        self.previous_managed = cli_state.workspace_showing_managed_projects
        cli_state.yaml_commands = yaml_commands.load_yaml_commands()

    def tearDown(self):
        cli_state.yaml_commands = self.previous_commands
        cli_state.current_scope = self.previous_scope
        cli_state.workspace_showing_managed_projects = self.previous_managed

    def test_runtime_scope_offers_both_aliases(self):
        cli_state.current_scope = "runtime"
        completions = get_available_completions()
        self.assertIn("/btw", completions)
        self.assertIn("/model", completions)

    def test_other_scopes_do_not_offer_the_aliases(self):
        for scope in ("workspace", "project", "session", "doc"):
            with self.subTest(scope=scope):
                cli_state.current_scope = scope
                cli_state.workspace_showing_managed_projects = False
                completions = get_available_completions()
                self.assertNotIn("/btw", completions)
                self.assertNotIn("/model", completions)

    def test_completion_is_derived_from_the_alias_declaration(self):
        """Every declared alias is advertised, so the two cannot drift."""
        cli_state.current_scope = "runtime"
        completions = get_available_completions()
        for alias in RUNTIME_COMMAND_ALIASES:
            with self.subTest(alias=alias):
                self.assertIn("/" + alias, completions)


class TestRuntimeCommandAliasHelp(unittest.TestCase):
    """The aliases are documented in the runtime help surfaces."""

    def _capture(self, func, *args, **kwargs):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            func(*args, **kwargs)
            return mock_stdout.getvalue()

    def test_runtime_help_lists_both_aliases(self):
        output = self._capture(print_help, [], "runtime")
        self.assertIn("/btw", output)
        self.assertIn("/model", output)

    def test_alias_help_entries_are_runtime_only(self):
        runtime_output = self._capture(print_help, [], "runtime")
        workspace_output = self._capture(print_help, [], "workspace")
        self.assertIn("/btw [message...]", runtime_output)
        self.assertIn("/model [args...]", runtime_output)
        self.assertNotIn("/btw [message...]", workspace_output)
        self.assertNotIn("/model [args...]", workspace_output)

    def test_scope_guide_names_both_aliases(self):
        output = self._capture(print_scopes)
        self.assertIn("alias /btw", output)
        self.assertIn("alias /model", output)


class TestRuntimeCommandAliasGuidance(unittest.TestCase):
    """A working alias must never be reported as unavailable."""

    def test_unknown_command_guidance_names_the_aliases(self):
        from cli_topsailai import streaming

        source = open(streaming.__file__, encoding="utf-8").read()
        self.assertIn("(alias '/btw')", source)
        self.assertIn("(alias '/model')", source)

    def test_startup_guidance_names_the_btw_alias(self):
        from cli_topsailai import streaming

        source = open(streaming.__file__, encoding="utf-8").read()
        self.assertIn("(alias 'btw')", source)


if __name__ == "__main__":
    unittest.main()
