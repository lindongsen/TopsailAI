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
)
from topsailai.utils.print_tool import print_step
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
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

        del self.messages[index]

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

        This method compresses the conversation history by summarizing
        older messages while preserving the most recent messages. It can
        operate in interactive mode to prompt the user for confirmation.

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
        if not messages:
            # just the processed Q&A messages for current runtime
            messages = self.messages

        if not messages:
            return None

        # print info
        print_step(f"!!! Summarizing context messages for processed: msg_len=[{len(messages)}]", need_format=False, need_log=True)

        llm_chat, answer = self._summarize_messages(messages)
        if not answer:
            return None

        if need_interactive:
            try:
                print(SPLIT_LINE)
                while True:
                    yn = input(">>> Is this answer acceptable? [yes/no] ").lower().strip()
                    if not yn:
                        continue
                    if yn != "yes":
                        return answer
                    break
            except Exception:
                return answer

        # head_offset_to_keep
        head_offset_to_keep = self._get_head_offset_to_keep_in_summary(head_offset_to_keep)

        if self.session_id:
            raw_messages_from_session = ctx_manager.get_messages_by_session(self.session_id, for_raw=True)

            # keep last user message
            last_user_raw_msg = None
            for raw_msg in reversed(raw_messages_from_session):
                msg_dict = json_tool.json_load(raw_msg.message)
                if msg_dict["role"] == ROLE_USER:
                    last_user_raw_msg = raw_msg
                    break

            # delete history messages
            if raw_messages_from_session:
                for raw_msg in raw_messages_from_session[head_offset_to_keep:]:
                    if last_user_raw_msg and raw_msg.msg_id == last_user_raw_msg.msg_id:
                        continue
                    ctx_manager.del_session_messages(self.session_id, [raw_msg.msg_id])
            else:
                logger.critical("BUG: how did it happend? null of messages from session: [%s]", self.session_id)

            # add answer to session
            ctx_manager.add_session_message(self.session_id, llm_chat.prompt_ctl.messages[-1])

            # reset messages
            self.reset_messages()
        else:
            # keep last user message
            last_user_msg = self.last_user_message

            # new messages
            new_messages = messages[:head_offset_to_keep]
            new_messages.append(llm_chat.prompt_ctl.messages[-1]) # add answer(summary) to messages
            if last_user_msg:
                new_messages.append(last_user_msg)

            self.set_messages(new_messages)

        return answer


    def is_need_summarize_for_processed(self) -> bool:
        """
        Check if the processed messages need to be summarized.

        Determines whether the current message quantity has exceeded
        the threshold that triggers message summarization. This helps
        manage memory and context window limitations.

        Returns:
            bool: True if the number of messages exceeds the quantity
                  threshold and summarization is needed, False otherwise.

        Example:
            >>> if runtime.is_need_summarize_for_processed():
            ...     runtime.summarize_messages_for_processed()
        """
        quantity_threshold = self._get_quantity_threshold()
        if not quantity_threshold:
            return False

        if len(self.messages) >= quantity_threshold:
            return True

        return False
