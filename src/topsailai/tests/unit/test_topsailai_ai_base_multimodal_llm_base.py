"""
Unit tests for ai_base/multimodal/llm_base.py module.

This module contains unit tests for the MultimodalLLMModel class which extends
LLMModel to support content arrays for multimodal interactions.
"""

import pytest
from unittest.mock import MagicMock, patch

from topsailai.ai_base.multimodal.llm_base import MultimodalLLMModel
from topsailai.ai_base.multimodal.message import MultimodalMessage, TextContent, ImageContent
from topsailai.ai_base.multimodal.prompt_base import MultimodalPromptBase


@pytest.fixture
def model():
    """Create a MultimodalLLMModel with mocked parent initialization."""
    with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
        with patch("topsailai.ai_base.llm_base.logger"):
            model = MultimodalLLMModel()
            model.model_name = "test-model"
            model.temperature = 0.7
            model.max_tokens = 4096
            model.top_p = 1.0
            model.frequency_penalty = 0.0
            model.content_senders = []
            model.models = []
            model.model = MagicMock()
            model.tokenStat = MagicMock()
            model.model_config = {"api_key": "test-key"}
            model.hooks = {}
            return model


class TestBuildParametersForChat:
    """Test cases for MultimodalLLMModel.build_parameters_for_chat method."""

    def test_string_content_processed_by_parent(self, model):
        """Test that string content messages are processed by parent's format_messages."""
        messages = [{"role": "user", "content": "Hello"}]

        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = messages

            params = model.build_parameters_for_chat(messages)

            mock_format.assert_called_once()
            assert params["messages"][0]["content"] == "Hello"

    def test_list_content_preserved(self, model):
        """Test that list content (content arrays) is preserved, not formatted."""
        content_array = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {"url": "http://example.com/image.png"}},
        ]
        messages = [{"role": "user", "content": content_array}]

        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = [{"role": "user", "content": "__MULTIMODAL_CONTENT_PLACEHOLDER_0__"}]

            params = model.build_parameters_for_chat(messages)

            assert params["messages"][0]["content"] == content_array
            assert isinstance(params["messages"][0]["content"], list)

    def test_mixed_content_string_formatted_list_preserved(self, model):
        """Test mixed content: strings are formatted, lists are preserved."""
        content_array = [
            {"type": "text", "text": "Describe this"},
            {"type": "image_url", "image_url": {"url": "http://example.com/image.png"}},
        ]
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": content_array},
        ]

        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "__MULTIMODAL_CONTENT_PLACEHOLDER_1__"},
            ]

            params = model.build_parameters_for_chat(messages)

            assert params["messages"][0]["content"] == "You are helpful."
            assert params["messages"][1]["content"] == content_array

    def test_returns_correct_params_dict(self, model):
        """Test that build_parameters_for_chat returns correct params dict."""
        messages = [{"role": "user", "content": "Hello"}]

        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = messages

            params = model.build_parameters_for_chat(
                messages,
                stream=True,
                tools=[{"type": "function", "function": {"name": "test"}}],
                tool_choice="required",
            )

            assert params["model"] == "test-model"
            assert params["temperature"] == 0.7
            assert params["max_tokens"] == 4096
            assert params["top_p"] == 1.0
            assert params["frequency_penalty"] == 0.0
            assert params["stream"] is True
            assert params["tools"] == [{"type": "function", "function": {"name": "test"}}]
            assert params["tool_choice"] == "required"
            assert params["stream_options"] == {"include_usage": True}

    def test_hook_execution(self, model):
        """Test that hook_execute is called and can modify messages."""
        messages = [{"role": "user", "content": "Hello"}]
        modified_messages = [{"role": "user", "content": "Modified"}]

        with patch("topsailai.ai_base.llm_hooks.executor.hook_execute") as mock_hook:
            with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
                mock_hook.return_value = modified_messages
                mock_format.return_value = modified_messages

                params = model.build_parameters_for_chat(messages)

                mock_hook.assert_called_once_with("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", messages)
                assert params["messages"][0]["content"] == "Modified"

    def test_hook_returns_none_uses_original(self, model):
        """Test that when hook returns None, original messages are used."""
        messages = [{"role": "user", "content": "Hello"}]

        with patch("topsailai.ai_base.llm_hooks.executor.hook_execute") as mock_hook:
            with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
                mock_hook.return_value = None
                mock_format.return_value = messages

                params = model.build_parameters_for_chat(messages)

                assert params["messages"][0]["content"] == "Hello"

    def test_empty_messages(self, model):
        """Test build_parameters_for_chat with empty messages list."""
        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = []

            params = model.build_parameters_for_chat([])

            assert params["messages"] == []

    def test_preserves_tool_call_id(self, model):
        """Test that tool_call_id is preserved in messages."""
        messages = [{"role": "tool", "content": "Result", "tool_call_id": "call_123"}]

        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = messages

            params = model.build_parameters_for_chat(messages)

            assert params["messages"][0]["tool_call_id"] == "call_123"

    def test_multiple_list_contents(self, model):
        """Test multiple messages with list content are all preserved."""
        content_array1 = [{"type": "text", "text": "First"}]
        content_array2 = [{"type": "image_url", "image_url": {"url": "http://example.com/2.png"}}]
        messages = [
            {"role": "user", "content": content_array1},
            {"role": "user", "content": content_array2},
        ]

        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = [
                {"role": "user", "content": "__MULTIMODAL_CONTENT_PLACEHOLDER_0__"},
                {"role": "user", "content": "__MULTIMODAL_CONTENT_PLACEHOLDER_1__"},
            ]

            params = model.build_parameters_for_chat(messages)

            assert params["messages"][0]["content"] == content_array1
            assert params["messages"][1]["content"] == content_array2


