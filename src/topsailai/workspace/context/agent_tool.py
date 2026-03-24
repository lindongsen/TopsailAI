'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-24
  Purpose:
'''

from topsailai.utils import (
    format_tool,
)
from topsailai.workspace.context.agent import (
    ContextRuntimeAIAgent,
)

class ContextRuntimeAgentTools(ContextRuntimeAIAgent):
    """
    Agent tools to manage context messages.

    Provides tool methods that can be called by the agent to manage
    both session messages and agent messages during processing.
    """

    # tool name
    TOOL_CONTEXT_DELETE_MESSAGES = "context-delete_messages"

    # user chats to agent
    def tool_delete_messages_for_processed(self, indexes: list[int]) -> str:
        """ You can use this tool to prune out useless messages

        Args:
            indexes (list[int]): Sequence numbers of messages to delete,
                                 starting from 0. Example: [1, 2, 3]

        Returns:
            str: A message indicating the result of the deletion operation.
        """
        indexes = format_tool.to_list_int(indexes)
        if not indexes:
            return ("do nothing")

        result = self.ctx_runtime_data.del_session_messages(indexes)
        return (f"deleted ok: {result}")

    # agent chats to LLM
    def tool_delete_messages_for_processing(self, indexes: list[int]) -> str:
        """ You can use this tool to prune out useless messages.
        Note that when the number of messages exceeds 50, use this tool to prune them, ensuring the context remains concise and efficient.

        Args:
            indexes (list[int]):
                ## About Sequence
                Sequence numbers of messages to delete,
                starting from 0, Example: [11, 12, 13]
                ## About Index
                The value of index starts from non-role=system, example:
                [msg1, msg2, msg3], msg1's role is system, msg2'role is not system,
                so index=0 is msg2, index=1 is msg3, ...

        Returns:
            str: A message indicating the result of the deletion operation.
        """
        indexes = format_tool.to_list_int(indexes)
        if not indexes:
            return ("do nothing")

        result = self.ctx_runtime_data.del_agent_messages(indexes)
        return (f"deleted ok: {result}")
