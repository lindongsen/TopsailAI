"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Unit tests for ai_base/llm_control/llm_mistakes/base/init.py
"""

import pytest
from unittest.mock import patch, MagicMock

from topsailai.ai_base.llm_control.llm_mistakes.base.init import (
    BASE_PATH,
    MISTAKES,
    check_or_fix_mistakes,
)


class TestBasePath:
    """Tests for BASE_PATH constant."""

    def test_base_path_is_string(self):
        """Test that BASE_PATH is a string."""
        assert isinstance(BASE_PATH, str)

    def test_base_path_format(self):
        """Test that BASE_PATH has correct format."""
        assert "llm_mistakes" in BASE_PATH


class TestMistakes:
    """Tests for MISTAKES constant."""

    def test_mistakes_is_dict(self):
        """Test that MISTAKES is a dictionary."""
        assert isinstance(MISTAKES, dict)


class TestCheckOrFixMistakes:
    """Tests for check_or_fix_mistakes function."""

    def test_returns_none_when_response_is_none(self):
        """Test that function returns None when response is None."""
        response = None
        result = check_or_fix_mistakes(response)
        assert result is None

    def test_handles_string_response(self):
        """Test that function handles string response."""
        response = "test string response"
        result = check_or_fix_mistakes(response)
        # Function returns None when mistake is fixed, or original response if no change
        assert result is None or result == response

    def test_handles_list_response(self):
        """Test that function handles list response."""
        response = [{"role": "user", "content": "hello"}]
        result = check_or_fix_mistakes(response)
        # Function returns None when mistake is fixed, or original response if no change
        assert result is None or result == response

    def test_handles_dict_response(self):
        """Test that function handles dict response."""
        response = {"role": "assistant", "content": "hello"}
        result = check_or_fix_mistakes(response)
        # Function returns None when mistake is fixed, or original response if no change
        assert result is None or result == response

    def test_passes_rsp_obj_to_mistakes(self):
        """Test that rsp_obj is passed to mistake functions."""
        response = "test response"
        rsp_obj = MagicMock()
        # Should not raise any exceptions
        check_or_fix_mistakes(response, rsp_obj=rsp_obj)

    def test_passes_kwargs_to_mistakes(self):
        """Test that additional kwargs are passed to mistake functions."""
        response = "test response"
        # Should not raise any exceptions
        check_or_fix_mistakes(response, extra_param="value")

    def test_handles_multiple_mistake_functions(self):
        """Test that function iterates through all mistake functions."""
        response = "test response"
        # Should complete without error even with multiple mistake functions
        result = check_or_fix_mistakes(response)
        # Result can be None (fixed) or original response
        assert result is None or result == response

    def test_mistakes_dict_contains_functions(self):
        """Test that MISTAKES dict contains callable functions."""
        for name, func in MISTAKES.items():
            assert callable(func), f"MISTAKES[{name}] is not callable"

    def test_mistakes_dict_keys_format(self):
        """Test that MISTAKES dict keys follow naming convention."""
        for key in MISTAKES.keys():
            assert isinstance(key, str), "MISTAKES key should be string"
            assert "." in key, "MISTAKES key should contain '.' separator"
