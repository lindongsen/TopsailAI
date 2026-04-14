'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-14
  Purpose:
'''

import os
from topsailai.logger import logger
from topsailai.tools import (
    skill_tool,
)
from topsailai.workspace.task import task_tool


def gen_task_id():
    """
    Generate a new unique task ID and set it as an environment variable.

    This function generates a new task ID using the task_tool module, stores it
    in the TOPSAILAI_TASK_ID environment variable, and logs the generation.

    Returns:
        str: The newly generated task ID.
    """
    task_id = task_tool.generate_task_id()
    os.environ["TOPSAILAI_TASK_ID"] = task_id
    logger.info("generate new task id: [%s]", task_id)
    return task_id


def get_task_id():
    """
    Get the current task ID from environment or generate a new one.

    This function retrieves the task ID from the TOPSAILAI_TASK_ID environment
    variable. If no task ID exists, it generates a new one by calling gen_task_id().

    Returns:
        str: The current task ID (existing or newly generated).
    """
    task_id = os.getenv("TOPSAILAI_TASK_ID")
    if task_id:
        return task_id
    return gen_task_id()


def call_assistant(task:str) -> str:
    """
    This is a versatile AI assistant. Leave everything you can't solve to it.

    [REMEMBER] When encountering difficulties(example: available tools are limited), DONOT ask the user, but call this assistant tool to solve them.
    **Everything you cannot, you JUST delegate to the assistant tool**

    Args:
        task (str): content

    Returns:
        str: final_answer
    """
    assert task, "missing task content"

    from topsailai.workspace.agent_shell import get_agent_chat

    disabled_tools = ["agent_tool", "subagent_tool"]

    task_agent = get_agent_chat(
        disabled_tools=disabled_tools,
        need_input_message=False,
    )
    task_agent.hooks_for_final_answer.clear()

    task_id = get_task_id()
    return task_agent.run(
        message=task,
        times=1,
        need_session_lock=False,
        task_id=task_id,
    )
call_assistant.__doc__ += "\n>>> SKILL START\n" + skill_tool.PROMPT_PLUGIN_SKILLS + "\n<<< SKILL END"

TOOLS = dict(
    call_assistant=call_assistant,
)

FLAG_TOOL_ENABLED = False
