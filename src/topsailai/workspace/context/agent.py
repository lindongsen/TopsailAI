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
from topsailai.utils import (
    format_tool,
)
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


class ContextRuntimeAgentTools(ContextRuntimeAIAgent):
    """
    Agent tools to manage context messages.
    
    Provides tool methods that can be called by the agent to manage
    both session messages and agent messages during processing.
    """
    
    # user chats to agent
    def tool_delete_messages_for_processed(self, indexes: list[int]) -> str:
        """
        Delete context messages from the session.
        
        Removes messages from the session context based on the provided indexes.
        This is typically used when user messages have been processed.
        
        Args:
            indexes (list[int]): Sequence numbers of messages to delete,
                                 starting from 0. Example: [1, 2, 3]
        
        Returns:
            str: A message indicating the result of the deletion operation.
        """
        indexes = format_tool.to_list_int(indexes)
        if not indexes:
            return "do nothing"
        result = self.ctx_runtime_data.del_session_messages(indexes)
        return f"deleted ok: {result}"

    # agent chats to LLM
    def tool_delete_messages_for_processing(self, indexes: list[int]) -> str:
        """
        Delete context messages from the agent's message list.
        
        Removes messages from the agent's internal message list based on
        the provided indexes. This is typically used when agent messages
        have been processed.
        
        Args:
            indexes (list[int]): Sequence numbers of messages to delete,
                                 starting from 0. Example: [11, 12, 13]
        
        Returns:
            str: A message indicating the result of the deletion operation.
        """
        indexes = format_tool.to_list_int(indexes)
        if not indexes:
            return "do nothing"
        result = self.ctx_runtime_data.del_agent_messages(indexes)
        return f"deleted ok: {result}"
