#!/usr/bin/env python3
"""Verify the leading '/' is optional for runtime-scope commands.

Runtime input is recognized as a command whether or not it starts with '/',
so ``send hello`` and ``/send hello`` are the same command. Input that names
no command keeps the existing send-as-message behavior.

Author: DawsonLin
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

import cli_topsailai.state as cli_state
from cli_topsailai import yaml_commands
from cli_topsailai.streaming import (
    _build_stream_command_handler,
    _dispatch_input,
    _runtime_command_line,
    _stream_file_legacy,
)


class TestRuntimeCommandLine(unittest.TestCase):
    """Tests for the shared runtime command recognizer."""

    def setUp(self):
        self.previous_commands = cli_state.yaml_commands
        self.previous_scope = cli_state.current_scope
        cli_state.yaml_commands = yaml_commands.load_yaml_commands()
        cli_state.current_scope = "runtime"

    def tearDown(self):
        cli_state.yaml_commands = self.previous_commands
        cli_state.current_scope = self.previous_scope

    def test_bare_builtin_commands_are_recognized(self):
        for text, expected in (
            ("send hello", "/send hello"),
            ("ctx.btw note", "/ctx.btw note"),
            ("ctx.btw-all note", "/ctx.btw-all note"),
            ("meta", "/meta"),
            ("help", "/help"),
            ("help ctx", "/help ctx"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_slash_prefixed_input_is_returned_as_is(self):
        for text in ("/send hello", "/meta", "/help", "/unknown"):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), text)

    def test_slash_prefixed_input_is_stripped(self):
        """Leading whitespace must not shift a fixed-length prefix slice."""
        for text, expected in (
            ("   /send hi", "/send hi"),
            ("\t/send hi", "/send hi"),
            ("  /unknown  ", "/unknown"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_unknown_slash_command_is_not_reinterpreted_as_message(self):
        self.assertEqual(_runtime_command_line("/unknown", "/task"), "/unknown")

    def test_plain_text_is_not_a_command(self):
        for text in ("hello world", "hello", "what", "not-a-command"):
            with self.subTest(text=text):
                self.assertIsNone(_runtime_command_line(text, "/task"))

    def test_empty_input_is_not_a_command(self):
        for text in ("", "   ", "\t"):
            with self.subTest(text=text):
                self.assertIsNone(_runtime_command_line(text, "/task"))

    def test_control_and_agent_prefixes_are_recognized(self):
        for text, expected in (
            ("control", "/control"),
            ("control heartbeat", "/control heartbeat"),
            ("control.hard_interrupt", "/control.hard_interrupt"),
            ("agent.models 1", "/agent.models 1"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_runtime_yaml_commands_are_recognized(self):
        for text, expected in (
            ("git status", "/git status"),
            ("git.status", "/git.status"),
            ("git.diff", "/git.diff"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_runtime_command_line(text, "/task"), expected)

    def test_command_unavailable_in_runtime_scope_is_not_promoted(self):
        """A workspace-only command must not become a runtime command."""
        self.assertIsNone(_runtime_command_line("kill 1", "/task"))
        self.assertIsNone(_runtime_command_line("driver 1", "/task"))

    def test_recognition_does_not_depend_on_ambient_scope(self):
        cli_state.current_scope = "workspace"
        self.assertEqual(_runtime_command_line("git status", "/task"), "/git status")

    def test_ambient_scope_is_restored(self):
        cli_state.current_scope = "workspace"
        _runtime_command_line("git status", "/task")
        self.assertEqual(cli_state.current_scope, "workspace")

    def test_quit_and_cd_are_not_commands(self):
        """q/quit/exit/cd keep their own precedence at the dispatch sites."""
        for text in ("q", "quit", "exit", "cd"):
            with self.subTest(text=text):
                self.assertIsNone(_runtime_command_line(text, "/task"))

    def test_shell_escape_is_not_a_command(self):
        self.assertIsNone(_runtime_command_line("!git status", "/task"))


class TestRawDispatchOptionalSlash(unittest.TestCase):
    """Tests for the raw (--runtime-raw) dispatch site."""

    def setUp(self):
        self.previous_commands = cli_state.yaml_commands
        self.previous_scope = cli_state.current_scope
        cli_state.yaml_commands = yaml_commands.load_yaml_commands()
        cli_state.current_scope = "runtime"

    def tearDown(self):
        cli_state.yaml_commands = self.previous_commands
        cli_state.current_scope = self.previous_scope

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_bare_send_delegates_as_slash_command(self, mock_handle):
        result = _dispatch_input(
            "send hello", "/task", [], "s1", "/task/s.log", default_pid=None
        )
        self.assertTrue(result)
        mock_handle.assert_called_once_with(
            "/send hello",
            "/task",
            [],
            "s1",
            "/task/s.log",
            None,
            default_session_pid=None,
        )

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_slash_send_still_delegates(self, mock_handle):
        result = _dispatch_input(
            "/send hello", "/task", [], "s1", "/task/s.log", default_pid=None
        )
        self.assertTrue(result)
        self.assertEqual(mock_handle.call_args[0][0], "/send hello")

    @patch("cli_topsailai.streaming._prompt_send_as_message")
    def test_plain_text_prompts_send_as_message(self, mock_prompt):
        mock_prompt.return_value = True
        result = _dispatch_input(
            "hello world", "/task", [], "s1", "/task/s.log", default_pid=None
        )
        self.assertTrue(result)
        mock_prompt.assert_called_once_with(
            "hello world",
            "/task",
            [],
            "s1",
            "/task/s.log",
            None,
            input_provider=None,
            output_callback=None,
            input_callback=None,
        )

    def test_quit_and_cd_keep_precedence(self):
        for cmd in ("q", "quit", "exit", "cd", "/cd"):
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    _dispatch_input(
                        cmd, "/task", [], "s1", "/task/s.log", default_pid=None
                    )
                )


class TestCursesHandlerOptionalSlash(unittest.TestCase):
    """Tests for the curses two-pane dispatch site."""

    def setUp(self):
        self.previous_commands = cli_state.yaml_commands
        self.previous_scope = cli_state.current_scope
        cli_state.yaml_commands = yaml_commands.load_yaml_commands()
        cli_state.current_scope = "runtime"
        self.ui = MagicMock()
        self.ui.read_multi_line_blocking.return_value = "multi-line message"
        self.handler = _build_stream_command_handler(
            self.ui,
            "/tmp/tasks",
            [{"filename": "s1.stdout"}],
            "s1",
            "/tmp/tasks/s1.123.session.stdout",
            default_pid=123,
        )

    def tearDown(self):
        cli_state.yaml_commands = self.previous_commands
        cli_state.current_scope = self.previous_scope

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_bare_send_delegates_as_slash_command(self, mock_handle):
        self.assertTrue(self.handler("send hello"))
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], "/send hello")

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_bare_ctx_btw_delegates(self, mock_handle):
        self.assertTrue(self.handler("ctx.btw remember this"))
        self.assertEqual(mock_handle.call_args[0][0], "/ctx.btw remember this")

    @patch("cli_topsailai.streaming._prompt_send_as_message")
    def test_plain_text_prompts_send_as_message(self, mock_prompt):
        self.assertTrue(self.handler("hello world"))
        mock_prompt.assert_called_once()
        self.assertEqual(mock_prompt.call_args[0][0], "hello world")

    @patch("cli_topsailai.streaming._handle_stream_command")
    def test_quit_and_cd_keep_precedence(self, mock_handle):
        for cmd in ("q", "quit", "cd", "/cd"):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.handler(cmd))
        mock_handle.assert_not_called()


class TestLegacyLoopOptionalSlash(unittest.TestCase):
    """Tests for the legacy single-pane dispatch site."""

    def setUp(self):
        self.previous_commands = cli_state.yaml_commands
        self.previous_scope = cli_state.current_scope
        cli_state.yaml_commands = yaml_commands.load_yaml_commands()
        cli_state.current_scope = "runtime"
        cli_state.running = True

    def tearDown(self):
        cli_state.yaml_commands = self.previous_commands
        cli_state.current_scope = self.previous_scope
        cli_state.running = True

    def _run_legacy(self, inputs):
        """Run the legacy loop over *inputs* and return the patched mocks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "s1.1234.session.stdout")
            with open(path, "w", encoding="utf-8") as stream_file:
                stream_file.write("existing line\n")

            with patch(
                "cli_topsailai.streaming._maybe_exit_on_dead_session",
                return_value=True,
            ), patch(
                "cli_topsailai.streaming._persist_runtime_command"
            ), patch(
                "cli_topsailai.streaming._prompt_send_as_message"
            ) as mock_prompt, patch(
                "cli_topsailai.streaming._handle_stream_command"
            ) as mock_handle, patch(
                "cli_topsailai.streaming._read_input_line"
            ) as mock_read, patch(
                "cli_topsailai.streaming.select.select"
            ) as mock_select, patch(
                "cli_topsailai.streaming.sys.stdin.isatty", return_value=True
            ), patch(
                "cli_topsailai.streaming.subprocess.run"
            ):
                mock_select.return_value = ([sys.stdin], [], [])
                mock_read.side_effect = list(inputs) + ["q"]
                _stream_file_legacy(
                    path, tmpdir, [], "s1", path, default_pid=1234
                )
                return mock_handle, mock_prompt

    def test_bare_send_delegates_as_slash_command(self):
        mock_handle, mock_prompt = self._run_legacy(["send hello"])
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], "/send hello")
        mock_prompt.assert_not_called()

    def test_plain_text_prompts_send_as_message(self):
        mock_handle, mock_prompt = self._run_legacy(["hello world"])
        mock_prompt.assert_called_once()
        self.assertEqual(mock_prompt.call_args[0][0], "hello world")
        mock_handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
