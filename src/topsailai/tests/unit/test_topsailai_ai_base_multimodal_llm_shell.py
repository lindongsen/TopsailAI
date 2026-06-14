"""
Unit tests for ai_base/multimodal/llm_shell.py module.

Tests cover MultimodalLLMChat class and get_multimodal_llm_chat factory function.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from topsailai.ai_base.multimodal.llm_shell import (
    MultimodalLLMChat,
    get_multimodal_llm_chat,
)
from topsailai.ai_base.multimodal.message import (
    TextContent,
    ImageContent,
    MultimodalMessage,
)
from topsailai.ai_base.multimodal.prompt_base import MultimodalPromptBase
from topsailai.ai_base.multimodal.llm_base import MultimodalLLMModel
from topsailai.ai_base.multimodal.constants import (
    DEFAULT_IMAGE_PROMPT,
    DEFAULT_MULTIMODAL_SYSTEM_PROMPT,
    IMAGE_DETAIL_AUTO,
)


@pytest.fixture
def mock_prompt():
    """Create a mock MultimodalPromptBase."""
    prompt = MagicMock(spec=MultimodalPromptBase)
    prompt.messages = []
    prompt.to_dict_list.return_value = []
    return prompt


@pytest.fixture
def mock_model():
    """Create a mock MultimodalLLMModel."""
    model = MagicMock(spec=MultimodalLLMModel)
    model.content_senders = []
    model.max_tokens = 8000
    model.temperature = 0.3
    return model


class TestMultimodalLLMChatInitialization:
    """Test MultimodalLLMChat initialization."""

    def test_init_with_prompt_ctl_and_llm_model(self, mock_prompt, mock_model):
        """Test initialization with prompt controller and LLM model."""
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        assert chat.prompt_ctl is mock_prompt
        assert chat.llm_model is mock_model
        assert chat.first_message == ""
        assert chat.last_message == ""


class TestMultimodalLLMChatChat:
    """Test MultimodalLLMChat.chat method."""

    def test_chat_sends_text_message(self, mock_prompt, mock_model):
        """Test chat sends a text-only message to LLM."""
        mock_model.chat_with_prompt.return_value = "Hello, user!"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        result = chat.chat("Hello", need_print=False)

        mock_prompt.add_user_message.assert_called_once_with("Hello", need_print=False)
        mock_model.chat_with_prompt.assert_called_once_with(
            mock_prompt, for_raw=True, for_stream=False
        )
        mock_prompt.add_assistant_message.assert_called_once_with("Hello, user!")
        assert result == "Hello, user!"
        assert chat.last_message == "Hello, user!"

    def test_chat_with_empty_message(self, mock_prompt, mock_model):
        """Test chat with empty message does not add user message."""
        mock_model.chat_with_prompt.return_value = "Response"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        result = chat.chat("", need_print=False)

        mock_prompt.add_user_message.assert_not_called()
        mock_model.chat_with_prompt.assert_called_once()
        assert result == "Response"

    def test_chat_strips_response(self, mock_prompt, mock_model):
        """Test that response is stripped of whitespace."""
        mock_model.chat_with_prompt.return_value = "  Response with spaces  \n"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        result = chat.chat("Hello", need_print=False)

        mock_prompt.add_assistant_message.assert_called_once_with("Response with spaces")
        assert result == "Response with spaces"

    def test_chat_sets_first_message(self, mock_prompt, mock_model):
        """Test that first_message is set when message is provided."""
        mock_model.chat_with_prompt.return_value = "Response"
        chat = MultimodalLLMChat(mock_prompt, mock_model)
        chat.first_message = "Hello"

        chat.chat("Hello", need_print=False)

        assert chat.first_message == "Hello"


class TestMultimodalLLMChatChatWithImage:
    """Test MultimodalLLMChat.chat_with_image method."""

    def test_chat_with_image_sends_image_and_text(self, mock_prompt, mock_model):
        """Test chat_with_image sends image + text to LLM."""
        mock_model.chat_with_prompt.return_value = "The image shows a cat."
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with patch("os.path.exists", return_value=False):
            result = chat.chat_with_image(
                message="What is in this image?",
                image_source="https://example.com/image.png",
                detail="high",
            )

        # Verify user message was added with text + image content items
        call_args = mock_prompt.add_user_message.call_args
        assert call_args[1]["text"] == ""
        media_items = call_args[1]["media_items"]
        assert len(media_items) == 2
        assert isinstance(media_items[0], TextContent)
        assert media_items[0].text == "What is in this image?"
        assert isinstance(media_items[1], ImageContent)
        assert media_items[1].source == "https://example.com/image.png"
        assert media_items[1].detail == "high"

        mock_model.chat_with_prompt.assert_called_once_with(
            mock_prompt, for_raw=True, for_stream=False
        )
        mock_prompt.add_assistant_message.assert_called_once_with("The image shows a cat.")
        assert result == "The image shows a cat."

    def test_chat_with_image_default_prompt(self, mock_prompt, mock_model):
        """Test chat_with_image uses default prompt when message is empty."""
        mock_model.chat_with_prompt.return_value = "Description"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with patch("os.path.exists", return_value=False):
            chat.chat_with_image(
                message="",
                image_source="https://example.com/image.png",
            )

        call_args = mock_prompt.add_user_message.call_args
        media_items = call_args[1]["media_items"]
        assert media_items[0].text == DEFAULT_IMAGE_PROMPT

    def test_chat_with_image_relative_path(self, mock_prompt, mock_model):
        """Test chat_with_image resolves relative paths."""
        mock_model.chat_with_prompt.return_value = "Description"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with patch("os.path.abspath", return_value="/abs/path/to/image.png"):
            with patch("os.path.exists", return_value=True):
                chat.chat_with_image(
                    message="Describe this",
                    image_source="image.png",
                )

        call_args = mock_prompt.add_user_message.call_args
        media_items = call_args[1]["media_items"]
        assert media_items[1].source == "/abs/path/to/image.png"

    def test_chat_with_image_empty_source_raises(self, mock_prompt, mock_model):
        """Test chat_with_image raises ValueError for empty image_source."""
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with pytest.raises(ValueError, match="image_source must be a non-empty string"):
            chat.chat_with_image(message="test", image_source="")

    def test_chat_with_image_none_source_raises(self, mock_prompt, mock_model):
        """Test chat_with_image raises ValueError for None image_source."""
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with pytest.raises(ValueError, match="image_source must be a non-empty string"):
            chat.chat_with_image(message="test", image_source=None)

    def test_chat_with_image_detail_default(self, mock_prompt, mock_model):
        """Test chat_with_image uses default detail level."""
        mock_model.chat_with_prompt.return_value = "Description"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with patch("os.path.exists", return_value=False):
            chat.chat_with_image(
                message="Describe",
                image_source="https://example.com/image.png",
            )

        call_args = mock_prompt.add_user_message.call_args
        media_items = call_args[1]["media_items"]
        assert media_items[1].detail == IMAGE_DETAIL_AUTO

    def test_chat_with_image_strips_source(self, mock_prompt, mock_model):
        """Test chat_with_image strips whitespace from image_source."""
        mock_model.chat_with_prompt.return_value = "Description"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with patch("os.path.exists", return_value=False):
            chat.chat_with_image(
                message="Describe",
                image_source="  https://example.com/image.png  ",
            )

        call_args = mock_prompt.add_user_message.call_args
        media_items = call_args[1]["media_items"]
        assert media_items[1].source == "https://example.com/image.png"


class TestMultimodalLLMChatChatWithMedia:
    """Test MultimodalLLMChat.chat_with_media method."""

    def test_chat_with_media_text_and_items(self, mock_prompt, mock_model):
        """Test chat_with_media with text and media items."""
        mock_model.chat_with_prompt.return_value = "Analysis"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        media_items = [ImageContent("https://example.com/image.png")]
        result = chat.chat_with_media(
            message="Analyze this",
            media_items=media_items,
        )

        mock_prompt.add_user_message.assert_called_once_with(
            text="Analyze this",
            media_items=media_items,
        )
        assert result == "Analysis"

    def test_chat_with_media_only_media(self, mock_prompt, mock_model):
        """Test chat_with_media with only media items."""
        mock_model.chat_with_prompt.return_value = "Analysis"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        media_items = [ImageContent("https://example.com/image.png")]
        result = chat.chat_with_media(
            message="",
            media_items=media_items,
        )

        mock_prompt.add_user_message.assert_called_once_with(
            text="",
            media_items=media_items,
        )
        assert result == "Analysis"

    def test_chat_with_media_empty_raises(self, mock_prompt, mock_model):
        """Test chat_with_media raises ValueError when both are empty."""
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with pytest.raises(ValueError, match="Either message or media_items must be provided"):
            chat.chat_with_media(message="", media_items=None)


class TestGetMultimodalLLMChat:
    """Test get_multimodal_llm_chat factory function."""

    def test_returns_multimodal_llm_chat_instance(self):
        """Test factory returns a MultimodalLLMChat instance."""
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                chat = get_multimodal_llm_chat(
                    message="Hello",
                    system_prompt="You are a vision expert.",
                )

        assert isinstance(chat, MultimodalLLMChat)
        assert chat.first_message == "Hello"

    def test_with_custom_system_prompt(self):
        """Test factory with custom system prompt."""
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                chat = get_multimodal_llm_chat(
                    system_prompt="Custom system prompt",
                )

        # The prompt controller should have the custom system prompt
        assert chat.prompt_ctl.system_prompt == "Custom system prompt"
        assert chat.prompt_ctl.messages[0].role == "system"
        assert chat.prompt_ctl.messages[0].get_text_content() == "Custom system prompt"

    def test_with_default_system_prompt(self):
        """Test factory uses default system prompt when none provided."""
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                with patch.dict(os.environ, {"SYSTEM_PROMPT": ""}, clear=True):
                    chat = get_multimodal_llm_chat()

        assert chat.prompt_ctl.system_prompt == DEFAULT_MULTIMODAL_SYSTEM_PROMPT

    def test_with_message_adds_user_message(self):
        """Test factory adds user message when message is provided."""
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                chat = get_multimodal_llm_chat(message="Hello there")

        assert len(chat.prompt_ctl.messages) == 2  # system + user
        assert chat.prompt_ctl.messages[1].role == "user"
        assert chat.prompt_ctl.messages[1].get_text_content() == "Hello there"
        assert chat.first_message == "Hello there"

    def test_model_configuration(self):
        """Test that model is configured with correct parameters.
        
        Note: max_tokens uses max(3000, max_tokens, model.max_tokens).
        Since mock_model.max_tokens is 8000, the result is max(3000, 5000, 8000) = 8000.
        """
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                get_multimodal_llm_chat(
                    max_tokens=5000,
                    temperature=0.5,
                    need_stdout=True,
                )

        # max(3000, 5000, 8000) = 8000
        assert mock_model.max_tokens == 8000
        # max(0.3, 0.5, 0.3) = 0.5
        assert mock_model.temperature == 0.5
        assert len(mock_model.content_senders) == 1  # ContentStdout added

    def test_model_configuration_defaults(self):
        """Test that model uses default parameters."""
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                get_multimodal_llm_chat()

        assert mock_model.max_tokens == 8000  # max(3000, 4000, 8000)
        assert mock_model.temperature == 0.3  # max(0.3, 0.3, 0.3)

    def test_without_message_no_input(self):
        """Test factory without message and need_input_message=False."""
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                with patch("topsailai.utils.env_tool.EnvReaderInstance.read_file_or_content", return_value=""):
                    chat = get_multimodal_llm_chat(need_input_message=False)

        assert chat.first_message == ""
        assert len(chat.prompt_ctl.messages) == 1  # Only system message

    def test_need_print_session_logs(self):
        """Test that need_print_session=True logs info."""
        with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
            with patch("topsailai.ai_base.multimodal.llm_shell.MultimodalLLMModel") as mock_model_cls:
                mock_model = MagicMock()
                mock_model.content_senders = []
                mock_model.max_tokens = 8000
                mock_model.temperature = 0.3
                mock_model_cls.return_value = mock_model

                with patch("topsailai.ai_base.multimodal.llm_shell.logger") as mock_logger:
                    get_multimodal_llm_chat(need_print_session=True)

                    mock_logger.info.assert_called_once()


class TestIntegration:
    """Integration-style tests for the multimodal chat flow."""

    def test_full_image_chat_flow(self, mock_prompt, mock_model):
        """Test a complete image chat flow end-to-end."""
        mock_model.chat_with_prompt.return_value = "I see a beautiful landscape."
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        with patch("os.path.exists", return_value=False):
            result = chat.chat_with_image(
                message="Describe this image",
                image_source="https://example.com/photo.jpg",
                detail="high",
            )

        assert result == "I see a beautiful landscape."
        assert chat.last_message == "I see a beautiful landscape."

        # Verify the message structure passed to add_user_message
        call_args = mock_prompt.add_user_message.call_args
        media_items = call_args[1]["media_items"]
        assert len(media_items) == 2
        assert media_items[0].to_dict() == {"type": "text", "text": "Describe this image"}
        assert media_items[1].to_dict()["type"] == "image_url"
        assert media_items[1].to_dict()["image_url"]["detail"] == "high"

    def test_conversation_sequence(self, mock_prompt, mock_model):
        """Test a multi-turn conversation with text and images."""
        mock_model.chat_with_prompt.side_effect = [
            "First response",
            "Second response",
        ]
        chat = MultimodalLLMChat(mock_prompt, mock_model)
        chat.first_message = "Hello"  # Simulate factory setting first_message

        # First turn: text only
        result1 = chat.chat("Hello", need_print=False)
        assert result1 == "First response"

        # Second turn: with image
        with patch("os.path.exists", return_value=False):
            result2 = chat.chat_with_image(
                message="What about this?",
                image_source="https://example.com/image.png",
            )
        assert result2 == "Second response"

        assert chat.first_message == "Hello"
        assert chat.last_message == "Second response"
        assert mock_prompt.add_user_message.call_count == 2
        assert mock_prompt.add_assistant_message.call_count == 2

    def test_chat_with_media_multiple_types(self, mock_prompt, mock_model):
        """Test chat_with_media with multiple media types."""
        mock_model.chat_with_prompt.return_value = "Multimedia analysis"
        chat = MultimodalLLMChat(mock_prompt, mock_model)

        from topsailai.ai_base.multimodal.message import VideoContent, AudioContent

        media_items = [
            ImageContent("https://example.com/image.png"),
            VideoContent("https://example.com/video.mp4"),
            AudioContent("https://example.com/audio.mp3"),
        ]
        result = chat.chat_with_media(
            message="Analyze all media",
            media_items=media_items,
        )

        assert result == "Multimedia analysis"
        call_args = mock_prompt.add_user_message.call_args
        assert len(call_args[1]["media_items"]) == 3
