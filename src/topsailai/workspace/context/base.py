"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
Purpose: Context runtime base module for managing chat sessions and message handling.
"""

import random

from topsailai.ai_base.constants import (
    ROLE_USER,
)
from topsailai.ai_base.agent_base import (
    AgentBase,
)
from topsailai.context import ctx_manager
from topsailai.tools import (
    story_tool,
)
from topsailai.utils import (
    json_tool,
    env_tool,
    file_tool,
)
from topsailai.workspace.llm_shell import get_llm_chat


class ContextRuntimeBase(object):
    """
    Context manager for runtime (session).

    Manages user chat sessions and maintains message history between users and agents.

    Variables:
        self.messages: User chats to agent in the current session.
        self.ai_agent.messages: Agent chats to LLM.
    """

    def __init__(self):
        """
        Initialize the ContextRuntimeBase instance.

        Sets up default values for session ID, messages list, and AI agent reference.
        """
        self.session_id = ""
        self.messages = []
        self.ai_agent: AgentBase = None

    @property
    def last_user_message(self):
        """
        Get the last user message from self.messages of current session.

        Returns:
            dict or None: The last message from ROLE_USER, or None if not found.
        """
        last_user_msg = None
        for msg in reversed(self.messages):
            msg_dict = json_tool.json_load(msg)
            if msg_dict["role"] == ROLE_USER:
                last_user_msg = msg
                break
        return last_user_msg

    def init(self, session_id: str, ai_agent: AgentBase):
        """
        Initialize the context runtime with session ID and AI agent.

        Args:
            session_id (str): Unique identifier for the session.
            ai_agent (AgentBase): The AI agent instance to use for processing.

        Returns:
            None
        """
        self.session_id = session_id
        self.ai_agent = ai_agent
        self.reset_messages()
        return

    def append_message(self, message: dict):
        """
        Append a message to the messages list.

        Args:
            message (dict): The message dictionary to append.

        Returns:
            None
        """
        if not message:
            return

        self.messages.append(message)

    def set_messages(self, value: list):
        """
        Set a new value for the messages list.

        Replaces all existing messages with the provided list.

        Args:
            value (list): New list of messages to set.

        Returns:
            None
        """
        if not value:
            value = []
        if value is self.messages:
            return
        self.messages.clear()
        self.messages += value
        return

    def reset_messages(self):
        """
        Reset messages to the newest from session storage.

        Retrieves messages from the session storage and updates the internal messages list.

        Returns:
            None
        """
        if self.session_id:
            messages_from_session = ctx_manager.get_messages_by_session(self.session_id) or []
            self.set_messages(messages_from_session)
        return

    ###############################################################
    # Env
    ###############################################################

    def _get_quantity_threshold(self) -> int:
        """
        Get the quantity threshold for message summarization.

        If the value is 0 or null, summarization is disabled.

        Returns:
            int: The quantity threshold value. Returns 0 if disabled.
        """
        env_quantity_threshold = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD",
            formatter=int,
        )
        # disabled
        if not env_quantity_threshold or env_quantity_threshold < 0:
            return 0

        number_list = [13, 17, 19, 23]
        quantity_threshold = max(random.choice(number_list), env_quantity_threshold)
        return quantity_threshold

    def _get_head_offset_to_keep_in_summary(
            self,
            head_offset_to_keep: int = None,
        ) -> int:
        """
        Get the head offset to keep in summary.

        Args:
            head_offset_to_keep (int, optional): If provided, use this value directly.
                If None, retrieve from environment variable.

        Returns:
            int: The head offset value to keep in summary. Always returns non-negative value.
        """
        if head_offset_to_keep is None:
            head_offset_to_keep = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP",
                default=0,
                formatter=int
            ) or 0

        if head_offset_to_keep < 0:
            head_offset_to_keep = 0

        return head_offset_to_keep

    ###############################################################
    # Summary
    ###############################################################

    def _summarize_messages(self, messages, prompt: str = None):
        """
        Summarize messages into a single text using LLM.

        Args:
            messages: The messages to summarize. Can be a string or list/dict.
            prompt (str, optional): Custom prompt for summarization. If None, uses
                default from environment variable.

        Returns:
            tuple: A tuple containing (llm_chat, answer) where:
                - llm_chat: The LLM chat instance used for summarization
                - answer (str): The summarized text response from LLM

        Raises:
            AssertionError: If messages is null/empty.
        """
        assert messages, "null of messages"
        one_msg = messages if isinstance(messages, str) else json_tool.json_dump(messages)
        enhanced_prompt = "\n---\nYou MUST focus on the Human's intention\n---\n\n"

        # prompt
        if prompt is None:
            prompt = env_tool.EnvReaderInstance.get("TOPSAILAI_SUMMARY_PROMPT")
        _, prompt_content = file_tool.get_file_content_fuzzy(prompt)
        if not prompt_content:
            prompt_content = ""

        llm_chat = get_llm_chat(
            message=enhanced_prompt + one_msg,
            session_id="",
            system_prompt=story_tool.PROMPT_SUMMARY + prompt_content,

            need_stdout=False,
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        answer = llm_chat.chat(need_print=False)

        return (llm_chat, answer)
