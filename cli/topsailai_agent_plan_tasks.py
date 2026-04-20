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

# init env
os.environ["TOPSAILAI_ENABLED_TOOLS"] = (os.getenv("TOPSAILAI_ENABLED_TOOLS", "+") or "+") + ";" + "subagent_tool;"

from topsailai.tools import (
    file_readonly_tool,
)
from topsailai.context.common import get_session_id
from topsailai.workspace.agent_shell import get_agent_chat


############################################################################
# Plan Tools
############################################################################

def get_tool_map() -> dict:
    """
    Build and return a mapping of tool names to their corresponding functions.

    This function constructs a dictionary that maps tool names to their handler
    functions. It includes the plan_tool-call_assistant function and all file
    readonly tools. Each tool is also registered using the add_tool function.

    Returns:
        dict: A dictionary mapping tool names (str) to their handler functions.
    """
    tool_map = {}
    for tool_name, tool_func in file_readonly_tool.FILE_RO_TOOLS.items():
        tool_name = "file_readonly_tool-" + tool_name
        tool_map[tool_name] = tool_func

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
    # plan agent
    plan_agent = get_agent_chat(
        session_id=get_session_id(),
        disabled_tools=["agent_tool"],
        enabled_tools=["story_memory_tool", "subagent_tool"],
        tool_map=get_tool_map(),
        agent_type="plan_and_execute",
    )

    # run
    plan_agent.run()
    return


if __name__ == "__main__":
    main()
