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
    env_tool,
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

        Final message structure after summarization:
            head_portion + [summary_answer] + [last_user_message]

        - head_portion: messages from the beginning up to and including the
          first role=user, step_name=task message. It is held in the local
          variable `keeping_messages` (formerly `task_messages`).
        - summary_answer: exactly one assistant message produced by the LLM.
        - last_user_message: exactly one final user message kept at the tail.

        The summarizer receives the current runtime messages. In the default
        "runtime" summary mode the LLM is fed from self.ai_agent.messages, so
        the wrapper argument is the runtime messages while the actual summary
        context is the full Agent2LLM history.

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

        msg_len = len(messages)

        if msg_len <= 2:
            logger.warning("no need summarize due to messages too short: [%s]", msg_len)
            return None

        # if need keep session messages, user2agent session
        need_session_messages = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES", True)

        session_msg_len = len(self.messages)
        if need_session_messages:
            # Prefer the Agent2LLM-specific threshold, fall back to the legacy shared threshold.
            ctx_quantity_threshold = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD", formatter=int)
            if not ctx_quantity_threshold or ctx_quantity_threshold <= 0:
                ctx_quantity_threshold = env_tool.EnvReaderInstance.get(
                    "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD", default=100, formatter=int) or 100
            if session_msg_len >= int(ctx_quantity_threshold / 2):
                need_session_messages = False
                logger.warning("summary step cannot keep session messages due to it is too long: [%s]", session_msg_len)

        if need_session_messages:
            # the messages too short
            if msg_len < (session_msg_len + 17):
                logger.info("no need summarize due to messages too short: [%s]", msg_len)
                return None

        # print info
        print_step(f"!!! Summarizing context messages for processing: msg_len=[{len(messages)}]", need_format=False, need_log=True)

        # Preserve task messages (role=user, step_name=task) from summarization/deletion.
        original_messages = list(messages)
        keeping_messages = self._get_messages_before_first_user_task_message(messages)
        print_step(f"!!! head_messages_before_first_user_task_message_to_keep(session_messages)={len(keeping_messages)}", need_format=False, need_log=True)

        # Log message count and token usage before summarization
        _token_count_before = self._get_current_tokens()
        logger.info("[summarize_processing] before: messages=%s, tokens=%s", len(messages), _token_count_before)

        llm_chat, answer = self._summarize_messages(messages)
        if not answer:
            return None

        # head_offset_to_keep
        head_offset_to_keep = self._get_head_offset_to_keep_in_summary(head_offset_to_keep)

        # keep last user message
        last_user_msg = self.last_user_message

        print_step(f"!!! head_offset_to_keep={head_offset_to_keep}, last_user_message_to_keep=1", need_format=False, need_log=True)

        # new messages: start with head_offset, then add session messages
        # if configured, then add summary answer, then append last_user_message.
        # The final structure is completed by merging keeping_messages
        # (head_portion) back in below.
        new_messages = messages[:head_offset_to_keep]

        # add session messages
        if need_session_messages:
            if not new_messages:
                # Note that they are different objects, so use '+=', DONOT use '='
                new_messages += self.messages
            else:
                _len = len(new_messages)
                for msg in self.messages:
                    if msg in new_messages[:_len]:
                        continue
                    new_messages.append(msg)

        # add answer(summary) to messages
        new_messages.append(llm_chat.prompt_ctl.messages[-1])

        if last_user_msg:
            if last_user_msg not in new_messages:
                new_messages.append(last_user_msg)

        # Re-insert the head_portion in chronological order so the final
        # list follows head_portion + [summary_answer] + [last_user_message].
        if keeping_messages:
            new_messages = self._merge_task_messages(original_messages, new_messages, keeping_messages)
        self.ai_agent.messages = self.ai_agent.messages[:index] + new_messages

        self.ai_agent.llm_model.tokenStat.add_msgs(self.ai_agent.messages)
        # Log message count and token usage after summarization
        _token_count_after = self._get_current_tokens(realtime=True)
        logger.info("[summarize_processing] after: messages=%s, tokens=%s", len(self.ai_agent.messages), _token_count_after)

        print_step(f"!!! New context messages for processing: msg_len=[{len(self.ai_agent.messages)}]", need_format=False, need_log=True)
        logger.info("new context messages: %s", self.ai_agent.messages)
        return answer

    def is_need_summarize_for_processing(self) -> bool:
        """
        Check if messages need to be summarized based on quantity or token threshold.

        Determines whether the current message count exceeds the configured quantity
        threshold, or whether the current Agent2LLM token usage exceeds the configured
        token threshold, and requires summarization for efficient processing.

        Returns:
            bool: True if summarization is needed, False otherwise.
        """
        quantity_threshold = self._get_quantity_threshold("TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD")
        if quantity_threshold:
            number_list = [23, 27, 29, 31, 37, 41, 43, 47]  # min -> max
            if quantity_threshold >= number_list[0]:
                number_list.append(quantity_threshold)
            if quantity_threshold * 2 <= number_list[-1]:
                number_list.append(quantity_threshold * 2)

            quantity_threshold = max(random.choice(number_list), quantity_threshold)

            if len(self.ai_agent.messages) >= quantity_threshold:
                return True

        token_threshold = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD",
            default=128000,
            formatter=int,
        ) or 0

        if token_threshold > 0:
            current_tokens = self._get_current_tokens() or 0

            if current_tokens > token_threshold:
                print_step(
                    f"!!! Agent2LLM token usage exceeded threshold: current_tokens=[{current_tokens}], threshold=[{token_threshold}]",
                    need_format=False,
                    need_log=True,
                )
                return True

        return False
