"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-06-14
  Purpose: Multimodal LLM model extending LLMModel to support content arrays.
"""

import copy
from typing import List, Union

from topsailai.ai_base.llm_base import LLMModel
from topsailai.logger.log_chat import logger

from .message import MultimodalMessage
from .prompt_base import MultimodalPromptBase


class MultimodalLLMModel(LLMModel):
    """
    Multimodal LLM model that supports content arrays for vision, video, and audio.

    Extends LLMModel to preserve content arrays (list of content item dicts)
    in message content. The parent's format_messages() expects string content
    and would fail on list content. This override uses temporary placeholders
    to safely delegate parameter building to the parent class.

    Content arrays follow the OpenAI vision API format:
        [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "...", "detail": "auto"}},
        ]

    Attributes:
        All attributes inherited from LLMModel and LLMModelBase.
    """

    def build_parameters_for_chat(self, messages, stream=False, tools=None, tool_choice="auto", **options):
        """
        Build parameters for the chat completion API call.

        Overrides the parent method to safely handle messages where content
        is a list (content array) instead of a string. List content messages
        are preserved by using temporary placeholders during parent processing,
        then restored in the final parameters.

        This approach delegates all parameter construction to the parent class,
        ensuring the multimodal version automatically inherits any future
        updates to the parent's parameter building logic.

        Args:
            messages (list): List of message dictionaries. Each message's 'content'
                can be either a string or a list of content item dicts.
            stream (bool, optional): Whether to stream the response. Defaults to False.
            tools (list, optional): List of tools available to the model. Defaults to None.
            tool_choice (str, optional): Tool choice strategy. Defaults to "auto".
            **options: Additional options for the API call.

        Returns:
            dict: Parameters dictionary for the chat completion API.
        """
        messages = copy.deepcopy(messages)

        # Execute pre-chat hook (preserved from original multimodal implementation)
        from topsailai.ai_base.llm_hooks.executor import hook_execute
        new_messages = hook_execute("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", messages)
        if new_messages:
            messages = new_messages

        # Preserve list content by replacing with safe placeholders.
        # Placeholders won't be modified by parent's format_messages()
        # because they don't start with '[' or '{' and don't contain
        # TOPSAILAI_FORMAT_PREFIX.
        list_content_map = {}
        for i, msg in enumerate(messages):
            content = msg.get("content")
            if isinstance(content, list):
                list_content_map[i] = content
                msg["content"] = f"__MULTIMODAL_CONTENT_PLACEHOLDER_{i}__"

        # Delegate parameter building to parent class.
        # Parent handles: format_messages, param dict construction,
        # stream_options, tools, tool_choice, parallel_tool_calls, etc.
        params = super().build_parameters_for_chat(messages, stream, tools, tool_choice, **options)

        # Restore original list content in the final parameters
        for i, original_content in list_content_map.items():
            params["messages"][i]["content"] = original_content

        return params

    def chat_with_content(
        self,
        multimodal_messages: List[Union[MultimodalMessage, dict]],
        for_raw: bool = True,
        for_stream: bool = False,
    ) -> str:
        """
        Send multimodal messages to the LLM and return the response.

        Accepts a list of MultimodalMessage objects or pre-converted dicts,
        converts them to the API format, and sends them to the LLM.

        Args:
            multimodal_messages (list): List of MultimodalMessage objects or dicts.
                Each item represents one message in the conversation.
            for_raw (bool, optional): If True, return raw content string.
                If False, return formatted response list. Defaults to True.
            for_stream (bool, optional): If True, use streaming mode.
                Defaults to False.

        Returns:
            str: The LLM's response content (when for_raw=True).
            list: Formatted response list (when for_raw=False).

        Raises:
            ValueError: If multimodal_messages is empty or contains invalid types.
            Exception: If the LLM chat fails after all retry attempts.

        Example:
            >>> from .message import MultimodalMessage, TextContent, ImageContent
            >>> msg = MultimodalMessage("user", [
            ...     TextContent("Describe this image"),
            ...     ImageContent("/path/to/image.png"),
            ... ])
            >>> response = model.chat_with_content([msg])
            >>> print(response)
            'The image shows...'
        """
        if not multimodal_messages:
            raise ValueError("multimodal_messages cannot be empty")

        # Convert MultimodalMessage objects to dicts, validating all elements
        messages = []
        for msg in multimodal_messages:
            if isinstance(msg, MultimodalMessage):
                messages.append(msg.to_dict())
            elif isinstance(msg, dict):
                messages.append(msg)
            else:
                raise ValueError(
                    f"multimodal_messages must contain MultimodalMessage objects or dicts, "
                    f"got {type(msg).__name__}"
                )

        logger.info("Sending multimodal chat with %d messages", len(messages))

        # Use the parent chat method which handles retries, error handling, etc.
        return self.chat(messages, for_raw=for_raw, for_stream=for_stream)

    def chat_with_prompt(
        self,
        prompt_ctl: MultimodalPromptBase,
        for_raw: bool = True,
        for_stream: bool = False,
    ) -> str:
        """
        Send messages from a MultimodalPromptBase to the LLM.

        Convenience method that extracts messages from a MultimodalPromptBase
        and sends them to the LLM.

        Args:
            prompt_ctl (MultimodalPromptBase): The prompt controller containing
                the conversation history.
            for_raw (bool, optional): If True, return raw content string.
                Defaults to True.
            for_stream (bool, optional): If True, use streaming mode.
                Defaults to False.

        Returns:
            str: The LLM's response content (when for_raw=True).
            list: Formatted response list (when for_raw=False).

        Example:
            >>> prompt = MultimodalPromptBase("You are a vision assistant.")
            >>> prompt.add_user_message("Describe this", [ImageContent("image.png")])
            >>> response = model.chat_with_prompt(prompt)
        """
        if not prompt_ctl:
            raise ValueError("prompt_ctl cannot be None")

        messages = prompt_ctl.to_dict_list()
        return self.chat_with_content(messages, for_raw=for_raw, for_stream=for_stream)
