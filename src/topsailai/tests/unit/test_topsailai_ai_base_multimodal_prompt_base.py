"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-06-14
  Purpose: Unit tests for MultimodalPromptBase class.
"""

import pytest
from unittest.mock import patch

from topsailai.ai_base.multimodal.prompt_base import MultimodalPromptBase
from topsailai.ai_base.multimodal.message import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    MultimodalMessage,
)
from topsailai.ai_base.constants import (
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_TOOL,
)


class TestInitialization:
    """Test MultimodalPromptBase initialization."""

    def test_init_with_system_prompt(self):
        """Test initialization with a system prompt creates a system message."""
        prompt = MultimodalPromptBase("You are a helpful assistant.")

        assert len(prompt.messages) == 1
        assert prompt.messages[0].role == ROLE_SYSTEM
        assert prompt.system_prompt == "You are a helpful assistant."
        assert prompt.messages[0].get_text_content() == "You are a helpful assistant."

    def test_init_without_system_prompt(self):
        """Test initialization without a system prompt creates no messages."""
        prompt = MultimodalPromptBase()

        assert len(prompt.messages) == 0
        assert prompt.system_prompt == ""

    def test_init_with_empty_string_system_prompt(self):
        """Test initialization with empty string system prompt creates no messages."""
        prompt = MultimodalPromptBase("")

        assert len(prompt.messages) == 0
        assert prompt.system_prompt == ""


class TestAddUserMessage:
    """Test add_user_message method."""

    def test_add_user_message_text_only(self):
        """Test adding a user message with text only."""
        prompt = MultimodalPromptBase()
        message = prompt.add_user_message("Hello, world!")

        assert len(prompt.messages) == 1
        assert message.role == ROLE_USER
        assert message.get_text_content() == "Hello, world!"
        assert message.to_dict() == {"role": ROLE_USER, "content": "Hello, world!"}

    def test_add_user_message_with_media(self):
        """Test adding a user message with text and media items."""
        prompt = MultimodalPromptBase()
        media_items = [
            ImageContent("https://example.com/image.png"),
            VideoContent("https://example.com/video.mp4"),
        ]
        message = prompt.add_user_message(
            "Describe this media",
            media_items=media_items,
        )

        assert len(prompt.messages) == 1
        assert message.role == ROLE_USER
        assert message.has_media_content() is True

        result = message.to_dict()
        assert result["role"] == ROLE_USER
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 3
        assert result["content"][0] == {"type": "text", "text": "Describe this media"}
        assert result["content"][1]["type"] == "image_url"
        assert result["content"][2]["type"] == "video"

    def test_add_user_message_media_only(self):
        """Test adding a user message with only media items (no text)."""
        prompt = MultimodalPromptBase()
        media_items = [ImageContent("https://example.com/image.png")]
        message = prompt.add_user_message(
            "",
            media_items=media_items,
        )

        assert len(prompt.messages) == 1
        assert message.role == ROLE_USER
        assert message.get_text_content() == ""

        result = message.to_dict()
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "image_url"

    def test_add_user_message_empty_raises(self):
        """Test that adding a user message with empty text and no media raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="Either text or media_items must be provided"):
            prompt.add_user_message("")

    def test_add_user_message_invalid_text_type(self):
        """Test that adding a user message with non-string text raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="text must be a string"):
            prompt.add_user_message(123)

    def test_add_user_message_invalid_media_item(self):
        """Test that adding a user message with invalid media item raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="All media_items must be ContentItem instances"):
            prompt.add_user_message("Hello", media_items=["not a content item"])

    def test_add_user_message_multiple_media_types(self):
        """Test adding a user message with multiple media types."""
        prompt = MultimodalPromptBase()
        media_items = [
            ImageContent("https://example.com/image.png"),
            AudioContent("https://example.com/audio.mp3"),
            VideoContent("https://example.com/video.mp4"),
        ]
        message = prompt.add_user_message(
            "Analyze all media",
            media_items=media_items,
        )

        result = message.to_dict()
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 4
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "image_url"
        assert result["content"][2]["type"] == "audio"
        assert result["content"][3]["type"] == "video"

    @patch("topsailai.ai_base.multimodal.prompt_base.print_debug")
    def test_add_user_message_need_print(self, mock_print_debug):
        """Test that need_print=True calls print_debug."""
        prompt = MultimodalPromptBase()
        prompt.add_user_message("Test message", need_print=True)

        mock_print_debug.assert_called_once_with("[User Message] Test message")


