'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose:
'''

from topsailai.utils import (
    env_tool,
)
from topsailai.utils.thread_local_tool import (
    get_agent_object,
)

from topsailai.ai_base.llm_control.message import (
    get_count_of_action,
)
from topsailai.ai_base.agent_base import AgentBase


def get_count_of_action_for_current_agent() -> int:
    """ get count of action from history context messages

    Returns:
        int: a number, -1 for invalid
    """
    agent = get_agent_object()
    if agent is None:
        return -1

    return get_count_of_action(agent.messages)


class _AgentContextBase(object):

    @property
    def agent(self) -> AgentBase | None:
        return get_agent_object()

    @property
    def max_tokens(self) -> int:
        _max_tokens = 0
        if self.agent:
            _max_tokens = self.agent.llm_model.max_tokens
        if not _max_tokens:
            _max_tokens = env_tool.EnvReaderInstance.get("MAX_TOKENS", 3000, formatter=int)
        return _max_tokens


AgentContextInstance = _AgentContextBase()
