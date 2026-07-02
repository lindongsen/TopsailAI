"""
Context Runtime Module.

This module provides runtime context management for user sessions and AI agent interactions.
It handles message storage, retrieval, deletion, and summarization for conversation contexts.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-21

Purpose:
    UserSession -> ctx_runtime_data.messages -> user chats to agent
    AgentSession -> ctx_runtime_aiagent.messages -> agent chats to LLM
"""

from topsailai.logger import logger
from topsailai.ai_base.constants import (
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
)

from topsailai.context import ctx_manager
from topsailai.utils import (
    json_tool,
    env_tool,
)
from topsailai.utils.print_tool import (
    print_step,
    print_critical,
    print_info,
)
from topsailai.tools import (
    story_tool,
    story_memory_tool,
)
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
    input_one_line,
)
from topsailai.workspace.context.agent2llm import (
    ContextRuntimeAgent2LLM,
)


class ContextRuntimeData(ContextRuntimeAgent2LLM):
    """
    Context manager for runtime data storage and manipulation.

    This class manages conversation messages between users and agents,
    providing methods to add, delete, and summarize messages. It maintains
    two message stores:
        - self.messages: messages from user chats to agent
        - self.ai_agent.messages: messages from agent chats to LLM

    Attributes:
        session_id: The current session identifier
        messages: List of message dictionaries with 'role' and 'content' keys
    """

    ###############################################################
    # User chats to Agent
    ###############################################################

    def add_session_message(self, role: str, message: str):
        """
        Add a message to the current session.

        Appends a new message to the session's message list and persists
        it to the context manager if a session_id is available.

        Args:
            role (str): The role of the message sender (e.g., 'user', 'assistant', 'system')
            message (str): The content of the message

        Returns:
            None

        Example:
            >>> runtime.add_session_message("user", "Hello, how are you?")
        """
        msg_dict = {"role": role or ROLE_ASSISTANT, "content": message}

        self.add_session_message_dict(msg_dict)

        return

    def add_session_message_dict(self, message:dict):
        assert isinstance(message, dict)
        self.append_message(message)
        if self.session_id:
            ctx_manager.add_session_message(
                self.session_id, message
            )
        return

    def del_session_message_by_ids(self, *msg_ids: list[str]):
        """
        Delete a single message from the session by message ID.

        Args:
            msg_ids (list_str)
        """
        session_id = self.session_id
        if session_id:
            ctx_manager.del_session_messages(session_id, msg_ids)
        return

    def del_session_message(self, index: int):
        """
        Delete a single message from the session by index.

        Removes a message at the specified index from both the local
        message list and the context manager (if session_id exists).

        Args:
            index (int): Sequence number of the message to delete, starting from 0

        Raises:
            AssertionError: If index is out of valid range

        Returns:
            None
        """
        session_id = self.session_id

        index = int(index)
        assert index >= 0 and index < len(self.messages), "nothing can be deleted"

        if session_id:
            raw_msgs = ctx_manager.get_messages_by_session(session_id, for_raw=True)
            index_msg = raw_msgs[index]
            index_msg_id = index_msg.msg_id
            ctx_manager.del_session_messages(session_id, [index_msg_id])

        self.delete_message(index)

        return

    # user chats to agent
    def del_session_messages(self, indexes: list[int]) -> list[int]:
        """
        Delete multiple messages from the session by their indexes.

        Removes messages at the specified indexes from the session,
        filtering out system messages. Only deletes non-system messages
        that are in the provided indexes list.

        Args:
            indexes (list[int]): List of sequence numbers of messages to delete,
                                starting from 0

        Returns:
            list[int]: List of indexes that were successfully deleted

        Example:
            >>> deleted = runtime.del_session_messages([0, 2, 5])
            >>> print(deleted)  # [0, 2, 5]
        """
        if not indexes:
            return []

        deleted_list = []

        new_messages = []
        for i, msg in enumerate(self.messages):
            new_messages.append(msg)
            msg_dict = json_tool.json_load(msg)
            if msg_dict["role"] == ROLE_SYSTEM:
                continue
            if i not in indexes:
                continue
            deleted_list.append(i)
            new_messages.pop()

        if not deleted_list:
            return []

        self.set_messages(new_messages)

        if self.session_id:
            raw_msgs = ctx_manager.get_messages_by_session(self.session_id, for_raw=True)
            msg_ids = []
            raw_msgs_len = len(raw_msgs)
            for i in deleted_list:
                if i >= raw_msgs_len:
                    continue
                msg_ids.append(raw_msgs[i].msg_id)
            if msg_ids:
                ctx_manager.del_session_messages(self.session_id, msg_ids)

        return deleted_list


    def summarize_messages_for_processed(
            self,
            messages: list = None,
            head_offset_to_keep: int = None,
            need_interactive: bool = False,
        ) -> str | None:
        """
        Summarize the processed conversation messages into a single text.

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

        Args:
            messages (list, optional): List of messages to summarize.
                                      Defaults to self.messages if None.
            head_offset_to_keep (int, optional): Number of recent messages
                                                 to keep unsummarized.
                                                 If None, uses default threshold.
            need_interactive (bool): If True, prompts user to confirm
                                     the summarized answer. Defaults to False.

        Returns:
            str | None: The summarized text if successful, None otherwise.
                        Returns None if there are no messages to summarize
                        or if summarization fails.

        Example:
            >>> summary = runtime.summarize_messages_for_processed(
            ...     head_offset_to_keep=5,
            ...     need_interactive=True
            ... )
        """
        raw_messages_from_session = []

        if not messages:
            # check again
            if self.session_id:
                self.reset_messages()
                if not self.is_need_summarize_for_processed():
                    print_info(f"!!! [User2Agent] [Summarization] No need summarize, current msg_len=[{len(self.messages)}]")
                    return None

            # just the processed Q&A messages for current runtime
            messages = self.messages

        if not messages:
            return None

        # Build the head_portion: messages from the beginning up to and
        # including the first role=user, step_name=task message. This is
        # stored in keeping_messages and later merged back so the final
        # structure remains head_portion + [summary_answer] + [last_user_message].
        original_messages = list(messages)
        keeping_messages = self._get_messages_before_first_user_task_message(messages)
        print_step(f"!!! [User2Agent] [Summarization] head_messages_before_first_user_task_message_to_keep(session_messages)={len(keeping_messages)}", need_format=False, need_log=True)

        # print info
        print_step(f"!!! [User2Agent] [Summarization] Summarizing context messages for processed: msg_len=[{len(messages)}]", need_format=False, need_log=True)

        # Log message count and token usage before summarization
        _token_count_before = self._get_current_tokens(realtime=True)
        logger.info("[summarize_processed] before: messages=%s, tokens=%s", len(messages), _token_count_before)

        # The summarizer is called with the current runtime messages. In
        # runtime mode the LLM actually consumes self.messages, but the
        # wrapper-level contract is to pass the runtime messages.
        llm_chat, answer = self._summarize_messages(messages, extra_prompt=story_tool.PROMPT_SUMMARY_MEMORY)
        if not answer:
            print_critical("!!! [User2Agent] [Summarization] NO ANSWER")
            return None

        if need_interactive:
            try:
                print(SPLIT_LINE)
                while True:
                    yn = input_one_line(">>> Is this answer acceptable? [yes/no] ").lower().strip()
                    if not yn:
                        continue
                    if yn != "yes":
                        return answer
                    break
            except Exception:
                return answer

        # persistent memory with story
        # if story_memory_tool.WORKSPACE:
        #     story_file = story_memory_tool.write_memory(
        #         title=answer.split('\n', 1)[0],
        #         content=answer,
        #     )
        #     logger.info("new memory with story: [%s]", story_file)

        # head_offset_to_keep
        head_offset_to_keep = self._get_head_offset_to_keep_in_summary(head_offset_to_keep)
        if head_offset_to_keep and len(self.messages) <= head_offset_to_keep:
            head_offset_to_keep = 1

        # tail_offset_to_keep
        tail_offset_to_keep = self._get_tail_offset_to_keep_in_summary()

        print_step(f"!!! [User2Agent] [Summarization] head_offset_to_keep={head_offset_to_keep}, tail_offset_to_keep={tail_offset_to_keep}, last_user_message_to_keep=1", need_format=False, need_log=True)

        if self.session_id:
            raw_messages_from_session = ctx_manager.get_messages_by_session(self.session_id, for_raw=True)

            # add answer to session
            ctx_manager.add_session_message(self.session_id, llm_chat.prompt_ctl.messages[-1])

            # keep messages before first user task message
            raw_msg_ids_to_keep = []
            for i, raw_msg in enumerate(raw_messages_from_session):
                raw_msg_ids_to_keep.append(raw_msg.msg_id)
                if self._is_task_message(raw_msg.message):
                    break
                if i > 7:
                    break
            print_step(f"!!! [User2Agent] [Summarization] head_messages_before_first_user_task_message_to_keep(session_raw_messages)={len(raw_msg_ids_to_keep)}")

            # keep last user message
            last_user_raw_msg = None
            for raw_msg in reversed(raw_messages_from_session):
                msg_dict = json_tool.json_load(raw_msg.message)
                if msg_dict["role"] == ROLE_USER:
                    last_user_raw_msg = raw_msg
                    break

            # delete history messages
            if raw_messages_from_session:
                for raw_msg in raw_messages_from_session[head_offset_to_keep:max(len(raw_messages_from_session)-tail_offset_to_keep, head_offset_to_keep)]:
                    if last_user_raw_msg and raw_msg.msg_id == last_user_raw_msg.msg_id:
                        continue
                    if raw_msg_ids_to_keep and raw_msg.msg_id in raw_msg_ids_to_keep:
                        continue
                    ctx_manager.del_session_messages(self.session_id, [raw_msg.msg_id])
            else:
                logger.critical("BUG: how did it happend? null of messages from session: [%s]", self.session_id)

            # reset messages
            self.reset_messages()
        else:
            # keep last user message
            last_user_msg = self.last_user_message

            # new messages: start with head_offset, then add tail_offset,
            # then add summary answer. The final structure is completed by
            # merging keeping_messages (head_portion) back in below and then
            # appending last_user_message.
            new_messages = messages[:head_offset_to_keep]

            # add tail_offset messages
            tail_messages = messages[-tail_offset_to_keep:] if tail_offset_to_keep > 0 else []
            for msg in tail_messages:
                if msg not in new_messages:
                    new_messages.append(msg)

            # add answer(summary) to messages
            new_messages.append(llm_chat.prompt_ctl.messages[-1])

            # Re-insert the head_portion in chronological order so the final
            # list follows head_portion + tail_portion + [summary_answer] + [last_user_message].
            if keeping_messages:
                new_messages = self._merge_task_messages(original_messages, new_messages, keeping_messages)

            if last_user_msg:
                if last_user_msg not in new_messages:
                    new_messages.append(last_user_msg)

            self.set_messages(new_messages)

        # Log message count and token usage after summarization
        _token_count_after = self._get_current_tokens(realtime=True)
        logger.info("[summarize_processed] after: messages=%s, tokens=%s", len(self.messages), _token_count_after)
        self._check_summarize_token_reduction(
            "summarize_messages_for_processed",
            _token_count_before,
            _token_count_after,
        )
        return answer


    def is_need_summarize_for_processed(self) -> bool:
        """
        Check if the processed messages need to be summarized.

        Determines whether the current message quantity has exceeded
        the threshold that triggers message summarization, or whether
        the current User2Agent token usage exceeds the configured token
        threshold. This helps manage memory and context window limitations.

        Returns:
            bool: True if summarization is needed based on quantity or token
                  threshold, False otherwise.

        Example:
            >>> if runtime.is_need_summarize_for_processed():
            ...     runtime.summarize_messages_for_processed()
        """
        quantity_threshold = self._get_quantity_threshold(
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD"
        )
        if quantity_threshold:
            if len(self.messages) >= quantity_threshold:
                print_info(
                    f"!!! [User2Agent] [Summarization] quantity_threshold exceeded: "
                    f"threshold=[{quantity_threshold}], current_messages=[{len(self.messages)}]"
                )
                return True

        token_threshold = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD",
            default=0,
            formatter=int,
        ) or 0

        if token_threshold > 0:
            current_tokens = self._get_current_tokens(self.messages) or 0
            if current_tokens > token_threshold:
                print_step(
                    f"!!! [User2Agent] [Summarization] token usage exceeded threshold: current_tokens=[{current_tokens}], threshold=[{token_threshold}]",
                    need_format=False,
                    need_log=True,
                )
                return True

        return False
