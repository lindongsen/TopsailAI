'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose:
'''

from topsailai.utils.thread_local_tool import (
    get_agent_object,
)

from topsailai.ai_base.llm_control.message import (
    get_count_of_action,
)


def get_count_of_action_for_current_agent() -> int:
    """ get count of action from history context messages

    Returns:
        int: a number, -1 for invalid
    """
    agent = get_agent_object()
    if agent is None:
        return -1

    return get_count_of_action(agent.messages)
