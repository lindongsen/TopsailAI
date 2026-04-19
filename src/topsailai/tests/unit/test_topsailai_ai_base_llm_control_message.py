"""
Test module for ai_base/llm_control/message.py

Author: AI
Purpose: Unit tests for message handling functions
"""

import pytest
from unittest.mock import MagicMock, patch


class TestToList:
    """Test suite for _to_list function."""

    def test_to_list_with_list(self):
        """Verify _to_list returns list unchanged."""
        from topsailai.ai_base.llm_control.message import _to_list

        input_list = [1, 2, 3]
        result = _to_list(input_list)
        assert result == [1, 2, 3]
        assert result is input_list

    def test_to_list_with_none(self):
        """Verify _to_list returns None for None input."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list(None)
        assert result is None

    def test_to_list_with_string(self):
        """Verify _to_list wraps string in list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list("hello")
        assert result == ["hello"]

    def test_to_list_with_tuple(self):
        """Verify _to_list converts tuple to list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list((1, 2, 3))
        assert result == [1, 2, 3]

    def test_to_list_with_set(self):
        """Verify _to_list converts set to list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list({1, 2, 3})
        assert result == [1, 2, 3]

    def test_to_list_with_dict(self):
        """Verify _to_list wraps dict in list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list({"key": "value"})
        assert result == [{"key": "value"}]

    def test_to_list_with_int(self):
        """Verify _to_list wraps int in list."""
        from topsailai.ai_base.llm_control.message import _to_list

        result = _to_list(42)
        assert result == [42]


class TestGetResponseMessage:
    """Test suite for get_response_message function."""

    def test_get_response_message_with_chat_completion_message(self):
        """Verify returns ChatCompletionMessage directly."""
        from openai.types.chat import ChatCompletionMessage
        from topsailai.ai_base.llm_control.message import get_response_message

        mock_msg = MagicMock(spec=ChatCompletionMessage)
        result = get_response_message(mock_msg)
        assert result is mock_msg

    def test_get_response_message_with_response_object(self):
        """Verify extracts message from response.choices[0].message."""
        from topsailai.ai_base.llm_control.message import get_response_message

        mock_msg = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_msg

        result = get_response_message(mock_response)
        assert result is mock_msg

    def test_get_response_message_with_empty_choices(self):
        """Verify handles empty choices list."""
        from topsailai.ai_base.llm_control.message import get_response_message

        mock_response = MagicMock()
        mock_response.choices = []

        # Should raise IndexError when accessing choices[0]
        with pytest.raises(IndexError):
            get_response_message(mock_response)


class TestGetToolCallsOfRsp:
    """Test suite for get_tool_calls_of_rsp function."""

    def test_get_tool_calls_with_none_response(self):
        """Verify returns None for None response."""
        from topsailai.ai_base.llm_control.message import get_tool_calls_of_rsp

        result = get_tool_calls_of_rsp(None)
        assert result is None

    def test_get_tool_calls_with_empty_response(self):
        """Verify returns None for empty response."""
        from topsailai.ai_base.llm_control.message import get_tool_calls_of_rsp

        result = get_tool_calls_of_rsp("")
        assert result is None

    def test_get_tool_calls_with_valid_response(self):
        """Verify extracts tool_calls from response."""
        from topsailai.ai_base.llm_control.message import get_tool_calls_of_rsp

        mock_tool_calls = [MagicMock(), MagicMock()]
        mock_msg = MagicMock()
        mock_msg.tool_calls = mock_tool_calls

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_msg

        result = get_tool_calls_of_rsp(mock_response)
        assert result is mock_tool_calls


class TestGetCountOfAction:
    """Test suite for get_count_of_action function."""

    def test_get_count_of_action_with_none(self):
        """Verify returns 0 for None."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        result = get_count_of_action(None)
        assert result == 0

    def test_get_count_of_action_with_empty_list(self):
        """Verify returns 0 for empty list."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        result = get_count_of_action([])
        assert result == 0

    def test_get_count_of_action_with_messages(self):
        """Verify counts messages with step_name action."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": '"step_name": "thought"'},
            {"role": "assistant", "content": '"step_name": "action"'},
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages)
        assert result == 2

    def test_get_count_of_action_ignores_non_dict(self):
        """Verify ignores non-dict messages."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            "not a dict",
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages)
        assert result == 1

    def test_get_count_of_action_ignores_missing_content(self):
        """Verify ignores messages without content."""
        from topsailai.ai_base.llm_control.message import get_count_of_action

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user"},  # missing content
            {"role": "assistant", "content": '"step_name": "action"'},
        ]

        result = get_count_of_action(messages)
        assert result == 1


class TestUpdateResponseItem:
    """Test suite for update_response_item function."""

    def test_update_response_item_with_action_and_raw_text(self):
        """Verify updates item with hook result."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "action",
            "raw_text": "test action"
        }

        with patch('topsailai.ai_base.llm_control.message.hook_execute') as mock_hook:
            mock_hook.return_value = [{"new_key": "new_value"}]
            result = update_response_item(item)

            mock_hook.assert_called_once_with("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "test action")
            assert result.get("new_key") == "new_value"

    def test_update_response_item_without_action_step(self):
        """Verify returns item unchanged if not action step."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "thought",
            "raw_text": "test thought"
        }

        result = update_response_item(item)
        assert result is item
        assert "step_name" in result

    def test_update_response_item_without_raw_text(self):
        """Verify returns item unchanged if no raw_text."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "action"
        }

        result = update_response_item(item)
        assert result is item

    def test_update_response_item_with_invalid_hook_result(self):
        """Verify handles invalid hook result gracefully."""
        from topsailai.ai_base.llm_control.message import update_response_item

        item = {
            "step_name": "action",
            "raw_text": "test action"
        }

        with patch('topsailai.ai_base.llm_control.message.hook_execute') as mock_hook:
            mock_hook.return_value = "not a list"
            result = update_response_item(item)
            assert result is item


