'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-05
  Purpose: hermit
'''

def finish_task(final_answer:str):
    """ output final answer and finish task.

    Args:
        final_answer: str
    """
    # no need execute this tool, set hook in ai_base.agent_types
    raise Exception("BUG: no need execute the tool")


TOOLS = dict(
    finish_task=finish_task,
)

FLAG_TOOL_ENABLED = False
