"""
Unit tests for context/token.py

This module tests token counting utilities and TokenStat class
for tracking token usage in LLM interactions.

Author: mm-m25
"""

import time
import unittest
from unittest.mock import patch, MagicMock

from topsailai.context.token import (
    count_tokens,
    count_tokens_for_model,
    TokenStat,
)


class TestCountTokens(unittest.TestCase):
    """Test cases for count_tokens function."""

    def test_count_tokens_simple_text(self):
        """Test counting tokens for simple English text."""
        result = count_tokens("Hello world")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_tokens_empty_string(self):
        """Test counting tokens for empty string."""
        result = count_tokens("")
        self.assertEqual(result, 0)

    def test_count_tokens_longer_text(self):
        """Test counting tokens for longer text."""
        text = "This is a longer piece of text that should have more tokens."
        result = count_tokens(text)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 5)

    def test_count_tokens_unicode(self):
        """Test counting tokens for unicode text."""
        text = "你好世界 Hello World"
        result = count_tokens(text)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_tokens_special_characters(self):
        """Test counting tokens for special characters."""
        text = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        result = count_tokens(text)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_tokens_different_encoding(self):
        """Test counting tokens with different encoding."""
        text = "Hello world"
        result = count_tokens(text, encoding_name="gpt2")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_tokens_invalid_encoding(self):
        """Test counting tokens with invalid encoding returns 0."""
        result = count_tokens("test", encoding_name="invalid_encoding")
        self.assertEqual(result, 0)

    def test_count_tokens_multiline_text(self):
        """Test counting tokens for multiline text."""
        text = "Line 1\nLine 2\nLine 3"
        result = count_tokens(text)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 5)


class TestCountTokensForModel(unittest.TestCase):
    """Test cases for count_tokens_for_model function."""

    def test_count_tokens_for_model_gpt4(self):
        """Test counting tokens for GPT-4 model."""
        result = count_tokens_for_model("Hello world", "gpt-4")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_tokens_for_model_gpt35(self):
        """Test counting tokens for GPT-3.5-turbo model."""
        result = count_tokens_for_model("Hello world", "gpt-3.5-turbo")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_tokens_for_model_default(self):
        """Test counting tokens with default model."""
        result = count_tokens_for_model("Hello world")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_count_tokens_for_model_empty_string(self):
        """Test counting tokens for empty string."""
        result = count_tokens_for_model("")
        self.assertEqual(result, 0)

    def test_count_tokens_for_model_invalid_model(self):
        """Test counting tokens with invalid model returns 0."""
        result = count_tokens_for_model("test", "invalid-model")
        self.assertEqual(result, 0)


class TestTokenStat(unittest.TestCase):
    """Test cases for TokenStat class."""

    def setUp(self):
        """Set up test fixtures."""
        self.llm_id = "test_llm"

    def tearDown(self):
        """Clean up after tests."""
        pass

    def test_token_stat_init_basic(self):
        """Test TokenStat initialization with basic parameters."""
        stat = TokenStat(self.llm_id, lifetime=0)
        self.assertEqual(stat.total_count, 0)
        self.assertEqual(stat.current_count, 0)
        self.assertEqual(stat.total_text_len, 0)
        self.assertEqual(stat.current_text_len, 0)
        self.assertEqual(stat.msg_count, 0)
        self.assertTrue(stat.flag_running)
        stat.flag_running = False  # Stop the thread

    def test_token_stat_init_with_lifetime(self):
        """Test TokenStat initialization with lifetime."""
        lifetime = 3600  # 1 hour
        stat = TokenStat(self.llm_id, lifetime=lifetime)
        self.assertGreater(stat._end_time, stat._start_time)
        self.assertEqual(stat._end_time, stat._start_time + lifetime + 60)
        stat.flag_running = False

    def test_token_stat_thread_name(self):
        """Test TokenStat thread has correct name."""
        stat = TokenStat(self.llm_id, lifetime=0)
        self.assertEqual(stat.name, f"TokenStat:{self.llm_id}")
        self.assertTrue(stat.daemon)
        stat.flag_running = False

    def test_token_stat_add_msgs_single_string(self):
        """Test adding single string message."""
        stat = TokenStat(self.llm_id, lifetime=0)
        stat.add_msgs("test message")
        # msg_count is len(msgs), so for string it's character count
        self.assertEqual(stat.msg_count, len("test message"))
        self.assertEqual(stat.current_count, 0)  # Not processed yet
        stat.flag_running = False

    def test_token_stat_add_msgs_list(self):
        """Test adding list of messages."""
        stat = TokenStat(self.llm_id, lifetime=0)
        stat.add_msgs(["msg1", "msg2", "msg3"])
        self.assertEqual(stat.msg_count, 3)
        stat.flag_running = False

    def test_token_stat_add_msgs_dict(self):
        """Test adding dictionary message."""
        stat = TokenStat(self.llm_id, lifetime=0)
        stat.add_msgs({"key": "value"})
        self.assertEqual(stat.msg_count, 1)
        stat.flag_running = False

    def test_token_stat_add_msgs_empty_list(self):
        """Test adding empty list."""
        stat = TokenStat(self.llm_id, lifetime=0)
        stat.add_msgs([])
        self.assertEqual(stat.msg_count, 0)
        stat.flag_running = False

    @patch('topsailai.context.token.count_tokens')
    def test_token_stat_process_message(self, mock_count_tokens):
        """Test that TokenStat processes buffered messages."""
        mock_count_tokens.return_value = 10
        
        stat = TokenStat(self.llm_id, lifetime=0)
        stat.add_msgs("test message")
        
        # Wait for thread to process
        time.sleep(0.1)
        
        self.assertEqual(stat.current_count, 10)
        self.assertGreater(stat.current_text_len, 0)
        stat.flag_running = False

    @patch('topsailai.context.token.count_tokens')
    def test_token_stat_accumulates_tokens(self, mock_count_tokens):
        """Test that TokenStat accumulates token counts."""
        mock_count_tokens.return_value = 5
        
        stat = TokenStat(self.llm_id, lifetime=0)
        
        # Add first message
        stat.add_msgs("first")
        time.sleep(0.1)
        first_total = stat.total_count
        
        # Add second message
        stat.add_msgs("second")
        time.sleep(0.1)
        
        self.assertGreater(stat.total_count, first_total)
        stat.flag_running = False

    def test_token_stat_output_token_stat(self):
        """Test output_token_stat method."""
        stat = TokenStat(self.llm_id, lifetime=0)
        # Should not raise any exceptions
        stat.output_token_stat()
        stat.flag_running = False

    def test_token_stat_rlock_exists(self):
        """Test that rlock is properly initialized."""
        stat = TokenStat(self.llm_id, lifetime=0)
        self.assertIsNotNone(stat.rlock)
        stat.flag_running = False


