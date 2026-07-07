"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-06-14
  Purpose: Multimodal LLM Shell - factory for creating multimodal chat instances.
"""

import os
from typing import Optional

from topsailai.ai_base.llm_control.content_endpoint import ContentStdout
from topsailai.utils import env_tool
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.logger.log_chat import logger

from .llm_base import MultimodalLLMModel
from .prompt_base import MultimodalPromptBase
from .message import (
    MultimodalMessage,
    TextContent,
    ImageContent,
)
from .constants import (
    DEFAULT_IMAGE_PROMPT,
    DEFAULT_MULTIMODAL_SYSTEM_PROMPT,
    IMAGE_DETAIL_AUTO,
)


class MultimodalLLMChat(object):
    """
    A chat interface for multimodal LLM interactions.

    Manages conversation history using MultimodalPromptBase and sends messages
    via MultimodalLLMModel. Supports text, image, video, and audio content.

    Attributes:
        prompt_ctl (MultimodalPromptBase): The prompt controller managing messages.
        llm_model (MultimodalLLMModel): The LLM model for generating responses.
        first_message (str): The first message in the conversation.
        last_message (str): The last response from the LLM.
    """

    def __init__(self, prompt_ctl: MultimodalPromptBase, llm_model: MultimodalLLMModel):
        """
        Initialize the MultimodalLLMChat instance.

        Args:
            prompt_ctl (MultimodalPromptBase): The prompt controller.
            llm_model (MultimodalLLMModel): The multimodal LLM model.
        """
        self.prompt_ctl = prompt_ctl
        self.llm_model = llm_model
        self.first_message = ""
        self.last_message = ""

    def chat(self, message: str = "", need_print: bool = True) -> str:
        """
        Send a text-only message to the LLM.

        Args:
            message (str): The user's text message.
            need_print (bool): Whether to print the message. Defaults to True.

        Returns:
            str: The LLM's response content.
        """
        if message:
            self.prompt_ctl.add_user_message(message, need_print=need_print)

        answer = self.llm_model.chat_with_prompt(self.prompt_ctl, for_raw=True, for_stream=False)
        if answer:
            answer = str(answer).strip()
        self.prompt_ctl.add_assistant_message(answer)
        self.last_message = answer
        return answer

    def chat_with_image(
        self,
        message: str = "",
        image_source: str = "",
        detail: str = IMAGE_DETAIL_AUTO,
    ) -> str:
        """
        Send a message with an image to the LLM for vision analysis.

        Creates a user message containing both text and image content,
        sends it to the vision-capable LLM, and returns the response.

        Args:
            message (str): The text prompt or question about the image.
                Defaults to DEFAULT_IMAGE_PROMPT if empty.
            image_source (str): File path or URL to the image.
                - Local file: absolute path like "/path/to/image.png"
                - URL: "https://example.com/image.jpg"
            detail (str): Image detail level. One of "auto", "low", "high".
                Defaults to "auto".

        Returns:
            str: The LLM's description or analysis of the image.

        Raises:
            ValueError: If image_source is empty or invalid.
            FileNotFoundError: If the local image file does not exist.

        Example:
            >>> chat = get_multimodal_llm_chat()
            >>> response = chat.chat_with_image(
            ...     message="What is in this image?",
            ...     image_source="/path/to/photo.png",
            ...     detail="high",
            ... )
            >>> print(response)
            'The image shows a cat sitting on a chair...'
        """
        if not image_source or not isinstance(image_source, str):
            raise ValueError("image_source must be a non-empty string")

        image_source = image_source.strip()

        # Handle relative paths
        if image_source[0] not in ["/", "h"]:
            abs_path = os.path.abspath(image_source)
            if os.path.exists(abs_path):
                image_source = abs_path

        if not message:
            message = DEFAULT_IMAGE_PROMPT

        # Build content items: text + image
        content_items = [TextContent(message)]
        content_items.append(ImageContent(image_source, detail=detail))

        # Add to prompt controller
        self.prompt_ctl.add_user_message(text="", media_items=content_items)

        # Send to LLM
        answer = self.llm_model.chat_with_prompt(self.prompt_ctl, for_raw=True, for_stream=False)
        if answer:
            answer = str(answer).strip()
        self.prompt_ctl.add_assistant_message(answer)
        self.last_message = answer
        return answer

    def chat_with_media(
        self,
        message: str = "",
        media_items: Optional[list] = None,
    ) -> str:
        """
        Send a message with arbitrary media content to the LLM.

        Args:
            message (str): The text prompt.
            media_items (list, optional): List of ContentItem objects (ImageContent,
                VideoContent, AudioContent). Defaults to None.

        Returns:
            str: The LLM's response content.
        """
        if not message and not media_items:
            raise ValueError("Either message or media_items must be provided")

        self.prompt_ctl.add_user_message(text=message or "", media_items=media_items)

        answer = self.llm_model.chat_with_prompt(self.prompt_ctl, for_raw=True, for_stream=False)
        if answer:
            answer = str(answer).strip()
        self.prompt_ctl.add_assistant_message(answer)
        self.last_message = answer
        return answer

    def chat_with_content(
        self,
        message: str = "",
        content=None,
    ) -> str:
        """
        Send a message with a single content item to the LLM.

        Args:
            message (str): The text prompt.
            content (ContentItem): A single ContentItem object (ImageContent,
                VideoContent, AudioContent, etc.).

        Returns:
            str: The LLM's response content.
        """
        if not content:
            raise ValueError("content must be provided")

        content_items = []
        if message:
            content_items.append(TextContent(message))
        content_items.append(content)

        self.prompt_ctl.add_user_message(text="", media_items=content_items)

        answer = self.llm_model.chat_with_prompt(self.prompt_ctl, for_raw=True, for_stream=False)
        if answer:
            answer = str(answer).strip()
        self.prompt_ctl.add_assistant_message(answer)
        self.last_message = answer
        return answer


def get_multimodal_llm_chat(
    message: str = None,
    system_prompt: str = "",
    max_tokens: int = 4000,
    temperature: float = 0.3,
    need_stdout: bool = True,
    need_input_message: bool = False,
    need_print_session: bool = False,
    need_print_message: bool = False,
) -> MultimodalLLMChat:
    """
    Create and return a MultimodalLLMChat instance.

    Factory function for creating a multimodal chat session. Unlike the
    standard get_llm_chat(), this does not manage session persistence
    since multimodal chats are typically one-shot interactions.

    Args:
        message (str, optional): Initial message. If None and need_input_message
            is True, will prompt for input.
        system_prompt (str, optional): System prompt for the LLM.
            Defaults to DEFAULT_MULTIMODAL_SYSTEM_PROMPT if empty.
        max_tokens (int, optional): Maximum tokens in response. Defaults to 4000.
        temperature (float, optional): Sampling temperature. Defaults to 0.3.
        need_stdout (bool, optional): Enable stdout content sending. Defaults to True.
        need_input_message (bool, optional): Prompt for user input if message
            is not provided. Defaults to False.
        need_print_session (bool, optional): Print session info. Defaults to False.
        need_print_message (bool, optional): Print messages before sending.
            Defaults to False.

    Returns:
        MultimodalLLMChat: An initialized multimodal chat instance.

    Example:
        >>> chat = get_multimodal_llm_chat(
        ...     system_prompt="You are a vision expert.",
        ... )
        >>> response = chat.chat_with_image("Describe this", "image.png")
    """
    # Handle input message
    if not message and need_input_message:
        from topsailai.workspace.input_tool import get_message
        message = get_message(need_input=True)

    if not message:
        message = env_tool.EnvReaderInstance.read_file_or_content("TOPSAILAI_USER_MESSAGE")
        os.environ["TOPSAILAI_USER_MESSAGE"] = ""

    if need_print_session:
        logger.info("Creating multimodal LLM chat instance")

    # System prompt
    if not system_prompt:
        system_prompt = os.getenv("SYSTEM_PROMPT") or DEFAULT_MULTIMODAL_SYSTEM_PROMPT

    # Create LLM model
    llm_model = MultimodalLLMModel()
    if need_stdout:
        llm_model.content_senders.append(ContentStdout())
    llm_model.max_tokens = max(3000, max_tokens, llm_model.max_tokens)
    llm_model.temperature = max(0.3, temperature, llm_model.temperature)

    # Create prompt controller
    prompt_ctl = MultimodalPromptBase(system_prompt)
    if message:
        prompt_ctl.add_user_message(message, need_print=need_print_message)

    # Create chat instance
    chat = MultimodalLLMChat(prompt_ctl, llm_model)
    if message:
        chat.first_message = message

    return chat
