'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-13
  Purpose:
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
)
from topsailai.workspace.task import task_tool
from topsailai.workspace.agent_shell import get_agent_chat


def gen_task_id():
    task_id = task_tool.generate_task_id()
    os.environ["TOPSAILAI_TASK_ID"] = task_id
    logger.info("generate new task id: [%s]", task_id)
    return task_id

def get_task_id():
    task_id = os.getenv("TOPSAILAI_TASK_ID")
    if task_id:
        return task_id
    return gen_task_id()

def execute_task(task:str) -> str:
    """
    This is a versatile AI assistant. Leave everything you can't solve to it.

    Args:
        task (str): content

    Returns:
        str: final_answer
    """
    assert task, "missing task content"
    task_id = get_task_id()
    return task_agent.run(
        message=task, times=1, need_interactive=False,
        task_id=task_id,
    )

def get_tool_map() -> dict:
    tool_map = {
        "plan_tool-call_assistant": execute_task,
    }
    for tool_name, tool_func in file_readonly_tool.FILE_RO_TOOLS.items():
        tool_name = "file_readonly_tool-" + tool_name
        tool_map[tool_name] = tool_func

    for tool_name, tool_func in tool_map.items():
        add_tool(tool_name, tool_func)

    return tool_map

# plan agent
plan_agent = get_agent_chat(
    disabled_tools=["agent_tool"],
    tool_map=get_tool_map(),
    agent_type="plan_and_execute",
)

# task agent
task_agent = get_agent_chat(
    disabled_tools=["agent_tool"],
    need_input_message=False,
)
task_agent.hooks_for_final_answer.clear()

def main():
    plan_agent.run(times=1, need_interactive=False)


if __name__ == "__main__":
    main()