class TestTokenStatEdgeCases(unittest.TestCase):
    """Test edge cases for TokenStat class."""

    def setUp(self):
        """Set up test fixtures."""
        self.llm_id = "test_edge"

    def tearDown(self):
        """Clean up after tests."""
        pass

    def test_token_stat_negative_lifetime(self):
        """Test TokenStat with negative lifetime (infinite)."""
        stat = TokenStat(self.llm_id, lifetime=-1)
        self.assertEqual(stat._end_time, 0)
        stat.flag_running = False

    def test_token_stat_zero_lifetime(self):
        """Test TokenStat with zero lifetime (infinite)."""
        stat = TokenStat(self.llm_id, lifetime=0)
        self.assertEqual(stat._end_time, 0)
        stat.flag_running = False

    def test_token_stat_special_characters_in_llm_id(self):
        """Test TokenStat with special characters in LLM ID."""
        stat = TokenStat("test-llm_v1.0", lifetime=0)
        self.assertIn("test-llm_v1.0", stat.name)
        stat.flag_running = False

    @patch('topsailai.context.token.count_tokens')
    def test_token_stat_very_long_message(self, mock_count_tokens):
        """Test TokenStat with very long message."""
        mock_count_tokens.return_value = 1000
        
        stat = TokenStat(self.llm_id, lifetime=0)
        long_message = "x" * 10000
        stat.add_msgs(long_message)
        time.sleep(0.1)
        
        self.assertGreater(stat.current_text_len, 9000)
        stat.flag_running = False


class TestTokenStatThreadSafety(unittest.TestCase):
    """Test thread safety aspects of TokenStat class."""

    def setUp(self):
        """Set up test fixtures."""
        self.llm_id = "test_thread"

    def tearDown(self):
        """Clean up after tests."""
        pass

    def test_token_stat_multiple_add_msgs(self):
        """Test adding multiple messages in sequence."""
        stat = TokenStat(self.llm_id, lifetime=0)
        
        for i in range(5):
            stat.add_msgs(f"message {i}")
            time.sleep(0.02)
        
        # msg_count is len(msgs), so for string it's character count
        expected_len = len(f"message {4}")
        self.assertEqual(stat.msg_count, expected_len)
        stat.flag_running = False

    def test_token_stat_concurrent_buffer_access(self):
        """Test concurrent buffer access doesn't cause issues."""
        stat = TokenStat(self.llm_id, lifetime=0)
        
        # Add messages rapidly
        for i in range(10):
            stat.add_msgs(f"rapid message {i}")
        
        # Should not raise any exceptions
        self.assertIsNotNone(stat.buffer)
        stat.flag_running = False


if __name__ == '__main__':
    unittest.main()
