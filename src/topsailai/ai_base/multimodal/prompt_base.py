"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-06-14
  Purpose: Multimodal prompt base for managing conversation history with
           structured message classes (MultimodalMessage, ContentItem).
"""

from typing import List, Optional

from topsailai.ai_base.constants import (
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_TOOL,
)
from topsailai.utils.print_tool import print_debug

from .message import (
    MultimodalMessage,
    ContentItem,
    TextContent,
)


class MultimodalPromptBase(object):
    """
    Prompt controller for multimodal conversation management.

    Manages conversation history using MultimodalMessage and ContentItem
    classes instead of raw list/dict. All messages are stored as
    MultimodalMessage objects and converted to API-compatible dicts
    only when needed for LLM calls.

    Attributes:
        messages (list): List of MultimodalMessage objects representing
            the conversation history.
        system_prompt (str): The current system prompt text.
    """

    def __init__(self, system_prompt: str = ""):
        """
        Initialize the MultimodalPromptBase.

        Args:
            system_prompt (str, optional): The system prompt to initialize
                the conversation with. If provided, a system message is
                automatically added. Defaults to empty string.
        """
        self.messages: List[MultimodalMessage] = []
        self.system_prompt = system_prompt
        if system_prompt:
            self.reset_messages(system_prompt)

    def reset_messages(self, system_prompt: str = ""):
        """
        Reset the conversation history with a system prompt.

        Clears all existing messages and adds a new system message.

        Args:
            system_prompt (str, optional): The system prompt text.
                If empty, uses the existing system_prompt attribute.
        """
        self.messages = []
        if system_prompt:
            self.system_prompt = system_prompt
        if self.system_prompt:
            self.add_system_message(self.system_prompt)

    def add_user_message(
        self,
        text: str = "",
        media_items: Optional[List[ContentItem]] = None,
        need_print: bool = False,
    ) -> MultimodalMessage:
        """
        Add a user message to the conversation.

        Creates a user message with optional text and media content items.
        Text content is always placed first, followed by media items.

        Args:
            text (str, optional): The text content of the message.
                Defaults to empty string.
            media_items (list, optional): List of ContentItem objects
                (ImageContent, VideoContent, AudioContent) to include.
                Defaults to None.
            need_print (bool, optional): Whether to print the message
                content for debugging. Defaults to False.

        Returns:
            MultimodalMessage: The created user message.

        Raises:
            ValueError: If text is not a string or media_items contains
                non-ContentItem objects.

        Example:
            >>> from topsailai.ai_base.multimodal.message import ImageContent
            >>> prompt = MultimodalPromptBase("You are a vision assistant.")
            >>> prompt.add_user_message(
            ...     text="Describe this image",
            ...     media_items=[ImageContent("/path/to/image.png")],
            ... )
        """
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text).__name__}")

        content_items = []
        if text:
            content_items.append(TextContent(text))

        if media_items:
            for item in media_items:
                if not isinstance(item, ContentItem):
                    raise ValueError(
                        f"All media_items must be ContentItem instances, "
                        f"got {type(item).__name__}"
                    )
                content_items.append(item)

        if not content_items:
            raise ValueError("Either text or media_items must be provided")

        if need_print:
            print_debug(f"[User Message] {text}")

        message = MultimodalMessage(ROLE_USER, content_items)
        self.messages.append(message)
        return message

    def add_assistant_message(self, text: str, need_print: bool = False) -> MultimodalMessage:
        """
        Add an assistant message to the conversation.

        Args:
            text (str): The assistant's response text.
            need_print (bool, optional): Whether to print the message
                content for debugging. Defaults to False.

        Returns:
            MultimodalMessage: The created assistant message.

        Raises:
            ValueError: If text is not a string.
        """
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text).__name__}")

        if need_print:
            print_debug(f"[Assistant Message] {text}")

        message = MultimodalMessage(ROLE_ASSISTANT, [TextContent(text)])
        self.messages.append(message)
        return message

    def add_system_message(self, text: str) -> MultimodalMessage:
        """
        Add a system message to the conversation.

        Args:
            text (str): The system prompt text.

        Returns:
            MultimodalMessage: The created system message.

        Raises:
            ValueError: If text is not a string or is empty.
        """
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text).__name__}")
        if not text.strip():
            raise ValueError("system message text cannot be empty")

        message = MultimodalMessage(ROLE_SYSTEM, [TextContent(text)])
        self.messages.append(message)
        return message

    def add_tool_message(self, text: str, tool_call_id: str = "") -> MultimodalMessage:
        """
        Add a tool result message to the conversation.

        Args:
            text (str): The tool result text.
            tool_call_id (str, optional): The ID of the tool call this
                result corresponds to. Defaults to empty string.

        Returns:
            MultimodalMessage: The created tool message.

        Raises:
            ValueError: If text is not a string.
        """
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text).__name__}")

        message = MultimodalMessage(
            ROLE_TOOL,
            [TextContent(text)],
            tool_call_id=tool_call_id or None,
        )
        self.messages.append(message)
        return message

    def get_last_message(self) -> Optional[MultimodalMessage]:
        """
        Get the most recent message in the conversation.

        Returns:
            MultimodalMessage or None: The last message, or None if
                the conversation is empty.
        """
        if not self.messages:
            return None
        return self.messages[-1]

    def get_messages_by_role(self, role: str) -> List[MultimodalMessage]:
        """
        Get all messages with a specific role.

        Args:
            role (str): The role to filter by ("user", "assistant",
                "system", or "tool").

        Returns:
            list: All messages matching the specified role.
        """
        return [msg for msg in self.messages if msg.role == role]

    def clear_messages(self):
        """
        Clear all messages from the conversation history.

        Removes all messages including system messages. Use reset_messages()
        to re-initialize with a system prompt.
        """
        self.messages = []

    def to_dict_list(self) -> List[dict]:
        """
        Convert all messages to a list of API-compatible dictionaries.

        Each MultimodalMessage is converted via its to_dict() method,
        producing OpenAI-compatible message dictionaries.

        Returns:
            list: List of message dictionaries ready for LLM API calls.

        Example:
            >>> prompt = MultimodalPromptBase("You are helpful.")
            >>> prompt.add_user_message("Hello")
            >>> prompt.to_dict_list()
            [
                {'role': 'system', 'content': 'You are helpful.'},
                {'role': 'user', 'content': 'Hello'},
            ]
        """
        return [msg.to_dict() for msg in self.messages]
