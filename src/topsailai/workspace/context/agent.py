
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-23
  Purpose:
'''

from topsailai.context import ctx_manager
from topsailai.ai_base.agent_base import AgentBase
from topsailai.utils import (
    format_tool,
)
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData


class ContextRuntimeUtils(object):
    """ common utils """
    def __init__(self, ctx_runtime_data:ContextRuntimeData):
        self.ctx_runtime_data = ctx_runtime_data
        return

    @property
    def session_id(self) -> str:
        return self.ctx_runtime_data.session_id

    @property
    def messages(self) -> list:
        return self.ctx_runtime_data.messages

    @property
    def ai_agent(self) -> AgentBase:
        return self.ctx_runtime_data.ai_agent


class ContextRuntimeAIAgent(ContextRuntimeUtils):
    """ reference to AIAgent """

    def add_session_message(self, message:dict=None):
        """
        Add the latest agent message to the session context and local messages list.
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
        """ add runtime_data.messages to ai_agent.messages """
        if self.messages:
            self.ai_agent.messages += self.messages
        return

class ContextRuntimeAgentTools(ContextRuntimeAIAgent):
    """ agent tools to manage context messages.
    agent will call these tools.
    """
    # user chats to agent
    def tool_delete_messages_for_processed(self, indexes:list[int]) -> str:
        """delete context messages
        Args:
            indexes (list[int]): Sequence number starting from 0, Example: [1,2,3]
        """
        indexes = format_tool.to_list_int(indexes)
        if not indexes:
            return "do nothing"
        result = self.ctx_runtime_data.del_session_messages(indexes)
        return f"deleted ok: {result}"

    # agent chats to LLM
    def tool_delete_messages_for_processing(self, indexes:list[int]) -> str:
        """delete context messages
        Args:
            indexes (list[int]): Sequence number starting from 0, Example: [11,12,13]
        """
        indexes = format_tool.to_list_int(indexes)
        if not indexes:
            return "do nothing"
        result = self.ctx_runtime_data.del_agent_messages(indexes)
        return f"deleted ok: {result}"
