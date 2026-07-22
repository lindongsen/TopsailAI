"""
Context runtime agent utilities for managing AI agent sessions and messages.

This module provides utility classes for managing context runtime data,
including session management, message handling, and tool operations
for the AI agent runtime environment.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
"""

import logging

from topsailai.context import ctx_manager
from topsailai.ai_base.agent_base import AgentBase
from topsailai.utils.env_tool import EnvReaderInstance, is_use_tool_calls
from topsailai.utils import message_tool
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

logger = logging.getLogger(__name__)


class ContextRuntimeUtils(object):
    """
    Common utilities for accessing context runtime data.

    Provides property access to session ID, messages, and AI agent instance
    from the underlying ContextRuntimeData object.
    """

    def __init__(self, ctx_runtime_data: ContextRuntimeData):
        """
        Initialize the ContextRuntimeUtils with runtime data.

        Args:
            ctx_runtime_data: The context runtime data object containing
                             session information and messages.
        """
        self.ctx_runtime_data = ctx_runtime_data
        return

    @property
    def session_id(self) -> str:
        """
        Get the current session ID.

        Returns:
            str: The unique identifier for the current session.
        """
        return self.ctx_runtime_data.session_id

    @property
    def messages(self) -> list:
        """
        Get the list of messages in the runtime context.

        Returns:
            list: A list of message dictionaries in the current context.
        """
        return self.ctx_runtime_data.messages

    @property
    def ai_agent(self) -> AgentBase:
        """
        Get the AI agent instance.

        Returns:
            AgentBase: The AI agent instance associated with this runtime.
        """
        return self.ctx_runtime_data.ai_agent


class ContextRuntimeAIAgent(ContextRuntimeUtils):
    """
    Reference to AIAgent for managing session and runtime messages.

    Provides methods to add session messages and runtime messages
    to the AI agent's message history.
    """

    @staticmethod
    def _drop_orphaned_tool_messages(messages: list) -> list:
        """Drop tool messages whose tool_call_id has no matching assistant tool_calls.

        When native tool calls are enabled, a previously slimmed session may
        contain tool messages whose matching assistant ``tool_calls`` array was
        deleted during archiving. Keeping those orphaned tool messages causes
        provider errors such as "No tool call found for function call output
        with call_id". This helper removes them before the messages are sent
        to the LLM.

        Args:
            messages: List of message dictionaries to clean.

        Returns:
            list: The cleaned message list. If native tool calls are disabled,
            the original list is returned unchanged.
        """
        if not is_use_tool_calls():
            return messages

        valid_tool_call_ids = set()
        cleaned = []
        for msg in messages:
            role = msg.get("role")
            if role == "assistant":
                tool_calls = msg.get("tool_calls") or []
                for tc in tool_calls:
                    tc_id = getattr(tc, "id", None)
                    if tc_id:
                        valid_tool_call_ids.add(tc_id)
                    elif isinstance(tc, dict):
                        tc_id = tc.get("id")
                        if tc_id:
                            valid_tool_call_ids.add(tc_id)
            elif role == "tool":
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id and tool_call_id not in valid_tool_call_ids:
                    logger.warning(
                        "drop orphaned tool message: tool_call_id=%s",
                        tool_call_id,
                    )
                    continue
            cleaned.append(msg)
        return cleaned

    def add_session_message(self, message: dict = None):
        """
        Add the latest agent message to the session context and local messages list.

        If no message is provided, it will automatically retrieve the last message
        from the AI agent's message history.

        Args:
            message (dict, optional): The message dictionary to add. If None,
                                      the last message from ai_agent.messages will be used.

        Raises:
            AssertionError: If no message is provided and ai_agent has no messages.
        """
        if not message:
            if self.ai_agent.messages:
                message = self.ai_agent.messages[-1]

        assert message

        if self.session_id:
            ctx_manager.add_session_message(self.session_id, message)

        self.ctx_runtime_data.append_message(message)

        return

    def add_runtime_messages(self):
        """
        Add runtime context messages to the AI agent's message list.

        Copies all messages from the runtime context (self.messages) and
        appends them to the AI agent's message history.

        When ``TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS`` is enabled,
        only messages that are not already present in the AI agent's message
        history are appended, so the Agent2LLM context persists across turns.
        """
        if not self.messages:
            return

        messages = self._drop_orphaned_tool_messages(self.messages)

        keep_messages = EnvReaderInstance.check_bool(
            "TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS", default=False
        )
        if keep_messages:
            for msg in messages:
                if not message_tool.message_in_list(msg, self.ai_agent.messages):
                    self.ai_agent.messages.append(msg)
        else:
            self.ai_agent.messages += messages
        return