class TestAssertModelServiceError:
    """Test suite for assert_model_service_error function."""

    def test_assert_model_service_error_with_none(self):
        """Verify does not raise for None."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        # Should not raise
        assert_model_service_error(None)

    def test_assert_model_service_error_with_empty_list(self):
        """Verify does not raise for empty list."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        # Should not raise
        assert_model_service_error([])

    def test_assert_model_service_error_with_multiple_items(self):
        """Verify does not raise for list with multiple items."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        # Should not raise
        assert_model_service_error([{"step_name": "action"}, {"step_name": "thought"}])

    def test_assert_model_service_error_raises_for_error_response(self):
        """Verify raises ModelServiceError for error response."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        error_response = [
            {"status": 500, "message": "Internal Server Error"}
        ]

        with pytest.raises(ModelServiceError):
            assert_model_service_error(error_response)

    def test_assert_model_service_error_raises_for_status_and_message(self):
        """Verify raises for response with only status and message."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        error_response = [
            {"status": 429, "message": "Rate limit exceeded"}
        ]

        with pytest.raises(ModelServiceError):
            assert_model_service_error(error_response)

    def test_assert_model_service_error_does_not_raise_for_valid(self):
        """Verify does not raise for valid action response."""
        from topsailai.ai_base.llm_control.message import assert_model_service_error

        valid_response = [
            {"step_name": "action", "raw_text": "do something"}
        ]

        # Should not raise
        assert_model_service_error(valid_response)


class TestFixLlmMistakes:
    """Test suite for fix_llm_mistakes function."""

    def test_fix_llm_mistakes_with_none(self):
        """Verify returns None for None input."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        result = fix_llm_mistakes(None)
        assert result is None

    def test_fix_llm_mistakes_with_empty_list(self):
        """Verify returns empty list unchanged."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        result = fix_llm_mistakes([])
        assert result == []

    def test_fix_llm_mistakes_adds_step_name(self):
        """Verify adds step_name for tool_call and tool_args."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        response = [
            {"tool_call": "test_tool", "tool_args": {}}
        ]

        result = fix_llm_mistakes(response)
        assert result[0].get("step_name") == "action"

    def test_fix_llm_mistakes_preserves_existing_step_name(self):
        """Verify preserves existing step_name."""
        from topsailai.ai_base.llm_control.message import fix_llm_mistakes

        response = [
            {"step_name": "thought", "raw_text": "thinking"}
        ]

        result = fix_llm_mistakes(response)
        assert result[0].get("step_name") == "thought"
