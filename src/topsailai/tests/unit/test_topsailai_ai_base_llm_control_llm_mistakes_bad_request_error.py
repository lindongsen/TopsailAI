"""
Unit tests for ai_base/llm_control/llm_mistakes/bad_request_error.py

Author: AI
Purpose: Test bad_request_error module for LLM mistake detection
"""

import pytest
from unittest.mock import MagicMock


class TestCheckMistake1:
    """Test cases for check_mistake1 function."""

    def test_check_mistake1_with_valid_bad_request_error(self):
        """Test that check_mistake1 raises ModelServiceError for BadRequestError at top level."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1
        from ai_base.llm_control.exception import ModelServiceError

        # Note: The function checks d.get("type"), so type must be at top level of dict
        message = [
            {
                "type": "BadRequestError",
                "code": 400,
                "error": {
                    "message": "Unterminated string starting at: line 1 column 83 (char 82)"
                }
            }
        ]

        with pytest.raises(ModelServiceError) as exc_info:
            check_mistake1(message)
        
        # ModelServiceError stores data in args[0]
        assert exc_info.value.args[0]["type"] == "BadRequestError"
        assert exc_info.value.args[0]["code"] == 400

    def test_check_mistake1_with_non_list_message(self):
        """Test check_mistake1 returns None for non-list message."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        result = check_mistake1("not a list")
        assert result is None

    def test_check_mistake1_with_empty_list(self):
        """Test check_mistake1 returns None for empty list."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        result = check_mistake1([])
        assert result is None

    def test_check_mistake1_with_list_length_not_one(self):
        """Test check_mistake1 returns None for list with more than one element."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = [{"error": {}}, {"error": {}}]
        result = check_mistake1(message)
        assert result is None

    def test_check_mistake1_with_non_dict_first_element(self):
        """Test check_mistake1 returns None when first element is not dict."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = ["not a dict"]
        result = check_mistake1(message)
        assert result is None

    def test_check_mistake1_without_error_key(self):
        """Test check_mistake1 returns None when 'error' key is missing."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = [{"not_error": {}}]
        result = check_mistake1(message)
        assert result is None

    def test_check_mistake1_with_non_dict_error(self):
        """Test check_mistake1 returns None when error is not a dict."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = [{"error": "not a dict"}]
        result = check_mistake1(message)
        assert result is None

    def test_check_mistake1_with_different_type(self):
        """Test check_mistake1 returns None for non-BadRequestError type."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = [
            {
                "type": "OtherError",
                "code": 500,
                "error": {}
            }
        ]
        result = check_mistake1(message)
        assert result is None

    def test_check_mistake1_with_none_type(self):
        """Test check_mistake1 returns None when type is None."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = [
            {
                "type": None,
                "code": 400,
                "error": {}
            }
        ]
        result = check_mistake1(message)
        assert result is None

    def test_check_mistake1_with_missing_type(self):
        """Test check_mistake1 returns None when type key is missing."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = [
            {
                "code": 400,
                "error": {}
            }
        ]
        result = check_mistake1(message)
        assert result is None


class TestMistakesDict:
    """Test cases for MISTAKES dictionary."""

    def test_mistakes_dict_exists(self):
        """Test that MISTAKES dictionary exists."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import MISTAKES

        assert isinstance(MISTAKES, dict)

    def test_mistakes_dict_contains_check_mistake1(self):
        """Test that MISTAKES contains check_mistake1."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import MISTAKES

        assert "check_mistake1" in MISTAKES

    def test_mistakes_dict_check_mistake1_is_callable(self):
        """Test that MISTAKES['check_mistake1'] is callable."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import MISTAKES

        assert callable(MISTAKES["check_mistake1"])

    def test_mistakes_dict_check_mistake1_reference(self):
        """Test that MISTAKES['check_mistake1'] references the correct function."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import MISTAKES, check_mistake1

        assert MISTAKES["check_mistake1"] is check_mistake1


class TestEdgeCases:
    """Test edge cases for check_mistake1 function."""

    def test_check_mistake1_with_none_message(self):
        """Test check_mistake1 returns None for None message."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        result = check_mistake1(None)
        assert result is None

    def test_check_mistake1_with_dict_message(self):
        """Test check_mistake1 returns None for dict message."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        result = check_mistake1({"error": {}})
        assert result is None

    def test_check_mistake1_with_integer_message(self):
        """Test check_mistake1 returns None for integer message."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        result = check_mistake1(123)
        assert result is None

    def test_check_mistake1_with_empty_dict_in_list(self):
        """Test check_mistake1 returns None for list with empty dict."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        message = [{}]
        result = check_mistake1(message)
        assert result is None

    def test_check_mistake1_with_kwargs_passed(self):
        """Test check_mistake1 handles kwargs correctly."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1
        from ai_base.llm_control.exception import ModelServiceError

        message = [{"type": "BadRequestError", "error": {}}]
        # Function raises ModelServiceError when type is BadRequestError, even with kwargs
        with pytest.raises(ModelServiceError):
            check_mistake1(message, extra_param="test")

    def test_check_mistake1_with_error_nested_type(self):
        """Test check_mistake1 behavior when type is nested inside error dict (not at top level)."""
        from ai_base.llm_control.llm_mistakes.bad_request_error import check_mistake1

        # This tests the actual behavior: type must be at d.get("type"), not d["error"].get("type")
        message = [
            {
                "error": {
                    "type": "BadRequestError",
                    "code": 400
                }
            }
        ]
        # Function checks d.get("type"), not d["error"].get("type"), so this returns None
        result = check_mistake1(message)
        assert result is None