class TestChatWithContent:
    """Test cases for MultimodalLLMModel.chat_with_content method."""

    def test_with_multimodal_message_objects(self, model):
        """Test chat_with_content with list of MultimodalMessage objects."""
        msg1 = MultimodalMessage("user", [TextContent("Hello")])
        msg2 = MultimodalMessage("user", [
            TextContent("Describe this"),
            ImageContent("http://example.com/image.png"),
        ])

        with patch.object(model, "chat") as mock_chat:
            mock_chat.return_value = "Response"

            result = model.chat_with_content([msg1, msg2])

            mock_chat.assert_called_once()
            call_messages = mock_chat.call_args[0][0]
            assert len(call_messages) == 2
            assert call_messages[0] == {"role": "user", "content": "Hello"}
            assert call_messages[1]["role"] == "user"
            assert isinstance(call_messages[1]["content"], list)
            assert result == "Response"

    def test_with_dicts_passes_through(self, model):
        """Test chat_with_content with list of pre-converted dicts."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        with patch.object(model, "chat") as mock_chat:
            mock_chat.return_value = "Response"

            result = model.chat_with_content(messages)

            mock_chat.assert_called_once_with(messages, for_raw=True, for_stream=False)
            assert result == "Response"

    def test_with_mixed_types_raises_value_error(self, model):
        """Test chat_with_content with mixed types raises ValueError."""
        msg = MultimodalMessage("user", [TextContent("Hello")])

        with pytest.raises(ValueError, match="must contain MultimodalMessage objects or dicts"):
            model.chat_with_content([msg, "invalid_string"])

    def test_with_empty_list_raises_value_error(self, model):
        """Test chat_with_content with empty list raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            model.chat_with_content([])

    def test_with_invalid_type_raises_value_error(self, model):
        """Test chat_with_content with invalid element type raises ValueError."""
        with pytest.raises(ValueError, match="must contain MultimodalMessage objects or dicts"):
            model.chat_with_content(["string1", "string2"])

    def test_for_raw_false(self, model):
        """Test chat_with_content with for_raw=False."""
        msg = MultimodalMessage("user", [TextContent("Hello")])

        with patch.object(model, "chat") as mock_chat:
            mock_chat.return_value = ["formatted", "response"]

            result = model.chat_with_content([msg], for_raw=False)

            mock_chat.assert_called_once_with(
                [{"role": "user", "content": "Hello"}],
                for_raw=False,
                for_stream=False,
            )
            assert result == ["formatted", "response"]

    def test_for_stream_true(self, model):
        """Test chat_with_content with for_stream=True."""
        msg = MultimodalMessage("user", [TextContent("Hello")])

        with patch.object(model, "chat") as mock_chat:
            mock_chat.return_value = "Streamed response"

            result = model.chat_with_content([msg], for_stream=True)

            mock_chat.assert_called_once_with(
                [{"role": "user", "content": "Hello"}],
                for_raw=True,
                for_stream=True,
            )

    def test_single_message(self, model):
        """Test chat_with_content with a single message."""
        msg = MultimodalMessage("user", [TextContent("Single message")])

        with patch.object(model, "chat") as mock_chat:
            mock_chat.return_value = "Response"

            result = model.chat_with_content([msg])

            assert result == "Response"

    def test_logs_message_count(self, model):
        """Test that chat_with_content logs the message count."""
        msg = MultimodalMessage("user", [TextContent("Hello")])

        with patch.object(model, "chat"):
            with patch("topsailai.ai_base.multimodal.llm_base.logger") as mock_logger:
                model.chat_with_content([msg])

                mock_logger.info.assert_called_once_with(
                    "Sending multimodal chat with %d messages", 1
                )

    def test_with_tool_message(self, model):
        """Test chat_with_content with a tool message including tool_call_id."""
        msg = MultimodalMessage("tool", [TextContent("Result")], tool_call_id="call_123")

        with patch.object(model, "chat") as mock_chat:
            mock_chat.return_value = "Response"

            result = model.chat_with_content([msg])

            call_messages = mock_chat.call_args[0][0]
            assert call_messages[0]["role"] == "tool"
            assert call_messages[0]["content"] == "Result"
            assert call_messages[0]["tool_call_id"] == "call_123"
            assert result == "Response"


