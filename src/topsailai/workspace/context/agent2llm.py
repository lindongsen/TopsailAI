"""
Context runtime agent to LLM conversion module.

This module provides functionality for converting agent messages to LLM format
and managing message summarization for processing.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
Purpose: Handle agent-to-LLM message conversion and context summarization.
"""

import random

from topsailai.logger import logger
from topsailai.ai_base.constants import (
    ROLE_SYSTEM,
)
from topsailai.utils.print_tool import (
    print_step,
)
from topsailai.utils import (
    json_tool,
)
from topsailai.workspace.context.base import (
    ContextRuntimeBase,
)


class ContextRuntimeAgent2LLM(ContextRuntimeBase):
    """
    Agent chats to LLM.

    This class provides functionality for managing agent conversations with LLM,
    including message deletion, summarization, and processing threshold detection.
    """

    def del_agent_messages(self, indexes: list[int], to_del_last=False) -> list[int]:
        """
        Delete specific messages from the agent's message list.

        Args:
            indexes (list[int]): Sequence numbers of messages to delete, starting from 0.

        Returns:
            list[int]: List of successfully deleted message indexes.
        """
        if not indexes:
            return []

        first_position = self.ai_agent.get_work_memory_first_position()
        if first_position is None:
            return []

        new_messages = []
        deleted_list = []
        last_index = None
        for i, msg in enumerate(self.ai_agent.messages[first_position:]):
            last_index = i
            new_messages.append(msg)
            msg_dict = json_tool.json_load(msg)
            if msg_dict["role"] == ROLE_SYSTEM:
                continue
            if i not in indexes:
                continue
            deleted_list.append(i)
            new_messages.pop()

        if to_del_last:
            if last_index is not None and last_index not in indexes:
                new_messages.pop()

        if not deleted_list:
            return []
        self.ai_agent.messages = new_messages

        return deleted_list

    def summarize_messages_for_processing(
            self,
            messages: list | str = None,
            head_offset_to_keep: int = None,
        ) -> str | None:
        """
        Summarize messages into a single text for processing.

        Args:
            messages (list | str, optional): Messages to summarize. Defaults to None.
            head_offset_to_keep (int, optional): Number of recent messages to keep. Defaults to None.

        Returns:
            str | None: The summarized text, or None if summarization fails.
        """
        index = self.ai_agent.get_work_memory_first_position()
        if index is None:
            return None

        if not messages:
            messages = self.ai_agent.messages[index:]

        if not messages:
            return None

        # print info
        print_step(f"!!! Summarizing context messages for processing: msg_len=[{len(messages)}]", need_format=False, need_log=True)

        llm_chat, answer = self._summarize_messages(messages)
        if not answer:
            return None

        # head_offset_to_keep
        head_offset_to_keep = self._get_head_offset_to_keep_in_summary(head_offset_to_keep)

        # keep last user message
        last_user_msg = self.last_user_message

        # new messages
        new_messages = messages[:head_offset_to_keep]
        new_messages.append(llm_chat.prompt_ctl.messages[-1])  # add answer(summary) to messages
        if last_user_msg:
            new_messages.append(last_user_msg)
        self.ai_agent.messages = self.ai_agent.messages[:index] + new_messages

        print_step(f"!!! New context messages for processing: msg_len=[{len(self.ai_agent.messages)}]", need_format=False, need_log=True)
        logger.info("new context messages: %s", self.ai_agent.messages)

        return answer

    def is_need_summarize_for_processing(self) -> bool:
        """
        Check if messages need to be summarized based on quantity threshold.

        Determines whether the current message count exceeds the configured threshold
        and requires summarization for efficient processing.

        Returns:
            bool: True if summarization is needed, False otherwise.
        """
        quantity_threshold = self._get_quantity_threshold()
        if not quantity_threshold:
            return False

        number_list = [23, 27, 29, 31, 37, 41, 43, 47]  # min -> max
        if quantity_threshold >= number_list[0]:
            number_list.append(quantity_threshold)
        if quantity_threshold * 2 <= number_list[-1]:
            number_list.append(quantity_threshold * 2)

        quantity_threshold = max(random.choice(number_list), quantity_threshold)

        if len(self.ai_agent.messages) >= quantity_threshold:
            return True

        return False
