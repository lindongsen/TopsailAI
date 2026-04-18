#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for topsailai.context.ctx_safe module.

Tests message truncation utilities for managing message size limits
in different agent contexts (regular agents vs AgentWriter).
"""

import pytest
from unittest.mock import patch, MagicMock

from topsailai.context.ctx_safe import (
    is_need_truncate,
    truncate_message,
    truncate_text,
    MAX_MSG_SIZE,
    LARGE_MSG_SIZE,
    SUFFIX_TRUNCATE,
)


class TestIsNeedTruncate:
    """Tests for is_need_truncate function."""

    @pytest.fixture(autouse=True)
    def mock_agent_name(self):
        """Mock get_agent_name to return None (regular agent) by default."""
        with patch(
            "topsailai.context.ctx_safe.get_agent_name",
            return_value=None
        ):
            yield

    def test_is_need_truncate_below_max(self):
        """Test that msg_len < MAX_MSG_SIZE returns False for regular agent."""
        assert is_need_truncate(MAX_MSG_SIZE - 1) is False

    def test_is_need_truncate_at_max(self):
        """Test that msg_len == MAX_MSG_SIZE returns True for regular agent.

        Regular agents use >= comparison, so at MAX_MSG_SIZE truncation is needed.
        """
        assert is_need_truncate(MAX_MSG_SIZE) is True

    def test_is_need_truncate_above_max(self):
        """Test that msg_len > MAX_MSG_SIZE returns True for regular agent."""
        assert is_need_truncate(MAX_MSG_SIZE + 1) is True

    def test_is_need_truncate_agent_writer_below_large(self):
        """Test that msg_len < LARGE_MSG_SIZE returns False for AgentWriter.

        AgentWriter uses > comparison with LARGE_MSG_SIZE threshold.
        """
        with patch(
            "topsailai.context.ctx_safe.get_agent_name",
            return_value="AgentWriter"
        ):
            assert is_need_truncate(LARGE_MSG_SIZE - 1) is False

    def test_is_need_truncate_agent_writer_at_large(self):
        """Test that msg_len == LARGE_MSG_SIZE returns False for AgentWriter.

        AgentWriter uses > comparison, so at LARGE_MSG_SIZE no truncation needed.
        """
        with patch(
            "topsailai.context.ctx_safe.get_agent_name",
            return_value="AgentWriter"
        ):
            assert is_need_truncate(LARGE_MSG_SIZE) is False

    def test_is_need_truncate_agent_writer_above_large(self):
        """Test that msg_len > LARGE_MSG_SIZE returns True for AgentWriter."""
        with patch(
            "topsailai.context.ctx_safe.get_agent_name",
            return_value="AgentWriter"
        ):
            assert is_need_truncate(LARGE_MSG_SIZE + 1) is True


class TestTruncateMessage:
    """Tests for truncate_message function."""

    @pytest.fixture(autouse=True)
    def mock_print_error(self):
        """Mock print_tool.print_error to avoid noisy output during tests."""
        with patch("topsailai.context.ctx_safe.print_tool.print_error"):
            yield

    @pytest.fixture(autouse=True)
    def mock_agent_name(self):
        """Mock get_agent_name to return None (regular agent) by default."""
        with patch(
            "topsailai.context.ctx_safe.get_agent_name",
            return_value=None
        ):
            yield

    def test_truncate_message_string_no_truncate(self):
        """Test that short string is returned unchanged."""
        short_msg = "Hello, this is a short message."
        result = truncate_message(short_msg)
        assert result == short_msg

    def test_truncate_message_string_with_truncate(self):
        """Test that long string is truncated to MAX_MSG_SIZE + suffix."""
        long_msg = "x" * (MAX_MSG_SIZE + 100)
        result = truncate_message(long_msg)
        expected = "x" * MAX_MSG_SIZE + SUFFIX_TRUNCATE
        assert result == expected
        assert len(result) == MAX_MSG_SIZE + len(SUFFIX_TRUNCATE)

    def test_truncate_message_bytes_no_truncate(self):
        """Test that short bytes is returned unchanged."""
        short_msg = b"Hello, this is a short message."
        result = truncate_message(short_msg)
        assert result == short_msg

    def test_truncate_message_bytes_with_truncate(self):
        """Test that long bytes is truncated with bytes suffix."""
        long_msg = b"x" * (MAX_MSG_SIZE + 100)
        result = truncate_message(long_msg)
        expected = b"x" * MAX_MSG_SIZE + b" ... (force to truncate)"
        assert result == expected
        assert len(result) == MAX_MSG_SIZE + len(b" ... (force to truncate)")

    def test_truncate_message_exact_max_size(self):
        """Test message at exactly MAX_MSG_SIZE is truncated.

        Regular agents use >= comparison, so at MAX_MSG_SIZE truncation is needed.
        """
        exact_msg = "x" * MAX_MSG_SIZE
        result = truncate_message(exact_msg)
        expected = exact_msg + SUFFIX_TRUNCATE
        assert result == expected

    def test_truncate_message_empty_string(self):
        """Test that empty string is returned unchanged."""
        result = truncate_message("")
        assert result == ""

    def test_truncate_message_empty_bytes(self):
        """Test that empty bytes is returned unchanged."""
        result = truncate_message(b"")
        assert result == b""


class TestTruncateText:
    """Tests for truncate_text function."""

    def test_truncate_text_basic(self):
        """Test basic text truncation to given size + suffix."""
        text = "This is a long text that needs truncation."
        size = 10
        result = truncate_text(text, size)
        expected = text[:size] + SUFFIX_TRUNCATE
        assert result == expected

    def test_truncate_text_exact_size(self):
        """Test text at exactly the size limit is not truncated."""
        text = "Hello"
        size = 5
        result = truncate_text(text, size)
        expected = text + SUFFIX_TRUNCATE
        assert result == expected

    def test_truncate_text_below_size(self):
        """Test text below size limit is returned with suffix."""
        text = "Hi"
        size = 10
        result = truncate_text(text, size)
        expected = text + SUFFIX_TRUNCATE
        assert result == expected

    def test_truncate_text_empty_string(self):
        """Test that empty string with suffix is returned."""
        result = truncate_text("", 10)
        expected = SUFFIX_TRUNCATE
        assert result == expected

    def test_truncate_text_unicode(self):
        """Test truncation with unicode characters."""
        text = "你好世界这是一个测试"
        size = 5
        result = truncate_text(text, size)
        expected = text[:size] + SUFFIX_TRUNCATE
        assert result == expected
