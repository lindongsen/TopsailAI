"""
Unit tests for context/ctx_safe.py - Message truncation utilities.

Author: mm-m25
Purpose: Test message truncation functionality for agent contexts
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestCtxSafeConstants(unittest.TestCase):
    """Test module-level constants."""

    def test_max_msg_size_value(self):
        """Test MAX_MSG_SIZE constant value is 3000."""
        from topsailai.context.ctx_safe import MAX_MSG_SIZE
        self.assertEqual(MAX_MSG_SIZE, 3000)

    def test_large_msg_size_value(self):
        """Test LARGE_MSG_SIZE constant value is 13000."""
        from topsailai.context.ctx_safe import LARGE_MSG_SIZE
        self.assertEqual(LARGE_MSG_SIZE, 13000)

    def test_suffix_truncate_value(self):
        """Test SUFFIX_TRUNCATE constant value."""
        from topsailai.context.ctx_safe import SUFFIX_TRUNCATE
        self.assertEqual(SUFFIX_TRUNCATE, " ... (force to truncate)")


class TestIsNeedTruncate(unittest.TestCase):
    """Test is_need_truncate function."""

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_need_truncate_standard_agent_at_limit(self, mock_get_agent_name):
        """Test truncation needed for standard agent at MAX_MSG_SIZE."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import is_need_truncate, MAX_MSG_SIZE
        result = is_need_truncate(MAX_MSG_SIZE)
        self.assertTrue(result)

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_need_truncate_standard_agent_below_limit(self, mock_get_agent_name):
        """Test no truncation for standard agent below MAX_MSG_SIZE."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import is_need_truncate
        result = is_need_truncate(1000)
        self.assertFalse(result)

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_need_truncate_standard_agent_above_limit(self, mock_get_agent_name):
        """Test truncation needed for standard agent above MAX_MSG_SIZE."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import is_need_truncate
        result = is_need_truncate(5000)
        self.assertTrue(result)

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_no_truncate_agent_writer_at_large_size(self, mock_get_agent_name):
        """Test no truncation for AgentWriter at LARGE_MSG_SIZE."""
        mock_get_agent_name.return_value = "AgentWriter"
        from topsailai.context.ctx_safe import is_need_truncate, LARGE_MSG_SIZE
        result = is_need_truncate(LARGE_MSG_SIZE)
        self.assertFalse(result)

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_no_truncate_agent_writer_below_large_size(self, mock_get_agent_name):
        """Test no truncation for AgentWriter below LARGE_MSG_SIZE."""
        mock_get_agent_name.return_value = "AgentWriter"
        from topsailai.context.ctx_safe import is_need_truncate
        result = is_need_truncate(10000)
        self.assertFalse(result)

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_need_truncate_agent_writer_above_large_size(self, mock_get_agent_name):
        """Test truncation needed for AgentWriter above LARGE_MSG_SIZE."""
        mock_get_agent_name.return_value = "AgentWriter"
        from topsailai.context.ctx_safe import is_need_truncate, LARGE_MSG_SIZE
        result = is_need_truncate(LARGE_MSG_SIZE + 1)
        self.assertTrue(result)

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_need_truncate_zero_length(self, mock_get_agent_name):
        """Test no truncation for zero length message."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import is_need_truncate
        result = is_need_truncate(0)
        self.assertFalse(result)

    @patch('topsailai.context.ctx_safe.get_agent_name')
    def test_need_truncate_negative_length(self, mock_get_agent_name):
        """Test no truncation for negative length message."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import is_need_truncate
        result = is_need_truncate(-1)
        self.assertFalse(result)