class TestAddAssistantMessage:
    """Test add_assistant_message method."""

    def test_add_assistant_message(self):
        """Test adding an assistant message."""
        prompt = MultimodalPromptBase()
        message = prompt.add_assistant_message("I can help you with that.")

        assert len(prompt.messages) == 1
        assert message.role == ROLE_ASSISTANT
        assert message.get_text_content() == "I can help you with that."
        assert message.to_dict() == {
            "role": ROLE_ASSISTANT,
            "content": "I can help you with that.",
        }

    def test_add_assistant_message_invalid_type(self):
        """Test that adding an assistant message with non-string raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="text must be a string"):
            prompt.add_assistant_message(123)

    @patch("topsailai.ai_base.multimodal.prompt_base.print_debug")
    def test_add_assistant_message_need_print(self, mock_print_debug):
        """Test that need_print=True calls print_debug."""
        prompt = MultimodalPromptBase()
        prompt.add_assistant_message("Test response", need_print=True)

        mock_print_debug.assert_called_once_with("[Assistant Message] Test response")


class TestAddSystemMessage:
    """Test add_system_message method."""

    def test_add_system_message(self):
        """Test adding a system message."""
        prompt = MultimodalPromptBase()
        message = prompt.add_system_message("You are a coding assistant.")

        assert len(prompt.messages) == 1
        assert message.role == ROLE_SYSTEM
        assert message.get_text_content() == "You are a coding assistant."
        assert message.to_dict() == {
            "role": ROLE_SYSTEM,
            "content": "You are a coding assistant.",
        }

    def test_add_system_message_invalid_type(self):
        """Test that adding a system message with non-string raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="text must be a string"):
            prompt.add_system_message(123)

    def test_add_system_message_empty_raises(self):
        """Test that adding an empty system message raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="system message text cannot be empty"):
            prompt.add_system_message("")

    def test_add_system_message_whitespace_raises(self):
        """Test that adding a whitespace-only system message raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="system message text cannot be empty"):
            prompt.add_system_message("   ")


class TestAddToolMessage:
    """Test add_tool_message method."""

    def test_add_tool_message_with_tool_call_id(self):
        """Test adding a tool message with tool_call_id."""
        prompt = MultimodalPromptBase()
        message = prompt.add_tool_message(
            "The weather is sunny.",
            tool_call_id="call_12345",
        )

        assert len(prompt.messages) == 1
        assert message.role == ROLE_TOOL
        assert message.get_text_content() == "The weather is sunny."
        assert message.tool_call_id == "call_12345"

        result = message.to_dict()
        assert result["role"] == ROLE_TOOL
        assert result["content"] == "The weather is sunny."
        assert result["tool_call_id"] == "call_12345"

    def test_add_tool_message_without_tool_call_id(self):
        """Test adding a tool message without tool_call_id."""
        prompt = MultimodalPromptBase()
        message = prompt.add_tool_message("The weather is sunny.")

        assert message.tool_call_id is None

        result = message.to_dict()
        assert "tool_call_id" not in result

    def test_add_tool_message_empty_tool_call_id(self):
        """Test that empty string tool_call_id is treated as None."""
        prompt = MultimodalPromptBase()
        message = prompt.add_tool_message(
            "Result here",
            tool_call_id="",
        )

        assert message.tool_call_id is None

        result = message.to_dict()
        assert "tool_call_id" not in result

    def test_add_tool_message_invalid_type(self):
        """Test that adding a tool message with non-string text raises ValueError."""
        prompt = MultimodalPromptBase()

        with pytest.raises(ValueError, match="text must be a string"):
            prompt.add_tool_message(123)


