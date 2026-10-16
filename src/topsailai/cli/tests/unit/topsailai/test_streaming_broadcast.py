#!/usr/bin/env python3
"""Unit tests for the runtime /ctx.btw-all dispatcher."""

import io
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))) )

from cli_topsailai import runtime_broadcast
from cli_topsailai.streaming import _handle_stream_command


class TestStreamingBroadcast(unittest.TestCase):
    """Verify exact command routing and message acquisition."""

    def _result(self, *outcomes):
        return runtime_broadcast.BroadcastResult("named", tuple(outcomes))

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_inline_message_routes_to_broadcast_once(self, broadcast):
        """Inline content is passed unchanged to the dedicated broadcaster."""
        broadcast.return_value = self._result(
            runtime_broadcast.BroadcastOutcome(101, "queued")
        )
        _handle_stream_command(
            "/ctx.btw-all hello 'quoted' | text",
            "/task",
            [],
            "named",
            "/task/named.101.session.stdout",
            default_pid=101,
        )
        broadcast.assert_called_once()
        self.assertEqual(broadcast.call_args.args, ("/task", "named", "hello 'quoted' | text"))

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_multiline_provider_is_called_once_and_cancel_writes_nothing(self, broadcast):
        """A provider payload is broadcast once; cancellation is a no-op."""
        broadcast.return_value = self._result(
            runtime_broadcast.BroadcastOutcome(101, "queued"),
            runtime_broadcast.BroadcastOutcome(102, "queued"),
        )
        provider = Mock(return_value="line one\nline two")
        _handle_stream_command(
            "/ctx.btw-all",
            "/task",
            [],
            "named",
            None,
            input_provider=provider,
        )
        provider.assert_called_once()
        broadcast.assert_called_once()
        self.assertEqual(broadcast.call_args.args, ("/task", "named", "line one\nline two"))

        broadcast.reset_mock()
        provider.reset_mock()
        provider.return_value = None
        _handle_stream_command(
            "/ctx.btw-all",
            "/task",
            [],
            "named",
            None,
            input_provider=provider,
        )
        broadcast.assert_not_called()

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_empty_message_and_temporary_session_do_not_broadcast(self, broadcast):
        """Empty input and temporary sessions fail closed."""
        _handle_stream_command(
            "/ctx.btw-all   ", "/task", [], "named", None,
            input_provider=lambda prompt: "  \n",
        )
        _handle_stream_command(
            "/ctx.btw-all hello", "/task", [], "topsailai", None,
        )
        broadcast.assert_not_called()

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_prefix_lookalike_is_not_broadcast(self, broadcast):
        """The command parser must require the complete command token."""
        with patch("builtins.print"):
            _handle_stream_command(
                "/ctx.btw-all-extra hello", "/task", [], "named", None
            )
        broadcast.assert_not_called()

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_result_display_reports_each_target_and_queue_boundary(self, broadcast):
        """Per-target statuses and queue-only semantics are visible to users."""
        def emit_progress(task_dir, session, message, *, progress_callback):
            first = runtime_broadcast.BroadcastOutcome(101, "queued")
            progress_callback("snapshot", 2)
            progress_callback("outcome", first)
            second = runtime_broadcast.BroadcastOutcome(102, "delivery_unknown", "write failed")
            progress_callback("outcome", second)
            return self._result(first, second)
        broadcast.side_effect = emit_progress
        output = io.StringIO()
        with patch("sys.stdout", output):
            _handle_stream_command(
                "/ctx.btw-all hello", "/task", [], "named", None
            )
        text = output.getvalue()
        self.assertIn("PID 101: queued", text)
        self.assertIn("PID 102: delivery_unknown: write failed", text)
        self.assertIn("does not confirm message consumption", text)

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_message_boundaries_reject_before_broadcast(self, broadcast):
        """Invalid surrogate and over-limit payloads do not enumerate targets."""
        _handle_stream_command("/ctx.btw-all " + "x" * (1024 * 1024 + 1), "/task", [], "named", None)
        broadcast.assert_not_called()
        broadcast.reset_mock()
        _handle_stream_command("/ctx.btw-all "+"\udcff", "/task", [], "named", None)
        broadcast.assert_not_called()

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_exact_limit_and_multibyte_message_are_accepted(self, broadcast):
        """The byte limit applies to the message, including multibyte UTF-8 data."""
        limit = 1024 * 1024
        broadcast.return_value = self._result(runtime_broadcast.BroadcastOutcome(101, "queued"))
        exact = "x" * limit
        _handle_stream_command("/ctx.btw-all " + exact, "/task", [], "named", None)
        self.assertEqual(broadcast.call_args.args[2], exact)
        self.assertEqual(len(exact.encode("utf-8")), limit)
        broadcast.reset_mock()
        multibyte = "é" * (limit // 2)
        _handle_stream_command("/ctx.btw-all " + multibyte, "/task", [], "named", None)
        self.assertEqual(broadcast.call_args.args[2], multibyte)
        self.assertEqual(len(multibyte.encode("utf-8")), limit)
        broadcast.reset_mock()
        _handle_stream_command("/ctx.btw-all " + multibyte + "é", "/task", [], "named", None)
        broadcast.assert_not_called()

    @patch("cli_topsailai.streaming.runtime_broadcast.broadcast_message")
    def test_interrupt_preserves_already_reported_progress(self, broadcast):
        """A host interrupt after one result preserves that visible result."""
        def interrupt_after_first(task_dir, session, message, *, progress_callback):
            progress_callback("snapshot", 2)
            progress_callback("outcome", runtime_broadcast.BroadcastOutcome(101, "queued"))
            raise KeyboardInterrupt
        broadcast.side_effect = interrupt_after_first
        output = io.StringIO()
        with patch("sys.stdout", output):
            with self.assertRaises(KeyboardInterrupt):
                _handle_stream_command("/ctx.btw-all hello", "/task", [], "named", None)
        self.assertIn("PID 101: queued", output.getvalue())


if __name__ == "__main__":
    unittest.main()
