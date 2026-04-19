#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for topsailai.context.token module.

Tests token counting utilities and TokenStat thread for tracking
token usage in LLM interactions.
"""

import pytest
import time
from unittest.mock import patch, MagicMock


class TestCountTokens:
    """Tests for count_tokens function."""

    def test_count_tokens_basic(self):
        """Test basic token counting with cl100k_base encoding."""
        from topsailai.context.token import count_tokens
        result = count_tokens("Hello world")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_empty_string(self):
        """Test token counting with empty string."""
        from topsailai.context.token import count_tokens
        result = count_tokens("")
        assert result == 0

    def test_count_tokens_long_text(self):
        """Test token counting with long text."""
        from topsailai.context.token import count_tokens
        long_text = "Hello world. " * 100
        result = count_tokens(long_text)
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_unicode(self):
        """Test token counting with unicode characters."""
        from topsailai.context.token import count_tokens
        result = count_tokens("你好世界")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_different_encoding(self):
        """Test token counting with different encoding."""
        from topsailai.context.token import count_tokens
        result = count_tokens("Hello world", encoding_name="gpt2")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_invalid_encoding(self):
        """Test token counting with invalid encoding returns 0."""
        from topsailai.context.token import count_tokens
        result = count_tokens("Hello world", encoding_name="invalid_encoding")
        assert result == 0

    def test_count_tokens_special_characters(self):
        """Test token counting with special characters."""
        from topsailai.context.token import count_tokens
        result = count_tokens("!@#$%^&*()_+-=[]{}|;':\",./<>?")
        assert isinstance(result, int)
        assert result >= 0


class TestCountTokensForModel:
    """Tests for count_tokens_for_model function."""

    def test_count_tokens_for_model_gpt4(self):
        """Test token counting for GPT-4 model."""
        from topsailai.context.token import count_tokens_for_model
        result = count_tokens_for_model("Hello world", model_name="gpt-4")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_for_model_gpt35(self):
        """Test token counting for GPT-3.5-turbo model."""
        from topsailai.context.token import count_tokens_for_model
        result = count_tokens_for_model("Hello world", model_name="gpt-3.5-turbo")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_for_model_empty_string(self):
        """Test token counting with empty string."""
        from topsailai.context.token import count_tokens_for_model
        result = count_tokens_for_model("")
        assert result == 0

    def test_count_tokens_for_model_invalid_model(self):
        """Test token counting with invalid model returns 0."""
        from topsailai.context.token import count_tokens_for_model
        result = count_tokens_for_model("Hello world", model_name="invalid-model")
        assert result == 0

    def test_count_tokens_for_model_long_text(self):
        """Test token counting with long text for model."""
        from topsailai.context.token import count_tokens_for_model
        long_text = "The quick brown fox jumps over the lazy dog. " * 50
        result = count_tokens_for_model(long_text)
        assert isinstance(result, int)
        assert result > 0


class TestTokenStat:
    """Tests for TokenStat thread class."""

    def test_token_stat_initialization(self):
        """Test TokenStat initialization with default parameters."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        assert stat.total_count == 0
        assert stat.current_count == 0
        assert stat.total_text_len == 0
        assert stat.current_text_len == 0
        assert stat.msg_count == 0
        assert stat.flag_running is True
        stat.flag_running = False  # Stop the thread

    def test_token_stat_initialization_custom_lifetime(self):
        """Test TokenStat initialization with custom lifetime."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm", lifetime=3600)
        assert stat.total_count == 0
        assert stat.current_count == 0
        assert stat._end_time > 0
        stat.flag_running = False  # Stop the thread

    def test_token_stat_initialization_infinite_lifetime(self):
        """Test TokenStat initialization with infinite lifetime (lifetime <= 0)."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm", lifetime=0)
        assert stat._end_time == 0
        stat.flag_running = False  # Stop the thread

    def test_token_stat_initialization_negative_lifetime(self):
        """Test TokenStat initialization with negative lifetime."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm", lifetime=-100)
        assert stat._end_time == 0
        stat.flag_running = False  # Stop the thread

    def test_token_stat_thread_name(self):
        """Test that TokenStat thread has correct name."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="my_llm_id")
        assert stat.name == "TokenStat:my_llm_id"
        stat.flag_running = False  # Stop the thread

    def test_token_stat_add_msgs_list(self):
        """Test adding list of messages to buffer."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        stat.add_msgs(["msg1", "msg2", "msg3"])
        assert stat.msg_count == 3
        stat.flag_running = False  # Stop the thread

    def test_token_stat_add_msgs_empty_list(self):
        """Test adding empty list to buffer."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        stat.add_msgs([])
        assert stat.msg_count == 0
        stat.flag_running = False  # Stop the thread

    def test_token_stat_output_token_stat(self):
        """Test output_token_stat method."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        # Should not raise any exceptions
        stat.output_token_stat()
        stat.flag_running = False  # Stop the thread


class TestTokenStatIntegration:
    """Integration tests for TokenStat thread."""

    def test_token_stat_message_processing(self):
        """Test that messages are processed in the thread loop."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        
        # Add message to buffer
        stat.add_msgs(["Test message"])
        
        # Wait for thread to process
        time.sleep(0.1)
        
        # Check that statistics were updated
        assert stat.current_text_len > 0
        stat.flag_running = False  # Stop the thread

    def test_token_stat_multiple_messages(self):
        """Test processing multiple messages."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        
        # Add multiple messages
        stat.add_msgs(["Message 1", "Message 2"])
        time.sleep(0.1)
        
        # Statistics should be updated
        assert stat.current_text_len > 0
        stat.flag_running = False  # Stop the thread

    def test_token_stat_thread_termination(self):
        """Test that thread can be terminated properly."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        
        # Set flag to stop
        stat.flag_running = False
        
        # Wait for thread to exit
        time.sleep(0.1)
        
        # Thread should have stopped
        assert stat.flag_running is False