class TestToDictList:
    """Test to_dict_list method."""

    def test_to_dict_list_empty(self):
        """Test to_dict_list with no messages."""
        prompt = MultimodalPromptBase()

        assert prompt.to_dict_list() == []

    def test_to_dict_list_with_messages(self):
        """Test to_dict_list converts all messages to dicts."""
        prompt = MultimodalPromptBase("You are helpful.")
        prompt.add_user_message("Hello")
        prompt.add_assistant_message("Hi there!")

        result = prompt.to_dict_list()
        assert len(result) == 3
        assert result[0] == {"role": ROLE_SYSTEM, "content": "You are helpful."}
        assert result[1] == {"role": ROLE_USER, "content": "Hello"}
        assert result[2] == {"role": ROLE_ASSISTANT, "content": "Hi there!"}

    def test_to_dict_list_with_multimodal(self):
        """Test to_dict_list with multimodal content."""
        prompt = MultimodalPromptBase()
        prompt.add_user_message(
            "Describe this",
            media_items=[ImageContent("https://example.com/image.png")],
        )

        result = prompt.to_dict_list()
        assert len(result) == 1
        assert result[0]["role"] == ROLE_USER
        assert isinstance(result[0]["content"], list)

    def test_to_dict_list_with_tool_message(self):
        """Test to_dict_list includes tool_call_id for tool messages."""
        prompt = MultimodalPromptBase()
        prompt.add_tool_message("Result", tool_call_id="call_abc")

        result = prompt.to_dict_list()
        assert len(result) == 1
        assert result[0]["role"] == ROLE_TOOL
        assert result[0]["tool_call_id"] == "call_abc"


class TestClearMessages:
    """Test clear_messages method."""

    def test_clear_messages(self):
        """Test clearing all messages."""
        prompt = MultimodalPromptBase("System prompt")
        prompt.add_user_message("Hello")
        prompt.add_assistant_message("Hi")

        assert len(prompt.messages) == 3

        prompt.clear_messages()

        assert len(prompt.messages) == 0

    def test_clear_messages_empty(self):
        """Test clearing an already empty message list."""
        prompt = MultimodalPromptBase()

        prompt.clear_messages()

        assert len(prompt.messages) == 0


class TestResetMessages:
    """Test reset_messages method."""

    def test_reset_messages_with_new_prompt(self):
        """Test resetting messages with a new system prompt."""
        prompt = MultimodalPromptBase("Original prompt")
        prompt.add_user_message("Hello")

        assert len(prompt.messages) == 2

        prompt.reset_messages("New system prompt")

        assert len(prompt.messages) == 1
        assert prompt.messages[0].role == ROLE_SYSTEM
        assert prompt.messages[0].get_text_content() == "New system prompt"
        assert prompt.system_prompt == "New system prompt"

    def test_reset_messages_without_prompt(self):
        """Test resetting messages without providing a new prompt."""
        prompt = MultimodalPromptBase("Original prompt")
        prompt.add_user_message("Hello")

        prompt.reset_messages()

        assert len(prompt.messages) == 1
        assert prompt.messages[0].get_text_content() == "Original prompt"

    def test_reset_messages_empty_prompt(self):
        """Test resetting messages with empty string keeps existing system prompt."""
        prompt = MultimodalPromptBase("Original prompt")
        prompt.add_user_message("Hello")

        prompt.reset_messages("")

        # Empty string doesn't change system_prompt, so existing prompt is re-added
        assert len(prompt.messages) == 1
        assert prompt.messages[0].role == ROLE_SYSTEM
        assert prompt.messages[0].get_text_content() == "Original prompt"
        assert prompt.system_prompt == "Original prompt"


class TestGetLastMessage:
    """Test get_last_message method."""

    def test_get_last_message(self):
        """Test getting the last message."""
        prompt = MultimodalPromptBase()
        prompt.add_user_message("First")
        prompt.add_assistant_message("Second")

        last = prompt.get_last_message()
        assert last is not None
        assert last.role == ROLE_ASSISTANT
        assert last.get_text_content() == "Second"

    def test_get_last_message_empty(self):
        """Test getting last message from empty conversation."""
        prompt = MultimodalPromptBase()

        assert prompt.get_last_message() is None


