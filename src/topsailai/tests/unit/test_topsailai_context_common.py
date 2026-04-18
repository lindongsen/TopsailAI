#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for topsailai.context.common module.

Tests the get_session_id function which generates or retrieves
session identifiers from environment variables or time-based generation.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from topsailai.context.common import get_session_id


class TestGetSessionId:
    """Tests for get_session_id function."""

    def test_get_session_id_from_env(self, monkeypatch):
        """Test that SESSION_ID env var is used when set."""
        monkeypatch.setenv("SESSION_ID", "custom_session_123")
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = "custom_session_123"
            result = get_session_id()
            assert result == "custom_session_123"
            mock_env.get_session_id.assert_called_once()

    def test_get_session_id_from_time_tool(self, monkeypatch):
        """Test fallback to time-based generation when env var not set."""
        monkeypatch.delenv("SESSION_ID", raising=False)
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = None
            with patch('topsailai.context.common.time_tool') as mock_time:
                mock_time.get_current_date.return_value = "2026-04-18T17:32:58"
                result = get_session_id()
                assert result == "20260418T173258"
                mock_time.get_current_date.assert_called_once_with(with_t=True)

    def test_get_session_id_env_priority(self, monkeypatch):
        """Test that env var takes priority over time-based generation."""
        monkeypatch.setenv("SESSION_ID", "priority_session")
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = "priority_session"
            with patch('topsailai.context.common.time_tool') as mock_time:
                result = get_session_id()
                assert result == "priority_session"
                mock_time.get_current_date.assert_not_called()

    def test_get_session_id_empty_env(self, monkeypatch):
        """Test that empty string env var falls back to time-based generation."""
        monkeypatch.setenv("SESSION_ID", "")
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = ""
            with patch('topsailai.context.common.time_tool') as mock_time:
                mock_time.get_current_date.return_value = "2026-01-01T00:00:00"
                result = get_session_id()
                assert result == "20260101T000000"

    def test_get_session_id_format(self, monkeypatch):
        """Test that returned format has no '-' or ':' characters."""
        monkeypatch.delenv("SESSION_ID", raising=False)
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = None
            with patch('topsailai.context.common.time_tool') as mock_time:
                mock_time.get_current_date.return_value = "2026-12-31T23:59:59"
                result = get_session_id()
                assert '-' not in result
                assert ':' not in result
                assert result == "20261231T235959"

    def test_get_session_id_returns_string(self, monkeypatch):
        """Test that return type is always str."""
        monkeypatch.delenv("SESSION_ID", raising=False)
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = None
            with patch('topsailai.context.common.time_tool') as mock_time:
                mock_time.get_current_date.return_value = "2026-04-18T17:32:58"
                result = get_session_id()
                assert isinstance(result, str)
                assert result == "20260418T173258"


class TestGetSessionIdEdgeCases:
    """Edge case tests for get_session_id function."""

    def test_get_session_id_none_from_env(self, monkeypatch):
        """Test handling when env_tool returns None."""
        monkeypatch.delenv("SESSION_ID", raising=False)
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = None
            with patch('topsailai.context.common.time_tool') as mock_time:
                mock_time.get_current_date.return_value = "2026-04-18T17:32:58"
                result = get_session_id()
                assert result == "20260418T173258"

    def test_get_session_id_with_special_chars_in_env(self, monkeypatch):
        """Test that env var with special chars is returned as-is."""
        monkeypatch.setenv("SESSION_ID", "session-with-special.chars")
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = "session-with-special.chars"
            result = get_session_id()
            assert result == "session-with-special.chars"

    def test_get_session_id_time_format_variations(self, monkeypatch):
        """Test various time format outputs are handled correctly."""
        monkeypatch.delenv("SESSION_ID", raising=False)
        test_cases = [
            ("2026-01-01T00:00:00", "20260101T000000"),
            ("2026-12-31T23:59:59", "20261231T235959"),
            ("2026-06-15T12:30:45", "20260615T123045"),
        ]
        with patch('topsailai.context.common.env_tool') as mock_env:
            mock_env.get_session_id.return_value = None
            for time_input, expected in test_cases:
                with patch('topsailai.context.common.time_tool') as mock_time:
                    mock_time.get_current_date.return_value = time_input
                    result = get_session_id()
                    assert result == expected