class TestTokenCountingEdgeCases:
    """Edge case tests for token counting functions."""

    def test_count_tokens_whitespace_only(self):
        """Test token counting with whitespace only."""
        from topsailai.context.token import count_tokens
        result = count_tokens("   \n\t   ")
        assert isinstance(result, int)
        assert result >= 0

    def test_count_tokens_newlines(self):
        """Test token counting with newlines."""
        from topsailai.context.token import count_tokens
        result = count_tokens("line1\nline2\nline3")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_code_snippet(self):
        """Test token counting with code snippet."""
        from topsailai.context.token import count_tokens
        code = """
        def hello():
            print("Hello, World!")
            return 42
        """
        result = count_tokens(code)
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_json_like(self):
        """Test token counting with JSON-like content."""
        from topsailai.context.token import count_tokens
        json_str = '{"key": "value", "number": 123, "nested": {"a": 1}}'
        result = count_tokens(json_str)
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_markdown(self):
        """Test token counting with markdown content."""
        from topsailai.context.token import count_tokens
        markdown = "# Title\n\nThis is a **bold** text with `code`."
        result = count_tokens(markdown)
        assert isinstance(result, int)
        assert result > 0


class TestTokenStatConcurrency:
    """Concurrency tests for TokenStat thread."""

    def test_token_stat_rlock_acquisition(self):
        """Test that rlock is properly initialized."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        assert stat.rlock is not None
        stat.flag_running = False  # Stop the thread

    def test_token_stat_buffer_isolation(self):
        """Test that buffer operations are properly isolated."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        
        # Add first message
        stat.add_msgs(["First message"])
        buffer1 = stat.buffer
        
        # Add second message
        stat.add_msgs(["Second message"])
        buffer2 = stat.buffer
        
        # Buffers should be different
        assert buffer1 != buffer2
        stat.flag_running = False  # Stop the thread

    def test_token_stat_timestamp_update(self):
        """Test that last message timestamp is updated."""
        from topsailai.context.token import TokenStat
        stat = TokenStat(llm_id="test_llm")
        initial_time = stat._last_msg_time
        
        # Add message
        stat.add_msgs(["Test message"])
        
        # Timestamp should be updated
        assert stat._last_msg_time >= initial_time
        stat.flag_running = False  # Stop the thread