class TestGetMessagesByRole:
    """Test get_messages_by_role method."""

    def test_get_messages_by_role(self):
        """Test filtering messages by role."""
        prompt = MultimodalPromptBase("System prompt")
        prompt.add_user_message("User 1")
        prompt.add_assistant_message("Assistant 1")
        prompt.add_user_message("User 2")

        user_messages = prompt.get_messages_by_role(ROLE_USER)
        assert len(user_messages) == 2
        assert user_messages[0].get_text_content() == "User 1"
        assert user_messages[1].get_text_content() == "User 2"

        assistant_messages = prompt.get_messages_by_role(ROLE_ASSISTANT)
        assert len(assistant_messages) == 1
        assert assistant_messages[0].get_text_content() == "Assistant 1"

        system_messages = prompt.get_messages_by_role(ROLE_SYSTEM)
        assert len(system_messages) == 1

    def test_get_messages_by_role_no_match(self):
        """Test filtering messages by role with no matches."""
        prompt = MultimodalPromptBase()
        prompt.add_user_message("Hello")

        tool_messages = prompt.get_messages_by_role(ROLE_TOOL)
        assert tool_messages == []

    def test_get_messages_by_role_empty(self):
        """Test filtering messages from empty conversation."""
        prompt = MultimodalPromptBase()

        assert prompt.get_messages_by_role(ROLE_USER) == []


class TestConversationFlow:
    """Test realistic conversation flows."""

    def test_full_conversation(self):
        """Test a complete conversation flow."""
        prompt = MultimodalPromptBase("You are a vision assistant.")
        prompt.add_user_message(
            "What's in this image?",
            media_items=[ImageContent("https://example.com/photo.jpg")],
        )
        prompt.add_assistant_message("I see a beautiful sunset over the ocean.")
        prompt.add_user_message("What colors do you see?")
        prompt.add_assistant_message("I see orange, pink, and purple hues.")

        assert len(prompt.messages) == 5

        result = prompt.to_dict_list()
        assert result[0]["role"] == ROLE_SYSTEM
        assert result[1]["role"] == ROLE_USER
        assert isinstance(result[1]["content"], list)
        assert result[2]["role"] == ROLE_ASSISTANT
        assert result[3]["role"] == ROLE_USER
        assert result[3]["content"] == "What colors do you see?"
        assert result[4]["role"] == ROLE_ASSISTANT

    def test_tool_conversation_flow(self):
        """Test a conversation involving tool calls."""
        prompt = MultimodalPromptBase("You are a helpful assistant.")
        prompt.add_user_message("What's the weather?")
        prompt.add_assistant_message("I'll check the weather for you.")
        prompt.add_tool_message("Sunny, 25C", tool_call_id="call_weather_1")
        prompt.add_assistant_message("The weather is sunny and 25C.")

        assert len(prompt.messages) == 5

        result = prompt.to_dict_list()
        assert result[3]["role"] == ROLE_TOOL
        assert result[3]["tool_call_id"] == "call_weather_1"

    def test_multiple_media_per_message(self):
        """Test adding multiple images in a single message."""
        prompt = MultimodalPromptBase()
        prompt.add_user_message(
            "Compare these images",
            media_items=[
                ImageContent("https://example.com/image1.png"),
                ImageContent("https://example.com/image2.png"),
            ],
        )

        result = prompt.to_dict_list()
        content = result[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 3  # text + 2 images
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[2]["type"] == "image_url"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_add_user_message_whitespace_text_with_media(self):
        """Test that whitespace-only text with media is accepted."""
        prompt = MultimodalPromptBase()
        message = prompt.add_user_message(
            "   ",
            media_items=[ImageContent("https://example.com/image.png")],
        )

        assert len(prompt.messages) == 1
        result = message.to_dict()
        assert isinstance(result["content"], list)
        assert result["content"][0]["text"] == "   "

    def test_add_user_message_none_text_with_media(self):
        """Test that None text raises ValueError."""
        prompt = MultimodalPromptBase()
        with pytest.raises(ValueError, match="text must be a string"):
            prompt.add_user_message(None, media_items=[ImageContent("https://example.com/image.png")])

    def test_messages_attribute_is_list(self):
        """Test that messages attribute is a list."""
        prompt = MultimodalPromptBase()
        assert isinstance(prompt.messages, list)

    def test_messages_are_multimodal_message_instances(self):
        """Test that all messages are MultimodalMessage instances."""
        prompt = MultimodalPromptBase("System")
        prompt.add_user_message("Hello")
        prompt.add_assistant_message("Hi")

        for msg in prompt.messages:
            assert isinstance(msg, MultimodalMessage)

    def test_system_prompt_attribute_persists(self):
        """Test that system_prompt attribute persists across operations."""
        prompt = MultimodalPromptBase("Original")
        prompt.add_user_message("Hello")
        prompt.clear_messages()

        assert prompt.system_prompt == "Original"
