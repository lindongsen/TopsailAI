"""
Test module for ai_base/llm_control/llm_mistakes/base/init.py

Author: AI
Purpose: Unit tests for LLM mistake checking and fixing functions
"""

import pytest
from unittest.mock import MagicMock, patch, call


class TestCheckOrFixMistakes:
    """Test suite for check_or_fix_mistakes function."""

    def test_check_or_fix_mistakes_with_none_response(self):
        """Verify returns None for None response."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        result = check_or_fix_mistakes(None)
        assert result is None

    def test_check_or_fix_mistakes_with_empty_list(self):
        """Verify returns None for empty list when no mistakes registered."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        result = check_or_fix_mistakes([])
        assert result is None

    def test_check_or_fix_mistakes_with_string(self):
        """Verify returns None for string when no fixes applied."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        result = check_or_fix_mistakes("test string")
        assert result is None

    def test_check_or_fix_mistakes_with_dict(self):
        """Verify returns None for dict when no fixes applied."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        test_dict = {"key": "value"}
        result = check_or_fix_mistakes(test_dict)
        assert result is None

    def test_check_or_fix_mistakes_calls_mistake_function(self):
        """Verify mistake function is called with response."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        mock_func = MagicMock(return_value="fixed_response")
        test_response = "original_response"

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test_mistake": mock_func}):
            result = check_or_fix_mistakes(test_response)

        mock_func.assert_called_once()
        call_kwargs = mock_func.call_args[1]
        assert 'rsp_obj' in call_kwargs

    def test_check_or_fix_mistakes_breaks_on_first_fix(self):
        """Verify iteration breaks after first successful fix."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        mock_func1 = MagicMock(return_value="fixed_response")
        mock_func2 = MagicMock()
        test_response = "original_response"

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {
            "mistake1": mock_func1,
            "mistake2": mock_func2
        }):
            result = check_or_fix_mistakes(test_response)

        # Second function should not be called
        mock_func2.assert_not_called()

    def test_check_or_fix_mistakes_continues_on_none(self):
        """Verify continues to next mistake when function returns None."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        mock_func1 = MagicMock(return_value=None)
        mock_func2 = MagicMock(return_value="fixed")
        test_response = "original_response"

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {
            "mistake1": mock_func1,
            "mistake2": mock_func2
        }):
            result = check_or_fix_mistakes(test_response)

        # Both functions should be called
        mock_func1.assert_called_once()
        mock_func2.assert_called_once()

    def test_check_or_fix_mistakes_continues_on_same_response(self):
        """Verify continues to next mistake when function returns same response."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        test_response = "original_response"
        mock_func1 = MagicMock(return_value=test_response)
        mock_func2 = MagicMock(return_value="fixed")
        mock_func3 = MagicMock()

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {
            "mistake1": mock_func1,
            "mistake2": mock_func2,
            "mistake3": mock_func3
        }):
            result = check_or_fix_mistakes(test_response)

        # Third function should not be called (second fixed it)
        mock_func3.assert_not_called()

    def test_check_or_fix_mistakes_passes_rsp_obj(self):
        """Verify rsp_obj is passed to mistake functions."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        mock_func = MagicMock(return_value="fixed")
        test_response = "original"
        test_rsp_obj = MagicMock()

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test": mock_func}):
            check_or_fix_mistakes(test_response, rsp_obj=test_rsp_obj)

        call_kwargs = mock_func.call_args[1]
        assert call_kwargs['rsp_obj'] is test_rsp_obj

    def test_check_or_fix_mistakes_passes_kwargs(self):
        """Verify additional kwargs are passed to mistake functions."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        mock_func = MagicMock(return_value="fixed")
        test_response = "original"

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test": mock_func}):
            check_or_fix_mistakes(test_response, extra_param="value", number=42)

        call_kwargs = mock_func.call_args[1]
        assert call_kwargs['extra_param'] == "value"
        assert call_kwargs['number'] == 42

    def test_check_or_fix_mistakes_logs_on_fix(self):
        """Verify error is logged when fix is applied."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        mock_func = MagicMock(return_value="fixed_response")
        test_response = "original_response"

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test_mistake": mock_func}):
            with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.print_tool') as mock_print:
                check_or_fix_mistakes(test_response)

        mock_print.print_error.assert_called_once()
        call_args = mock_print.print_error.call_args[0][0]
        assert "test_mistake" in call_args
        assert "original_response" in call_args
        assert "fixed_response" in call_args

    def test_check_or_fix_mistakes_no_log_on_no_fix(self):
        """Verify no log when no fix is applied."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        test_response = "original_response"
        mock_func = MagicMock(return_value=test_response)

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test": mock_func}):
            with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.print_tool') as mock_print:
                result = check_or_fix_mistakes(test_response)

        mock_print.print_error.assert_not_called()

    def test_check_or_fix_mistakes_returns_fixed_response(self):
        """Verify returns the fixed response after applying fix."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        fixed_response = {"step_name": "action", "raw_text": "fixed"}
        mock_func = MagicMock(return_value=fixed_response)
        test_response = "original"

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test": mock_func}):
            result = check_or_fix_mistakes(test_response)

        assert result is fixed_response

    def test_check_or_fix_mistakes_with_empty_mistakes(self):
        """Verify returns original response when no mistakes registered."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        test_response = ["item1", "item2"]

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {}):
            result = check_or_fix_mistakes(test_response)

        assert result == test_response

    def test_check_or_fix_mistakes_with_list_response(self):
        """Verify handles list response correctly."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        test_response = [{"step_name": "thought"}, {"step_name": "action"}]
        mock_func = MagicMock(return_value=test_response)

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test": mock_func}):
            result = check_or_fix_mistakes(test_response)

        assert result == test_response

    def test_check_or_fix_mistakes_with_nested_dict(self):
        """Verify handles nested dict response correctly."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        test_response = {
            "data": {
                "nested": {"value": 123}
            }
        }
        mock_func = MagicMock(return_value=test_response)

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {"test": mock_func}):
            result = check_or_fix_mistakes(test_response)

        assert result == test_response

    def test_check_or_fix_mistakes_multiple_fixes_not_applied(self):
        """Verify only first fix is applied even if multiple could apply."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import check_or_fix_mistakes

        mock_func1 = MagicMock(return_value="fixed1")
        mock_func2 = MagicMock(return_value="fixed2")
        test_response = "original"

        with patch('topsailai.ai_base.llm_control.llm_mistakes.base.init.MISTAKES', {
            "mistake1": mock_func1,
            "mistake2": mock_func2
        }):
            result = check_or_fix_mistakes(test_response)

        assert result == "fixed1"
        mock_func2.assert_not_called()


class TestMISTAKESConstant:
    """Test suite for MISTAKES constant."""

    def test_mistakes_is_dict(self):
        """Verify MISTAKES is a dictionary."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import MISTAKES

        assert isinstance(MISTAKES, dict)

    def test_mistakes_values_are_callable(self):
        """Verify all MISTAKES values are callable functions."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import MISTAKES

        for name, func in MISTAKES.items():
            assert callable(func), f"MISTAKES['{name}'] is not callable"

    def test_mistakes_keys_are_strings(self):
        """Verify all MISTAKES keys are strings."""
        from topsailai.ai_base.llm_control.llm_mistakes.base.init import MISTAKES

        for key in MISTAKES.keys():
            assert isinstance(key, str), f"MISTAKES key '{key}' is not a string"
