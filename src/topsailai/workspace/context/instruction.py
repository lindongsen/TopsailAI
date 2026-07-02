"""
Context runtime instructions module.

This module provides instruction handlers for managing context messages
in the TopsailAI workspace, including operations like clearing, viewing,
deleting, and summarizing messages.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
"""

from topsailai.ai_base.constants import (
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_TOOL,
    STEP_NAME_OBSERVATION,
    MSG_KEY_STEP_NAME,
    MSG_KEY_RAW_TEXT,
)
from topsailai.utils import (
    json_tool,
)
from topsailai.context import ctx_manager
from topsailai.tools.agent_tool import (
    subprocess_agent_memory_as_story,
)
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)
from topsailai.workspace.print_tool import (
    print_context_messages,
    print_raw_messages,
)
from topsailai.workspace.context.agent import ContextRuntimeUtils


class ContextRuntimeInstructions(ContextRuntimeUtils):
    """
    Instructions handler for human interaction with context messages.

    This class provides methods to manage context messages including
    clearing, viewing history, deleting messages, and summarizing.
    Inherits utility methods from ContextRuntimeUtils.
    """

    @property
    def instructions(self) -> dict:
        """
        Get the dictionary of available instruction methods.

        Returns:
            dict: A dictionary mapping instruction names to their
                  corresponding methods.
        """

        # context messages
        ctx_map = {
            "ctx.clear": self.ctx_clear,
            "ctx.story": self.ctx_story,
            "ctx.history": self.ctx_history,
            "ctx.history2": self.ctx_history2,
            "ctx.del_msg": self.ctx_delete_message,
            "ctx.del_msgs": self.ctx_delete_messages,
            "ctx.del_msg_ids": self.ctx_runtime_data.del_session_message_by_ids,
            "ctx.summarize": self.ctx_summarize,
            "ctx.search": self.ctx_search,
            "ctx.add_agent2llm": self.ctx_add_agent2llm_message,
        }

        # total
        instructions = {}
        instructions.update(ctx_map)

        # result
        return instructions

    ##############################################################################
    # Context, ctx
    ##############################################################################
    def ctx_refresh(self):
        """
        Refresh context messages
        """
        if self.session_id:
            self.ctx_runtime_data.reset_messages()
        return

    def ctx_clear(self):
        """
        Clear all context messages for the current session.

        Clears the context messages if no session ID exists.
        If a session ID is present, displays a message indicating
        that clearing is not possible due to the active session.

        Returns:
            None
        """
        session_id = self.session_id

        if session_id:
            print(f"Context cannot be clear due to exist session_id({session_id})")
        else:
            # clear context messages
            self.ctx_runtime_data.clear_messages()
            print("Context already is clear")
        return

    def ctx_story(self):
        """
        Save context messages to a new story.

        Saves the current context messages to a new story using
        subprocess agent. Only executes if there are existing
        messages in the session.

        Returns:
            None
        """
        if not self.messages:
            return
        pid = subprocess_agent_memory_as_story(self.messages)
        print(f"The history messages will be save to a new story, pid=[{pid}], msg_len=[{len(self.messages)}]")
        return

    def ctx_history(self, offset:str=""):
        """
        Display the history of messages for the current session.

        Shows all context messages with an optional offset to display
        a subset of messages. A separator line is printed before
        the messages.

        Args:
            offset (str, optional): Offset specification for message range.
                - Usage 1: Single number, e.g., "7" displays 7:-7
                - Usage 2: Range format "head_num:tail_num", e.g., "5:-3"
                Defaults to empty string, which displays all messages.

        Returns:
            None
        """
        self.ctx_refresh()
        session_id = self.session_id

        print(f"\n\n{SPLIT_LINE}")
        print(f"Show history messages {session_id}")
        if self.messages:
            head_offset = None
            tail_offset = None
            if offset:
                try:
                    if ':' in offset:
                        head_offset, tail_offset = offset.split(':', 1)
                        head_offset = int(head_offset)
                        tail_offset = int(tail_offset)
                    else:
                        head_offset = tail_offset = int(offset)
                        tail_offset = -tail_offset
                except Exception:
                    pass

            _msgs = self.messages if head_offset is None else self.messages[head_offset:tail_offset]
            print_context_messages(_msgs)

        return

    def ctx_history2(self):
        """
        Display raw history messages for the current session.

        Prints the raw (unprocessed) context messages for the
        current session, useful for debugging or detailed inspection.

        Returns:
            None
        """
        session_id = self.session_id

        print(f"\n\n{SPLIT_LINE}")
        print(f"Show raw history messages {session_id}")
        raw_msgs = ctx_manager.get_messages_by_session(session_id, for_raw=True)
        if raw_msgs:
            print_raw_messages(raw_msgs)
        return

    def ctx_add_agent2llm_message(self, content: str, role: str = ROLE_USER):
        """
        Add a message to the Agent2LLM ephemeral message context.

        This instruction injects a message directly into the agent's internal
        ReAct conversation context (``self.ai_agent.messages``). The content is
        wrapped as an observation string so it is treated like a runtime
        observation payload by downstream consumers.

        Args:
            content (str): Raw message content. This becomes the ``raw_text``
                of an observation content block.
            role (str, optional): Message role. Must be one of "system", "user",
                "assistant", or "tool". Defaults to "user".

        Returns:
            str: A concise confirmation message.
        """
        valid_roles = {ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL}
        role = (role or "").strip().lower()
        if role not in valid_roles:
            return f"invalid role [{role}], must be one of {sorted(valid_roles)}"

        if not self.ai_agent:
            return "no active agent, cannot add Agent2LLM message"

        if self.ai_agent.messages is None:
            self.ai_agent.messages = []

        observation_content = {
            MSG_KEY_STEP_NAME: STEP_NAME_OBSERVATION,
            MSG_KEY_RAW_TEXT: content,
        }
        message = {
            "role": role,
            "content": json_tool.json_dump(observation_content),
        }
        # Append via the controlled mutator convention for the Agent2LLM layer:
        # use ``+=`` on the existing list rather than replacing the reference.
        # The message itself is a dict (not a JSON string), consistent with
        # PromptBase message conventions.
        self.ai_agent.messages += [message]
        return f"added 1 {role} message to Agent2LLM context (total={len(self.ai_agent.messages)})"

    def ctx_delete_message(self, index:int):
        """
        Delete a single message by its index.

        Removes a message at the specified index (1-based) from
        the context messages and refreshes the history display.

        Args:
            index (int): Sequence number of the message to delete,
                         starting from 1.
        Raises:
            AssertionError: If index is out of valid range.

        Returns:
            None
        """
        index = int(index)
        assert index > 0 and index <= len(self.messages), "nothing can be deleted"
        index -= 1

        self.ctx_runtime_data.del_session_message(index)

        self.ctx_history()
        return

    def ctx_delete_messages(self, *indexes:list[int]):
        """
        Delete multiple messages by their indexes.

        Removes messages at the specified indexes (1-based) from
        the context messages and displays the result.

        Args:
            *indexes (list[int]): Variable number of sequence numbers
                                  of messages to delete, starting from 1.

        Returns:
            None
        """
        new_indexes = []
        # Convert 1-based to 0-based index
        for index in indexes:
            new_indexes.append(int(index)-1)

        result = self.ctx_runtime_data.del_session_messages(new_indexes)
        # Convert back to 1-based for display
        for i, value in enumerate(result):
            result[i] = value + 1
        print(f"deleted: {result}")
        self.ctx_history()
        return

    def ctx_summarize(self, head_offset_to_keep:int=1, need_interactive:int=1, to_force:int=0):
        """
        Summarize context messages for the current session.

        Triggers the summarization process for context messages,
        keeping only the specified number of most recent messages
        from the beginning. After summarization, displays the
        updated history.

        Args:
            head_offset_to_keep (int, optional): Number of messages
                to keep from the beginning of the message list
                before summarization. Defaults to 1.
            need_interactive (int, optional): 1 for interactive mode
            to_force (int, optional): 1 to force to do summary, default 0

        Returns:
            None
        """
        head_offset_to_keep = int(head_offset_to_keep)
        need_interactive = True if int(need_interactive) else False
        to_force = True if int(to_force) else False

        if not to_force and not self.ctx_runtime_data.is_need_summarize_for_processed():
            print("no need summarize")
            return

        self.ctx_runtime_data.summarize_messages_for_processed(
            head_offset_to_keep=head_offset_to_keep,
            need_interactive=need_interactive,
        )
        self.ctx_history()
        return

    def ctx_search(self, keyword: str) -> list:
        """
        Search context messages by keyword

        Args:
            keyword (str)

        Returns:
            list: messages
        """
        raw_msgs = ctx_manager.get_messages_by_session(self.session_id, for_raw=True)
        if not raw_msgs:
            return
        matched_msgs = []
        for msg in raw_msgs:
            if keyword in msg.message:
                matched_msgs.append(msg)
        if matched_msgs:
            print_raw_messages(matched_msgs)
        return
