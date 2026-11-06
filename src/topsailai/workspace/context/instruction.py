"""
Context runtime instructions module.

This module provides instruction handlers for managing context messages
in the TopsailAI workspace, including operations like clearing, viewing,
deleting, and summarizing messages.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
"""

import json

from topsailai.ai_base.constants import (
    ROLE_USER,
    STEP_NAME_OBSERVATION,
    MSG_KEY_STEP_NAME,
    MSG_KEY_RAW_TEXT,
)
from topsailai.context import ctx_manager
from topsailai.tools.agent_tool_utils.story import (
    subprocess_agent_memory_as_story,
)
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)
from topsailai.workspace.print_tool import (
    format_context_messages,
    format_raw_messages,
)
from topsailai.workspace.context.agent import ContextRuntimeUtils
from topsailai.workspace.plugin_instruction.agent import get_tokens


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
            "ctx.btw": self.ctx_btw,
            "agent.tokens": self.agent_tokens,
        }

        # session metadata
        session_map = {
            "session.rename": self.session_rename,
        }

        # total
        instructions = {}
        instructions.update(ctx_map)
        instructions.update(session_map)

        # result
        return instructions

    def agent_tokens(self) -> str:
        """Report token usage for the two current message layers."""
        return get_tokens(self.ctx_runtime_data)

    ##############################################################################
    # Session metadata
    ##############################################################################
    def session_rename(self, *args) -> str:
        """
        Rename the current session and refresh its update_time.

        The new name is the positional arguments joined with a single space,
        so multi-word names do not need quoting.

        Usage::

            /session.rename my new name

        Args:
            *args: Positional words/phrases that are assembled into the new
                session name.

        Returns:
            str: A concise confirmation or error message.
        """
        session_id = self.session_id
        if not session_id:
            return "no active session, cannot rename"

        session_name = " ".join(str(arg) for arg in args).strip()
        if not session_name:
            return "Usage: /session.rename <session_name>"

        if "\0" in session_name or "\n" in session_name or "\r" in session_name:
            return "Invalid session name: control characters are not allowed"

        if not ctx_manager.update_session_name(session_id, session_name):
            return f"rename failed: session_id={session_id}"

        return f"renamed session {session_id} -> {session_name}"

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
            return f"Context cannot be clear due to exist session_id({session_id})"

        self.ctx_runtime_data.clear_messages()
        return "Context already is clear"

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
        return (
            "The history messages will be save to a new story, "
            f"pid=[{pid}], msg_len=[{len(self.messages)}]"
        )

    def ctx_history(self, offset: str = "") -> str:
        """Return the current session history with an optional slice."""
        self.ctx_refresh()
        session_id = self.session_id
        messages = self.messages
        if messages and offset:
            head_offset = None
            tail_offset = None
            try:
                if ":" in offset:
                    head_offset, tail_offset = offset.split(":", 1)
                    head_offset = int(head_offset)
                    tail_offset = int(tail_offset)
                else:
                    head_offset = tail_offset = int(offset)
                    tail_offset = -tail_offset
            except Exception:
                pass
            if head_offset is not None:
                messages = messages[head_offset:tail_offset]

        header = f"{SPLIT_LINE}\nShow history messages {session_id}"
        if not messages:
            return header
        return f"{header}\n{format_context_messages(messages).rstrip()}"

    def ctx_history2(self) -> str:
        """Return raw history messages for the current session."""
        session_id = self.session_id
        raw_msgs = ctx_manager.get_messages_by_session(session_id, for_raw=True)
        header = f"{SPLIT_LINE}\nShow raw history messages {session_id}"
        if not raw_msgs:
            return header
        return f"{header}\n{format_raw_messages(raw_msgs).rstrip()}"

    def ctx_btw(self, *args):
        """
        Add a "by the way" message to the Agent2LLM ephemeral message context.

        This instruction injects a message directly into the agent's internal
        ReAct conversation context (``self.ai_agent.messages``). Positional
        arguments are joined with a single space to form the content, which is
        wrapped as an observation payload so downstream consumers treat it like
        a runtime observation.

        Usage::

            /ctx.btw hello world
            /ctx.btw this is a multi word message

        Args:
            *args: Positional words/phrases that are assembled into the message
                content.

        Returns:
            str: A concise confirmation message.
        """
        content = " ".join(str(arg) for arg in args)

        if not self.ai_agent:
            return "no active agent, cannot add Agent2LLM message"

        if self.ai_agent.messages is None:
            self.ai_agent.messages = []

        observation_content = {
            MSG_KEY_STEP_NAME: STEP_NAME_OBSERVATION,
            MSG_KEY_RAW_TEXT: content,
        }
        message = {
            "role": ROLE_USER,
            "content": json.dumps(observation_content),
        }
        # Append via the controlled mutator convention for the Agent2LLM layer:
        # use ``+=`` on the existing list rather than replacing the reference.
        self.ai_agent.messages += [message]
        return f"added 1 user message to Agent2LLM context (total={len(self.ai_agent.messages)})"

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
        return self.ctx_history()

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
        history = self.ctx_history()
        return f"deleted: {result}\n{history}"

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
            return "no need summarize"

        self.ctx_runtime_data.summarize_messages_for_processed(
            head_offset_to_keep=head_offset_to_keep,
            need_interactive=need_interactive,
            force=to_force,
        )
        return self.ctx_history()

    def ctx_search(self, keyword: str) -> str | None:
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
            return format_raw_messages(matched_msgs).rstrip()
        return None
