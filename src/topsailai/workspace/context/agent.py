"""
Context runtime agent utilities for managing AI agent sessions and messages.

This module provides utility classes for managing context runtime data,
including session management, message handling, and tool operations
for the AI agent runtime environment.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
"""

from topsailai.context import ctx_manager
from topsailai.ai_base.agent_base import AgentBase
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData


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
        """
        if self.messages:
            self.ai_agent.messages += self.messages
        return
