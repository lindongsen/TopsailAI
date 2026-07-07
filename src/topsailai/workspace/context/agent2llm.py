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
    print_info,
    print_error,
    print_critical,
)
from topsailai.utils import (
    json_tool,
    env_tool,
)
from topsailai.context.tool_stat import (
    get_agent_tool_stat,
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
        self.ai_agent.messages = self.ai_agent.messages[:first_position] + new_messages
        return deleted_list


    def summarize_messages_for_processing(
            self,
            messages: list | str = None,
            head_offset_to_keep: int = None,
        ) -> str | None:
        """
        Summarize messages into a single text for processing.

        Final message structure after summarization (no duplicates):
            head_portion + head_offset + tail_offset + [summary_answer] + [last_user_message]

        In plain terms: preserve the original head and tail messages first,
        then add the summary answer, then the last user message. Duplicates
        are skipped. ``head_portion`` and ``head_offset`` are often spoken of
        together as "head"; the same applies to ``tail_portion`` and
        ``tail_offset`` as "tail".

        - head_portion: messages from the beginning up to and including the
          first role=user, step_name=task message. It is held in the local
          variable `keeping_messages` (formerly `task_messages`).
        - head_offset: the first `head_offset_to_keep` messages kept verbatim.
        - tail_offset: the last `tail_offset_to_keep` messages kept verbatim.
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

        # if need keep session messages, user2agent session
        need_session_messages = env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES", True)
        session_msg_len = len(self.messages)

        if need_session_messages and session_msg_len > 0:
            # Prefer the Agent2LLM-specific threshold, fall back to the legacy shared threshold.
            ctx_quantity_threshold = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD", formatter=int)
            if not ctx_quantity_threshold or ctx_quantity_threshold <= 0:
                ctx_quantity_threshold = env_tool.EnvReaderInstance.get(
                    "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD", default=100, formatter=int) or 100

            session_max_ratio = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO",
                default=0.5,
                formatter=float,
            )
            if session_max_ratio is None or session_max_ratio <= 0 or session_max_ratio > 1:
                logger.warning("invalid TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO [%s], using default 0.5", session_max_ratio)
                session_max_ratio = 0.5

            if session_msg_len >= int(ctx_quantity_threshold * session_max_ratio):
                need_session_messages = False
                logger.warning("summary step cannot keep session messages due to it is too long: [%s]", session_msg_len)

        # When session messages are kept, count them toward the "too short" guard
        # so that the MIN_EXTRA_MESSAGES check can decide whether summarizing is worthwhile.
        total_len = msg_len
        if need_session_messages:
            total_len += session_msg_len

        if total_len <= 2:
            print_error(f"!!! [Agent2LLM] [Summarization] no need summarize due to messages too short: [{total_len}]")
            return None

        if need_session_messages:
            # the messages too short
            min_extra_messages = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES",
                default=17,
                formatter=int,
            )
            if min_extra_messages is None or min_extra_messages < 0:
                logger.warning("invalid TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES [%s], using default 17", min_extra_messages)
                min_extra_messages = 17
            if msg_len < (session_msg_len + min_extra_messages):
                print_info(f"!!! [Agent2LLM] [Summarization] no need summarize due to messages too short: [{msg_len}]")
                return None

        # print info
        print_info(f"!!! [Agent2LLM] [Summarization] Summarizing context messages for processing: msg_len=[{len(messages)}]")

        # Preserve task messages (role=user, step_name=task) from summarization/deletion.
        original_messages = list(messages)
        keeping_messages = self._get_messages_before_first_user_task_message(messages)
        print_info(f"!!! [Agent2LLM] [Summarization] head_messages_before_first_user_task_message_to_keep(session_messages)={len(keeping_messages)}")

        # Log message count and token usage before summarization
        _token_count_before = self._get_current_tokens()
        logger.info("[summarize_processing] before: messages=%s, tokens=%s", len(messages), _token_count_before)

        llm_chat, answer = self._summarize_messages(messages)
        if not answer:
            print_critical("!!! [Agent2LLM] [Summarization] NO ANSWER")
            return None

        # head_offset_to_keep
        head_offset_to_keep = self._get_head_offset_to_keep_in_summary(head_offset_to_keep)
        tail_offset_to_keep = self._get_tail_offset_to_keep_in_summary()

        # keep last user message
        # IMPORTANT DESIGN NOTE:
        # ``self.last_user_message`` intentionally reads from ``self.messages``
        # (the User2Agent persisted session layer), NOT from
        # ``self.ai_agent.messages`` (the Agent2LLM ephemeral ReAct context).
        # The message to preserve here is the most recent real human input to
        # the agent, not an internal tool observation or ReAct turn. This
        # ensures the summarized Agent2LLM context still ends with a clear
        # user prompt for the next LLM call.
        last_user_msg = self.last_user_message

        print_info(f"!!! [Agent2LLM] [Summarization] head_offset_to_keep={head_offset_to_keep}, tail_offset_to_keep={tail_offset_to_keep}, last_user_message_to_keep=1")

        # new messages: start with head_offset, then add session messages
        # if configured, then add tail_offset, then add summary answer, then
        # append last_user_message. The final structure is completed by merging
        # keeping_messages (head_portion) back in below.
        new_messages = messages[:head_offset_to_keep]

        # add session messages
        if need_session_messages:
            if not new_messages:
                # Note that they are different objects, so use '+=', DONOT use '='
                new_messages += self.messages
            else:
                _len = len(new_messages)
                for msg in self.messages:
                    if self._message_in_list(msg, new_messages[:_len]):
                        continue
                    new_messages.append(msg)

        # add tail_offset messages
        tail_messages = messages[-tail_offset_to_keep:] if tail_offset_to_keep > 0 else []
        for msg in tail_messages:
            if not self._message_in_list(msg, new_messages):
                new_messages.append(msg)

        # add answer(summary) to messages
        summary_answer = llm_chat.prompt_ctl.messages[-1]
        new_messages.append(summary_answer)

        # Re-insert the head_portion in chronological order so the final
        # list follows head_portion + tail_portion + [summary_answer] + [last_user_message].
        if keeping_messages:
            new_messages = self._merge_task_messages(original_messages, new_messages, keeping_messages)

        if last_user_msg:
            if not self._message_in_list(last_user_msg, new_messages):
                new_messages.append(last_user_msg)

        self._log_summarize_message_identity_changes(
            "summarize_messages_for_processing",
            original_messages,
            new_messages,
            summary_answer,
        )
        self.ai_agent.messages = self.ai_agent.messages[:index] + new_messages

        self.ai_agent.llm_model.tokenStat.add_msgs(self.ai_agent.messages)
        # Log message count and token usage after summarization
        _token_count_after = self._get_current_tokens(realtime=True)
        logger.info("[summarize_processing] after: messages=%s, tokens=%s", len(self.ai_agent.messages), _token_count_after)
        self._check_summarize_token_reduction(
            "summarize_messages_for_processing",
            _token_count_before,
            _token_count_after,
        )

        print_info(f"!!! [Agent2LLM] [Summarization] New context messages for processing: msg_len=[{len(self.ai_agent.messages)}]")
        logger.info("new context messages: %s", self.ai_agent.messages)
        return answer

    def is_need_summarize_for_processing(self) -> bool:
        """
        Check if messages need to be summarized based on quantity, token, or
        consecutive duplicate tool call threshold.

        Determines whether the current message count exceeds the configured quantity
        threshold, whether the current Agent2LLM token usage exceeds the configured
        token threshold, or whether the agent's consecutive duplicate tool call count
        exceeds the configured duplicate threshold, and requires summarization for
        efficient processing.

        Returns:
            bool: True if summarization is needed, False otherwise.
        """
        quantity_threshold = self._get_quantity_threshold(
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD"
        )
        if quantity_threshold:
            # Agent2LLM uses a larger candidate pool than User2Agent because
            # this layer represents the agent actively working: a single human
            # task can trigger many agent-to-LLM turns. A higher/different
            # distribution avoids summarizing too aggressively in the middle of
            # active task execution, while still respecting the configured floor.
            number_list = [23, 27, 29, 31, 37, 41, 43, 47]  # min -> max
            if quantity_threshold >= number_list[0]:
                number_list.append(quantity_threshold)
            if quantity_threshold * 2 <= number_list[-1]:
                number_list.append(quantity_threshold * 2)

            quantity_threshold = max(random.choice(number_list), quantity_threshold)
            if len(self.ai_agent.messages) >= quantity_threshold:
                print_info(
                    f"!!! [Agent2LLM] [Summarization] quantity_threshold exceeded: "
                    f"threshold=[{quantity_threshold}], current_messages=[{len(self.ai_agent.messages)}]"
                )
                return True

        token_threshold = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD",
            default=128000,
            formatter=int,
        ) or 0

        if token_threshold > 0:
            current_tokens = self._get_current_tokens() or 0

            if current_tokens > token_threshold:
                print_info(
                    f"!!! [Agent2LLM] [Summarization] token usage exceeded threshold: current_tokens=[{current_tokens}], threshold=[{token_threshold}]"
                )
                return True

        dup_threshold = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_AGENT2LLM_DUP_TOOL_CALL_SUMMARIZE_THRESHOLD",
            default=3,
            formatter=int,
        ) or 0

        if dup_threshold > 0:
            consecutive_count = self._get_consecutive_duplicate_count()
            if consecutive_count > dup_threshold:
                print_info(
                    f"!!! [Agent2LLM] [Summarization] consecutive duplicate tool calls exceeded: "
                    f"threshold=[{dup_threshold}], current_count=[{consecutive_count}]"
                )
                return True

        return False

    def _get_consecutive_duplicate_count(self) -> int:
        """
        Get the current consecutive duplicate tool call count from the agent.

        Resolves the agent's ToolStat instance, preferring the one attached to
        ``ai_agent.llm_model.tool_stat`` and falling back to ``ai_agent._tool_stat``.
        If no agent or ToolStat is available, returns ``0``.

        Returns:
            int: The current consecutive duplicate count, or ``0`` if unavailable.
        """
        if not self.ai_agent:
            return 0

        tool_stat = get_agent_tool_stat(self.ai_agent)
        if tool_stat is None:
            return 0

        try:
            return int(tool_stat.get_consecutive_duplicate_count())
        except Exception:
            return 0