class TestChatWithPrompt:
    """Test cases for MultimodalLLMModel.chat_with_prompt method."""

    def test_with_prompt_base(self, model):
        """Test chat_with_prompt with MultimodalPromptBase."""
        prompt = MultimodalPromptBase("You are helpful.")
        prompt.add_user_message("Hello")

        with patch.object(model, "chat_with_content") as mock_chat_with_content:
            mock_chat_with_content.return_value = "Response"

            result = model.chat_with_prompt(prompt)

            mock_chat_with_content.assert_called_once()
            call_messages = mock_chat_with_content.call_args[0][0]
            assert len(call_messages) == 2
            assert call_messages[0] == {"role": "system", "content": "You are helpful."}
            assert call_messages[1] == {"role": "user", "content": "Hello"}
            assert result == "Response"

    def test_with_none_raises_value_error(self, model):
        """Test chat_with_prompt with None raises ValueError."""
        with pytest.raises(ValueError, match="cannot be None"):
            model.chat_with_prompt(None)

    def test_for_raw_and_stream_passed_through(self, model):
        """Test that for_raw and for_stream are passed to chat_with_content."""
        prompt = MultimodalPromptBase("You are helpful.")
        prompt.add_user_message("Hello")

        with patch.object(model, "chat_with_content") as mock_chat_with_content:
            model.chat_with_prompt(prompt, for_raw=False, for_stream=True)

            _, kwargs = mock_chat_with_content.call_args
            assert kwargs["for_raw"] is False
            assert kwargs["for_stream"] is True


class TestEdgeCases:
    """Test edge cases for MultimodalLLMModel."""

    def test_inherits_from_llm_model(self, model):
        """Test that MultimodalLLMModel inherits from LLMModel."""
        from topsailai.ai_base.llm_base import LLMModel
        assert isinstance(model, LLMModel)

    def test_build_parameters_does_not_modify_original_messages(self, model):
        """Test that build_parameters_for_chat does not modify the original messages list."""
        content_array = [{"type": "text", "text": "Hello"}]
        messages = [{"role": "user", "content": content_array}]

        with patch("topsailai.ai_base.llm_control.base_class.format_messages") as mock_format:
            mock_format.return_value = [{"role": "user", "content": "__MULTIMODAL_CONTENT_PLACEHOLDER_0__"}]

            model.build_parameters_for_chat(messages)

            # Original should still be a list
            assert isinstance(messages[0]["content"], list)
            assert messages[0]["content"] == content_array
