#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for ai_retrieve_messages.py."""

import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/TopsailAI/cli")

import ai_retrieve_messages


class TestTruncateMessageContent(unittest.TestCase):
    """Tests for truncate_message_content helper."""

    def test_no_max_chars_returns_original(self):
        """When max_chars is None, messages are returned unchanged."""
        messages = [{"role": "user", "content": "hello world"}]
        result = ai_retrieve_messages.truncate_message_content(messages, None)
        self.assertEqual(result, messages)
        self.assertIs(result, messages)

    def test_zero_max_chars_returns_original(self):
        """When max_chars is zero, messages are returned unchanged."""
        messages = [{"role": "user", "content": "hello world"}]
        result = ai_retrieve_messages.truncate_message_content(messages, 0)
        self.assertEqual(result, messages)
        self.assertIs(result, messages)

    def test_negative_max_chars_returns_original(self):
        """When max_chars is negative, messages are returned unchanged."""
        messages = [{"role": "user", "content": "hello world"}]
        result = ai_retrieve_messages.truncate_message_content(messages, -1)
        self.assertEqual(result, messages)
        self.assertIs(result, messages)

    def test_long_content_truncated_with_ellipsis(self):
        """Long content is truncated and suffixed with '...'."""
        messages = [{"role": "user", "content": "hello world"}]
        result = ai_retrieve_messages.truncate_message_content(messages, 5)
        self.assertEqual(result, [{"role": "user", "content": "hello..."}])

    def test_short_content_unchanged(self):
        """Content within the limit is returned unchanged."""
        messages = [{"role": "user", "content": "hi"}]
        result = ai_retrieve_messages.truncate_message_content(messages, 10)
        self.assertEqual(result, [{"role": "user", "content": "hi"}])

    def test_exact_length_content_unchanged(self):
        """Content exactly matching the limit is not truncated."""
        messages = [{"role": "user", "content": "hello"}]
        result = ai_retrieve_messages.truncate_message_content(messages, 5)
        self.assertEqual(result, [{"role": "user", "content": "hello"}])

    def test_empty_content(self):
        """Empty content is handled gracefully."""
        messages = [{"role": "user", "content": ""}]
        result = ai_retrieve_messages.truncate_message_content(messages, 5)
        self.assertEqual(result, [{"role": "user", "content": ""}])

    def test_missing_content_key(self):
        """Messages without a content key are preserved."""
        messages = [{"role": "user"}]
        result = ai_retrieve_messages.truncate_message_content(messages, 5)
        self.assertEqual(result, [{"role": "user"}])

    def test_non_string_content_converted(self):
        """Non-string content is converted to string before truncation."""
        messages = [{"role": "user", "content": 12345}]
        result = ai_retrieve_messages.truncate_message_content(messages, 3)
        self.assertEqual(result, [{"role": "user", "content": "123..."}])

    def test_multiple_messages(self):
        """Each message is truncated independently."""
        messages = [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": "a much longer message"},
        ]
        result = ai_retrieve_messages.truncate_message_content(messages, 10)
        self.assertEqual(result, [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": "a much lon..."},
        ])

    def test_original_messages_not_mutated(self):
        """The original message list and dicts are not modified."""
        messages = [{"role": "user", "content": "hello world"}]
        ai_retrieve_messages.truncate_message_content(messages, 5)
        self.assertEqual(messages, [{"role": "user", "content": "hello world"}])


