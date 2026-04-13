'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-13
  Purpose: Plan and execute task agent for TopsailAI CLI
'''

import os
import sys

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.logger import logger
from topsailai.tools.base.common import add_tool
from topsailai.tools import (
    file_readonly_tool,
    skill_tool,
)
from topsailai.utils import (
    env_tool,
)
from topsailai.workspace.task import task_tool
from topsailai.workspace.agent_shell import get_agent_chat


task_agent = None


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


############################################################################
# Plan Tools
############################################################################

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
    task_id = get_task_id()
    return task_agent.run(
        message=task,
        times=1,
        need_session_lock=False,
        task_id=task_id,
    )


def get_tool_map() -> dict:
    """
    Build and return a mapping of tool names to their corresponding functions.

    This function constructs a dictionary that maps tool names to their handler
    functions. It includes the plan_tool-call_assistant function and all file
    readonly tools. Each tool is also registered using the add_tool function.

    Returns:
        dict: A dictionary mapping tool names (str) to their handler functions.
    """
    tool_map = {
        "plan_tool-call_assistant": call_assistant,
    }
    for tool_name, tool_func in file_readonly_tool.FILE_RO_TOOLS.items():
        tool_name = "file_readonly_tool-" + tool_name
        tool_map[tool_name] = tool_func

    for tool_name, tool_func in tool_map.items():
        add_tool(tool_name, tool_func)

    return tool_map


def main():
    """
    Main entry point for the plan and execute task agent.

    This function initializes and configures two agents:
    1. plan_agent: Handles planning with call_assistant and file readonly tools.
    2. task_agent: Executes tasks with disabled planning tools.

    The function sets up the global task_agent, configures available tools,
    and starts the plan_agent to run once.

    Returns:
        None
    """
    # task agent
    global task_agent

    with env_tool.ctxm_hide_env(
        [
            "TOPSAILAI_TASK",
        ]
    ):
        disabled_tools = ["agent_tool", "plan_tool-call_assistant"]
        task_agent = get_agent_chat(
            disabled_tools=disabled_tools,
            need_input_message=False,
        )
        task_agent.hooks_for_final_answer.clear()

        call_assistant.__doc__ += "\n>>> SKILL START\n" + skill_tool.PROMPT_PLUGIN_SKILLS + "\n<<< SKILL END"

    # plan agent
    with env_tool.ctxm_hide_env(
        [
            "TOPSAILAI_PLUGIN_SKILLS",
        ]
    ):
        plan_agent = get_agent_chat(
            disabled_tools=["agent_tool"],
            tool_map=get_tool_map(),
            agent_type="plan_and_execute",
        )

    # run
    plan_agent.run(times=1)
    return


if __name__ == "__main__":
    main()
