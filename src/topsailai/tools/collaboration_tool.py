'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-05
  Purpose: hermit
'''

from topsailai.ai_base.agent_types.exception import (
    AgentFinalAnswer,
)

ACTION_FINISH_TASK = "await_or_transfer_task"

def await_or_transfer_task(summary:str):
    """
    tool_call in following Scenarios:
    - When a certain stage or step is completed.
      example:
        awaiting something from x;
        execute the next step by x;
        execute something by x;

    Args:
        summary (str): complete info
    """
    raise AgentFinalAnswer(summary)


def finish_task(final_answer:str):
    """ output final answer and finish task.

    Args:
        final_answer: str
    """
    # no need execute this tool, set hook in ai_base.agent_types
    raise Exception("BUG: no need execute the tool")


TOOLS = dict(
    await_or_transfer_task=await_or_transfer_task,
)

FLAG_TOOL_ENABLED = False