class TestParseArgs(unittest.TestCase):
    """Tests for command-line argument parsing."""

    def test_session_id_only(self):
        """Only session_id is required."""
        args = ai_retrieve_messages.parse_args(["abc123"])
        self.assertEqual(args.session_id, "abc123")
        self.assertIsNone(args.db_conn)
        self.assertIsNone(args.max_chars)

    def test_session_id_and_db_conn(self):
        """Optional database connection string is parsed positionally."""
        args = ai_retrieve_messages.parse_args(["abc123", "sqlite:///custom.db"])
        self.assertEqual(args.session_id, "abc123")
        self.assertEqual(args.db_conn, "sqlite:///custom.db")
        self.assertIsNone(args.max_chars)

    def test_max_chars_long_option(self):
        """--max-chars is parsed as an integer."""
        args = ai_retrieve_messages.parse_args(["abc123", "--max-chars", "100"])
        self.assertEqual(args.session_id, "abc123")
        self.assertEqual(args.max_chars, 100)

    def test_max_chars_short_option(self):
        """-c is parsed as an integer."""
        args = ai_retrieve_messages.parse_args(["abc123", "-c", "50"])
        self.assertEqual(args.session_id, "abc123")
        self.assertEqual(args.max_chars, 50)

    def test_max_chars_with_db_conn(self):
        """--max-chars can be combined with a database connection string."""
        args = ai_retrieve_messages.parse_args([
            "abc123", "sqlite:///custom.db", "--max-chars", "25"
        ])
        self.assertEqual(args.session_id, "abc123")
        self.assertEqual(args.db_conn, "sqlite:///custom.db")
        self.assertEqual(args.max_chars, 25)


class TestMain(unittest.TestCase):
    """Tests for the main entry point."""

    @patch("ai_retrieve_messages.print_context_messages")
    @patch("ai_retrieve_messages.get_session_manager")
    def test_main_without_max_chars(self, mock_get_manager, mock_print):
        """main retrieves and prints messages without truncation by default."""
        mock_manager = MagicMock()
        mock_manager.retrieve_messages.return_value = [
            {"role": "user", "content": "hello world"}
        ]
        mock_get_manager.return_value = mock_manager

        ai_retrieve_messages.main(["abc123"])

        mock_get_manager.assert_called_once_with(None)
        mock_manager.retrieve_messages.assert_called_once_with("abc123")
        mock_print.assert_called_once_with([
            {"role": "user", "content": "hello world"}
        ])

    @patch("ai_retrieve_messages.print_context_messages")
    @patch("ai_retrieve_messages.get_session_manager")
    def test_main_with_max_chars(self, mock_get_manager, mock_print):
        """main truncates messages when --max-chars is provided."""
        mock_manager = MagicMock()
        mock_manager.retrieve_messages.return_value = [
            {"role": "user", "content": "hello world"}
        ]
        mock_get_manager.return_value = mock_manager

        ai_retrieve_messages.main(["abc123", "--max-chars", "5"])

        mock_get_manager.assert_called_once_with(None)
        mock_manager.retrieve_messages.assert_called_once_with("abc123")
        mock_print.assert_called_once_with([
            {"role": "user", "content": "hello..."}
        ])

    @patch("ai_retrieve_messages.print_context_messages")
    @patch("ai_retrieve_messages.get_session_manager")
    def test_main_with_db_conn(self, mock_get_manager, mock_print):
        """main passes the optional database connection string to the manager."""
        mock_manager = MagicMock()
        mock_manager.retrieve_messages.return_value = []
        mock_get_manager.return_value = mock_manager

        ai_retrieve_messages.main(["abc123", "sqlite:///custom.db"])

        mock_get_manager.assert_called_once_with("sqlite:///custom.db")
        mock_manager.retrieve_messages.assert_called_once_with("abc123")
        mock_print.assert_called_once_with([])

    @patch("ai_retrieve_messages.print_context_messages")
    @patch("ai_retrieve_messages.get_session_manager")
    def test_main_error_exits_with_failure(self, mock_get_manager, mock_print):
        """main exits with code 1 when retrieval fails."""
        mock_get_manager.side_effect = RuntimeError("database error")

        with self.assertRaises(SystemExit) as cm:
            ai_retrieve_messages.main(["abc123"])

        self.assertEqual(cm.exception.code, 1)
        mock_print.assert_not_called()


if __name__ == "__main__":
    unittest.main()
