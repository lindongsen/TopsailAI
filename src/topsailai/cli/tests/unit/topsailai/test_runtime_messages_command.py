#!/usr/bin/env python3
"""Runtime-scope ``messages`` command.

Typing ``messages`` (or ``/messages``) while streaming a log must print the
watched session's history with exactly the same effect as the workspace-scope
``messages`` alias. Both scopes therefore share one retrieval function,
``retrieve.show_session_history``; these tests pin recognition, dispatch,
argument handling, and discoverability so the command cannot work while staying
undiscoverable.

Author: DawsonLin
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
from cli_topsailai import completer, help_text, retrieve, yaml_commands
from cli_topsailai.streaming import (
    _handle_stream_command,
    _handle_stream_messages,
    _runtime_command_line,
)


class RuntimeStateMixin(unittest.TestCase):
    """Load the real YAML command set and enter runtime scope."""

    def setUp(self):
        self.previous_commands = cli_state.yaml_commands
        self.previous_scope = cli_state.current_scope
        cli_state.yaml_commands = yaml_commands.load_yaml_commands()
        cli_state.current_scope = "runtime"

    def tearDown(self):
        cli_state.yaml_commands = self.previous_commands
        cli_state.current_scope = self.previous_scope


class TestRuntimeMessagesRecognition(RuntimeStateMixin):
    """The command is recognized with and without the leading slash."""

    def test_bare_spelling_is_recognized(self):
        """Typing ``messages`` alone becomes the canonical command."""
        self.assertEqual(_runtime_command_line("messages", "/task"), "/messages")

    def test_slash_spelling_is_recognized(self):
        """The canonical spelling is returned unchanged."""
        self.assertEqual(_runtime_command_line("/messages", "/task"), "/messages")

    def test_leading_whitespace_is_stripped(self):
        """Surrounding whitespace must not shift the command prefix."""
        self.assertEqual(_runtime_command_line("   messages  ", "/task"), "/messages")

    def test_argument_is_preserved_for_the_handler_to_reject(self):
        """An argument reaches the handler instead of being silently dropped."""
        self.assertEqual(
            _runtime_command_line("messages 3", "/task"), "/messages 3"
        )

    def test_plain_text_is_still_not_a_command(self):
        """A word that merely resembles the command is not the command."""
        self.assertIsNone(_runtime_command_line("messaging please", "/task"))


class TestRuntimeMessagesDispatch(RuntimeStateMixin):
    """The dispatcher routes the command to its dedicated handler."""

    def test_dispatch_calls_the_messages_handler(self):
        """``/messages`` is routed to ``_handle_stream_messages``."""
        with patch("cli_topsailai.streaming._handle_stream_messages") as handler:
            _handle_stream_command(
                "/messages", "/task", [], "s1", "/task/s1.1.session.stdout",
                default_pid=1, default_session_pid=1,
            )
        handler.assert_called_once_with("/messages", "/task", "s1", 1)

    def test_dispatch_does_not_fall_through_to_yaml_commands(self):
        """The built-in handler wins over any YAML command matching."""
        with patch("cli_topsailai.streaming._handle_stream_messages") as handler, \
                patch("cli_topsailai.streaming.yaml_commands.match_yaml_command") as match:
            _handle_stream_command(
                "/messages", "/task", [], "s1", None, default_session_pid=1
            )
        handler.assert_called_once()
        match.assert_not_called()


class TestRuntimeMessagesHandler(RuntimeStateMixin):
    """The handler delegates to the shared retrieval path."""

    def test_real_session_uses_the_shared_path(self):
        """A real session id is handed to the shared retrieval function."""
        calls = []

        def fake_show(session_id, task_dir, **kwargs):
            calls.append((session_id, task_dir, kwargs))
            return True

        with patch.object(retrieve, "show_session_history", fake_show):
            _handle_stream_messages("/messages", "/task", "s1", 4242)

        self.assertEqual(len(calls), 1)
        session_id, task_dir, kwargs = calls[0]
        self.assertEqual((session_id, task_dir), ("s1", "/task"))
        self.assertEqual(kwargs["row"]["session_id"], "s1")
        self.assertEqual(kwargs["row"]["session_pid"], 4242)
        self.assertFalse(kwargs["row"]["is_task"])

    def test_unknown_session_pid_leaves_the_row_unset(self):
        """Without a known PID the shared path resolves the socket itself."""
        calls = []

        def fake_show(session_id, task_dir, **kwargs):
            calls.append(kwargs)
            return True

        with patch.object(retrieve, "show_session_history", fake_show):
            _handle_stream_messages("/messages", "/task", "s1", None)

        self.assertIsNone(calls[0]["row"])

    def test_temporary_session_is_passed_through(self):
        """A temporary session keeps its reserved identity for translation."""
        calls = []

        def fake_show(session_id, task_dir, **kwargs):
            calls.append(session_id)
            return True

        with patch.object(retrieve, "show_session_history", fake_show):
            _handle_stream_messages("/messages", "/task", "topsailai", 77)

        self.assertEqual(calls, ["topsailai"])

    def test_argument_is_rejected_with_usage(self):
        """Runtime scope already targets a session, so an argument is refused."""
        with patch.object(retrieve, "show_session_history") as show, \
                patch("sys.stdout") as stdout:
            _handle_stream_messages("/messages 3", "/task", "s1", 1)

        show.assert_not_called()
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("Usage: /messages", printed)

    def test_missing_session_reports_an_error(self):
        """A log without a session cannot show history."""
        with patch.object(retrieve, "show_session_history") as show, \
                patch("sys.stdout") as stdout:
            _handle_stream_messages("/messages", "/task", None, None)

        show.assert_not_called()
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("No session is associated with this log file.", printed)


class TestRuntimeMessagesDiscoverability(RuntimeStateMixin):
    """The command must be advertised everywhere a runtime command is listed."""

    def test_completion_offers_the_slash_spelling(self):
        """TAB completion offers ``/messages`` in runtime scope."""
        self.assertIn("/messages", completer.get_completion_candidates("/messages"))

    def test_completion_offers_the_bare_spelling(self):
        """The bare spelling completes because the leading slash is optional."""
        self.assertIn("messages", completer.get_completion_candidates("messages"))

    def test_completion_inventory_lists_the_command(self):
        """The advertised inventory contains the canonical spelling."""
        self.assertIn("/messages", completer.get_available_completions())

    def test_help_lists_the_command_in_runtime_scope(self):
        """Runtime help lists ``/messages`` as an available command."""
        with patch("sys.stdout") as stdout:
            help_text.print_help(cli_state.yaml_commands, "runtime")
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("/messages", printed)

    def test_scope_guide_mentions_the_command(self):
        """The runtime scope description names the command."""
        with patch("sys.stdout") as stdout:
            help_text.print_scopes()
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("/messages", printed)

    def test_unknown_command_guidance_mentions_the_command(self):
        """The unknown-command error enumerates the real command set."""
        with patch("sys.stdout") as stdout:
            _handle_stream_command("/nope", "/task", [], "s1", None)
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("/messages", printed)


if __name__ == "__main__":
    unittest.main()
