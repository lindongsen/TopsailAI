"""
Unit tests for ai_base/llm_control/message.py module.

This module tests the core LLM message handling functions including:
- _to_list: Object to list conversion
- fix_llm_mistakes: LLM mistake correction logic
- assert_model_service_error: Model service error detection
- get_count_of_action: Action counting in messages

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from topsailai.ai_base.llm_control.message import (
    _to_list,
    fix_llm_mistakes,
    assert_model_service_error,
    get_count_of_action,
    ModelServiceError,
)


class TestToList(unittest.TestCase):
    """Tests for _to_list function."""

    def test_to_list_with_list(self):
        """Test that a list is returned unchanged."""
        input_list = [1, 2, 3]
        result = _to_list(input_list)
        self.assertEqual(result, [1, 2, 3])

    def test_to_list_with_none(self):
        """Test that None returns None."""
        result = _to_list(None)
        self.assertIsNone(result)

    def test_to_list_with_set(self):
        """Test that a set is converted to a list."""
        input_set = {1, 2, 3}
        result = _to_list(input_set)
        self.assertIsInstance(result, list)
        self.assertEqual(sorted(result), [1, 2, 3])

    def test_to_list_with_tuple(self):
        """Test that a tuple is converted to a list."""
        input_tuple = (1, 2, 3)
        result = _to_list(input_tuple)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [1, 2, 3])

    def test_to_list_with_scalar(self):
        """Test that a scalar value is wrapped in a list."""
        result = _to_list("hello")
        self.assertEqual(result, ["hello"])


class TestFixLlmMistakes(unittest.TestCase):
    """Tests for fix_llm_mistakes function."""

    @patch('topsailai.ai_base.llm_control.message.print_error')
    def test_fix_llm_mistakes_empty(self, mock_print_error):
        """Test that empty response returns empty list."""
        result = fix_llm_mistakes([])
        self.assertEqual(result, [])

    @patch('topsailai.ai_base.llm_control.message.print_error')
    def test_fix_llm_mistakes_missing_step_name_with_tool_call_and_args(self, mock_print_error):
        """Test that step_name is added when tool_call and tool_args present."""
        response = [{"tool_call": "test", "tool_args": {}}]
        result = fix_llm_mistakes(response)
        self.assertEqual(result[0].get("step_name"), "action")
        mock_print_error.assert_called_once()

    @patch('topsailai.ai_base.llm_control.message.print_error')
    def test_fix_llm_mistakes_missing_step_name_only_tool_call(self, mock_print_error):
        """Test that step_name is added when only tool_call present."""
        response = [{"tool_call": "test"}]
        result = fix_llm_mistakes(response)
        self.assertEqual(result[0].get("step_name"), "action")
        mock_print_error.assert_called_once()

    @patch('topsailai.ai_base.llm_control.message.print_error')
    def test_fix_llm_mistakes_normal_response(self, mock_print_error):
        """Test that normal response with step_name is unchanged."""
        response = [{"step_name": "thought", "content": "normal response"}]
        result = fix_llm_mistakes(response)
        self.assertEqual(result[0].get("step_name"), "thought")
        self.assertNotIn("action", result[0])

    @patch('topsailai.ai_base.llm_control.message.print_error')
    @patch('topsailai.ai_base.llm_control.message.get_response_message')
    def test_fix_llm_mistakes_missing_action_with_tool_calls(
        self, mock_get_response, mock_print_error
    ):
        """Test that action dict is appended when step_name != action but tool_calls exist."""
        mock_msg = MagicMock()
        mock_msg.tool_calls = [MagicMock()]
        mock_get_response.return_value = mock_msg

        response = [{"step_name": "thought", "content": "test"}]
        result = fix_llm_mistakes(response, rsp_obj=MagicMock())

        self.assertEqual(len(result), 2)
        self.assertEqual(result[1].get("step_name"), "action")
        mock_print_error.assert_called()

    @patch('topsailai.ai_base.llm_control.message.print_error')
    def test_fix_llm_mistakes_rsp_obj_none(self, mock_print_error):
        """Test that no action is appended when rsp_obj is None."""
        response = [{"step_name": "thought", "content": "test"}]
        result = fix_llm_mistakes(response, rsp_obj=None)
        self.assertEqual(len(result), 1)
        self.assertNotIn("action", result)


class TestAssertModelServiceError(unittest.TestCase):
    """Tests for assert_model_service_error function."""

    def test_assert_model_service_error_empty(self):
        """Test that empty list does not raise."""
        assert_model_service_error([])

    def test_assert_model_service_error_multi_items(self):
        """Test that list with multiple items does not raise."""
        response = [
            {"step_name": "thought", "content": "first"},
            {"step_name": "action", "content": "second"}
        ]
        assert_model_service_error(response)

    def test_assert_model_service_error_with_status_message(self):
        """Test that error dict with status and message raises ModelServiceError."""
        response = [{"status": 500, "message": "Internal Server Error"}]
        with self.assertRaises(ModelServiceError) as context:
            assert_model_service_error(response)
        self.assertIn("some errors have occurred", str(context.exception))

    def test_assert_model_service_error_with_step_name(self):
        """Test that dict with step_name does not raise."""
        response = [{"step_name": "thought", "content": "test", "status": 200}]
        assert_model_service_error(response)


class TestGetCountOfAction(unittest.TestCase):
    """Tests for get_count_of_action function."""

    def test_get_count_of_action_empty(self):
        """Test that empty list returns 0."""
        result = get_count_of_action([])
        self.assertEqual(result, 0)

    def test_get_count_of_action_no_action(self):
        """Test that messages without step_name action return 0."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"content": '{"step_name": "thought", "content": "thinking"}'}
        ]
        result = get_count_of_action(messages)
        self.assertEqual(result, 0)

    def test_get_count_of_action_with_actions(self):
        """Test that messages with step_name action are counted."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"content": '{"step_name": "action", "content": "doing something"}'},
            {"content": '{"step_name": "thought", "content": "thinking"}'},
            {"content": '{"step_name": "action", "content": "doing more"}'}
        ]
        result = get_count_of_action(messages)
        self.assertEqual(result, 2)

    def test_get_count_of_action_skips_first_two(self):
        """Test that actions in first two messages are ignored."""
        messages = [
            {"content": '{"step_name": "action", "content": "first action"}'},
            {"content": '{"step_name": "action", "content": "second action"}'},
            {"content": '{"step_name": "action", "content": "third action"}'}
        ]
        result = get_count_of_action(messages)
        self.assertEqual(result, 1)

    def test_get_count_of_action_non_dict_messages(self):
        """Test that non-dict items in messages are skipped."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            "not a dict",
            123,
            None,
            {"content": '{"step_name": "action", "content": "valid action"}'}
        ]
        result = get_count_of_action(messages)
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