class TestTruncateMessage(unittest.TestCase):
    """Test truncate_message function."""

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_truncate_string_message(self, mock_print_tool, mock_get_agent_name):
        """Test truncation of string message."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message, MAX_MSG_SIZE, SUFFIX_TRUNCATE
        long_message = "a" * (MAX_MSG_SIZE + 100)
        result = truncate_message(long_message)
        self.assertEqual(len(result), MAX_MSG_SIZE + len(SUFFIX_TRUNCATE))
        self.assertTrue(result.endswith(SUFFIX_TRUNCATE))
        mock_print_tool.print_error.assert_called_once()

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_truncate_bytes_message(self, mock_print_tool, mock_get_agent_name):
        """Test truncation of bytes message."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message, MAX_MSG_SIZE, SUFFIX_TRUNCATE
        long_message = b"a" * (MAX_MSG_SIZE + 100)
        result = truncate_message(long_message)
        self.assertIsInstance(result, bytes)
        self.assertEqual(len(result), MAX_MSG_SIZE + len(SUFFIX_TRUNCATE))
        self.assertTrue(result.endswith(b" ... (force to truncate)"))

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_no_truncate_short_string(self, mock_print_tool, mock_get_agent_name):
        """Test no truncation for short string message."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        short_message = "short message"
        result = truncate_message(short_message)
        self.assertEqual(result, short_message)
        mock_print_tool.print_error.assert_not_called()

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_no_truncate_short_bytes(self, mock_print_tool, mock_get_agent_name):
        """Test no truncation for short bytes message."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        short_message = b"short message"
        result = truncate_message(short_message)
        self.assertEqual(result, short_message)
        mock_print_tool.print_error.assert_not_called()

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_truncate_agent_writer_bytes(self, mock_print_tool, mock_get_agent_name):
        """Test AgentWriter truncation with bytes."""
        mock_get_agent_name.return_value = "AgentWriter"
        from topsailai.context.ctx_safe import truncate_message, LARGE_MSG_SIZE
        long_message = b"b" * (LARGE_MSG_SIZE + 100)
        result = truncate_message(long_message)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.endswith(b" ... (force to truncate)"))

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_truncate_empty_string(self, mock_print_tool, mock_get_agent_name):
        """Test truncation of empty string."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        result = truncate_message("")
        self.assertEqual(result, "")
        mock_print_tool.print_error.assert_not_called()

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_truncate_empty_bytes(self, mock_print_tool, mock_get_agent_name):
        """Test truncation of empty bytes."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        result = truncate_message(b"")
        self.assertEqual(result, b"")
        mock_print_tool.print_error.assert_not_called()

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_truncate_unicode_string(self, mock_print_tool, mock_get_agent_name):
        """Test truncation of unicode string."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message, SUFFIX_TRUNCATE
        # Create unicode string longer than MAX_MSG_SIZE (3000)
        unicode_message = "中文" * 2000
        result = truncate_message(unicode_message)
        self.assertTrue(result.endswith(SUFFIX_TRUNCATE))

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_truncate_preserves_content_before_limit(self, mock_print_tool, mock_get_agent_name):
        """Test that content before limit is preserved."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        original_content = "Hello World " * 300
        result = truncate_message(original_content)
        self.assertTrue(result.startswith("Hello World "))
        self.assertEqual(result[:11], "Hello World")


class TestTruncateText(unittest.TestCase):
    """Test truncate_text function."""

    def test_truncate_text_with_suffix(self):
        """Test truncate_text adds suffix."""
        from topsailai.context.ctx_safe import truncate_text, SUFFIX_TRUNCATE
        text = "a" * 100
        result = truncate_text(text, 50)
        self.assertEqual(len(result), 50 + len(SUFFIX_TRUNCATE))
        self.assertTrue(result.endswith(SUFFIX_TRUNCATE))

    def test_truncate_text_exact_size(self):
        """Test truncate_text with exact size match."""
        from topsailai.context.ctx_safe import truncate_text, SUFFIX_TRUNCATE
        text = "hello"
        result = truncate_text(text, 5)
        self.assertEqual(len(result), 5 + len(SUFFIX_TRUNCATE))

    def test_truncate_text_size_zero(self):
        """Test truncate_text with size zero."""
        from topsailai.context.ctx_safe import truncate_text, SUFFIX_TRUNCATE
        text = "hello"
        result = truncate_text(text, 0)
        self.assertEqual(len(result), 0 + len(SUFFIX_TRUNCATE))

    def test_truncate_text_size_larger_than_text(self):
        """Test truncate_text with size larger than text."""
        from topsailai.context.ctx_safe import truncate_text, SUFFIX_TRUNCATE
        text = "hi"
        result = truncate_text(text, 10)
        self.assertEqual(len(result), 2 + len(SUFFIX_TRUNCATE))

    def test_truncate_text_preserves_content(self):
        """Test truncate_text preserves original content prefix."""
        from topsailai.context.ctx_safe import truncate_text
        text = "Hello World"
        result = truncate_text(text, 5)
        self.assertTrue(result.startswith("Hello"))

    def test_truncate_text_empty_string(self):
        """Test truncate_text with empty string."""
        from topsailai.context.ctx_safe import truncate_text, SUFFIX_TRUNCATE
        result = truncate_text("", 10)
        self.assertEqual(len(result), len(SUFFIX_TRUNCATE))

    def test_truncate_text_unicode(self):
        """Test truncate_text with unicode characters."""
        from topsailai.context.ctx_safe import truncate_text, SUFFIX_TRUNCATE
        text = "你好世界"
        result = truncate_text(text, 2)
        self.assertTrue(result.endswith(SUFFIX_TRUNCATE))


class TestEdgeCases(unittest.TestCase):
    """Test edge cases for ctx_safe module."""

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_special_characters_string(self, mock_print_tool, mock_get_agent_name):
        """Test truncation with special characters."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        special_chars = "!@#$%^&*()" * 500
        result = truncate_message(special_chars)
        self.assertTrue(result.startswith("!@#$%^&*()"))

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_multiline_string(self, mock_print_tool, mock_get_agent_name):
        """Test truncation with multiline string."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        multiline = "\n".join(["line"] * 1000)
        result = truncate_message(multiline)
        self.assertTrue(result.startswith("line"))

    @patch('topsailai.context.ctx_safe.get_agent_name')
    @patch('topsailai.context.ctx_safe.print_tool')
    def test_json_string(self, mock_print_tool, mock_get_agent_name):
        """Test truncation with JSON-like string."""
        mock_get_agent_name.return_value = "StandardAgent"
        from topsailai.context.ctx_safe import truncate_message
        json_str = '{"key": "value"}' * 500
        result = truncate_message(json_str)
        self.assertTrue(result.startswith('{"key": "value"}'))


if __name__ == '__main__':
    unittest.main()
