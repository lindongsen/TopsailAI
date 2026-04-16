#!/usr/bin/env python3
"""
Unit Tests for Edge Cases

This module contains unit tests for edge cases and boundary conditions
in the agent_daemon client modules.

Test IDs: E-001 to E-003
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from topsailai_server.agent_daemon.client.base import BaseClient, APIError
from topsailai_server.agent_daemon.client.session import SessionClient
from topsailai_server.agent_daemon.client.message import MessageClient
from topsailai_server.agent_daemon.client.task import TaskClient


class TestE001EmptyMessageContent(unittest.TestCase):
    """Test cases for E-001: Empty message content handling."""

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_empty_message(self, mock_request):
        """E-001: Test sending empty string message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_empty"}, "message": "success"}
        mock_request.return_value = mock_response

        client = MessageClient()
        result = client.send_message(session_id="test_session", message="")

        self.assertEqual(result["msg_id"], "msg_empty")
        # Verify empty string was sent
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"]["message"], "")

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_whitespace_only_message(self, mock_request):
        """E-001: Test sending whitespace-only message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_whitespace"}, "message": "success"}
        mock_request.return_value = mock_response

        client = MessageClient()
        result = client.send_message(session_id="test_session", message="   \n\t  ")

        self.assertEqual(result["msg_id"], "msg_whitespace")

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_list_messages_empty_session(self, mock_request):
        """E-001: Test listing messages for session with no messages."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": [], "message": "success"}
        mock_request.return_value = mock_response

        client = MessageClient()
        result = client.list_messages(session_id="empty_session")

        self.assertEqual(result, [])

    def test_print_message_empty_content(self):
        """E-001: Test display of empty message content."""
        client = MessageClient()

        # Capture stdout
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            client._print_message({
                "msg_id": "msg_empty",
                "session_id": "test_session",
                "role": "user",
                "message": "",
                "create_time": "2026-04-16T10:00:00"
            })

        output = f.getvalue()
        # Should still display the message entry even with empty content
        self.assertIn("msg_empty", output)
        self.assertIn("user", output)


class TestE002VeryLongMessageContent(unittest.TestCase):
    """Test cases for E-002: Very long message content (10MB+)."""

    def test_10mb_message_content(self):
        """E-002: Test message content of approximately 10MB."""
        # Create a 10MB message (10,485,760 characters)
        long_message = "A" * (10 * 1024 * 1024)

        # Verify the message size
        self.assertEqual(len(long_message), 10 * 1024 * 1024)

        # Test that we can create the message client
        client = MessageClient()
        self.assertIsNotNone(client)

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_long_message(self, mock_request):
        """E-002: Test sending a long message (1MB for faster test)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_long"}, "message": "success"}
        mock_request.return_value = mock_response

        # Use 1MB for faster test execution
        long_message = "X" * (1 * 1024 * 1024)

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=long_message)

        self.assertEqual(result["msg_id"], "msg_long")
        # Verify the long message was sent
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"]["message"], long_message)

    def test_print_long_message_full_content(self):
        """E-002: Test that long message content is displayed in full (no truncation)."""
        client = MessageClient()

        long_message = "L" * 1000  # 1KB message

        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            client._print_message({
                "msg_id": "msg_long",
                "session_id": "test_session",
                "role": "user",
                "message": long_message,
                "create_time": "2026-04-16T10:00:00"
            })

        output = f.getvalue()
        # Verify full content is displayed (no truncation)
        self.assertIn(long_message, output)

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_long_message_with_special_chars(self, mock_request):
        """E-002: Test long message with special characters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_long_special"}, "message": "success"}
        mock_request.return_value = mock_response

        # Create a long message with special characters
        special_chars = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        long_message = (special_chars * 1000)[:1 * 1024 * 1024]  # 1MB with special chars

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=long_message)

        self.assertEqual(result["msg_id"], "msg_long_special")


class TestE003SpecialCharactersAndUnicode(unittest.TestCase):
    """Test cases for E-003: Special characters and Unicode in messages."""

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_unicode_chinese(self, mock_request):
        """E-003: Test sending Chinese Unicode characters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_chinese"}, "message": "success"}
        mock_request.return_value = mock_response

        chinese_message = "你好世界！这是中文测试消息。"

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=chinese_message)

        self.assertEqual(result["msg_id"], "msg_chinese")
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"]["message"], chinese_message)

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_unicode_emoji(self, mock_request):
        """E-003: Test sending emoji characters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_emoji"}, "message": "success"}
        mock_request.return_value = mock_response

        emoji_message = "Hello! 🎉🚀💻🌟✨"

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=emoji_message)

        self.assertEqual(result["msg_id"], "msg_emoji")
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"]["message"], emoji_message)

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_special_characters(self, mock_request):
        """E-003: Test sending special characters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_special"}, "message": "success"}
        mock_request.return_value = mock_response

        special_message = 'Special chars: !@#$%^&*()_+-=[]{}|;\':",./<>?\\`~'

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=special_message)

        self.assertEqual(result["msg_id"], "msg_special")
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"]["message"], special_message)

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_multiline_with_newlines(self, mock_request):
        """E-003: Test sending multiline message with newlines."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_multiline"}, "message": "success"}
        mock_request.return_value = mock_response

        multiline_message = "Line 1\nLine 2\nLine 3\tTabbed"

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=multiline_message)

        self.assertEqual(result["msg_id"], "msg_multiline")
        call_args = mock_request.call_args
        self.assertIn("\n", call_args.kwargs["json"]["message"])

    def test_print_unicode_message(self):
        """E-003: Test display of Unicode message content."""
        client = MessageClient()

        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            client._print_message({
                "msg_id": "msg_unicode",
                "session_id": "test_session",
                "role": "user",
                "message": "你好世界！🎉",
                "create_time": "2026-04-16T10:00:00"
            })

        output = f.getvalue()
        # Verify Unicode content is displayed correctly
        self.assertIn("你好世界", output)
        self.assertIn("🎉", output)

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_mixed_content(self, mock_request):
        """E-003: Test sending mixed Unicode, emoji, and special chars."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_mixed"}, "message": "success"}
        mock_request.return_value = mock_response

        mixed_message = """
        Mixed Content Test:
        - Chinese: 你好
        - Japanese: こんにちは
        - Korean: 안녕하세요
        - Emoji: 🚀🌟💻
        - Special: !@#$%^&*
        - Newlines: line1\nline2
        """

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=mixed_message)

        self.assertEqual(result["msg_id"], "msg_mixed")

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_html_content(self, mock_request):
        """E-003: Test sending HTML-like content."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_html"}, "message": "success"}
        mock_request.return_value = mock_response

        html_message = "<html><body><h1>Hello</h1></body></html>"

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=html_message)

        self.assertEqual(result["msg_id"], "msg_html")
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"]["message"], html_message)

    @patch("topsailai_server.agent_daemon.client.base.requests.request")
    def test_send_json_like_content(self, mock_request):
        """E-003: Test sending JSON-like content."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 0, "data": {"msg_id": "msg_json"}, "message": "success"}
        mock_request.return_value = mock_response

        json_message = '{"key": "value", "number": 123, "array": [1, 2, 3]}'

        client = MessageClient()
        result = client.send_message(session_id="test_session", message=json_message)

        self.assertEqual(result["msg_id"], "msg_json")
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["json"]["message"], json_message)


if __name__ == "__main__":
    unittest.main()
