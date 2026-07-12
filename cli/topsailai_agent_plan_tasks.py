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
from topsailai.utils.env_tool import is_true
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

    # Tool availability for the plan_agent:
    #
    # `enabled_tools` acts as an explicit allow-list. Only the tool kits listed
    # below are available to the plan_agent, plus any tools injected via
    # `tool_map`.
    #
    # Available tools:
    #   - file_readonly_tool-* (read-only file operations, injected by get_tool_map)
    #       - check_files_existing
    #       - get_file_size
    #       - list_dirs
    #       - read_file
    #       - read_file_around_line
    #       - read_file_lines
    #       - read_file_with_context
    #       - read_files
    #   - story_memory_tool-* (persistent memory access)
    #   - subagent_tool-call_assistant (delegate work to sub-agents)
    #
    # Deliberately unavailable:
    #   - agent_tool is disabled via disabled_tools.
    #   - cmd_tool, file_tool (write variants), skill_tool, time_tool, ctx_tool,
    #     and all other internal tools are NOT in the allow-list, so the main
    #     agent cannot execute commands, write files, call skills, etc. directly.
    #     Any such action must be delegated to a sub-agent through
    #     subagent_tool-call_assistant.
    #
    # Determine whether to inject the read-only file tool map into the plan
    # agent. This is controlled by the TOPSAILAI_AGENT_PLAN_USE_TOOL_MAP
    # environment variable. When set to a truthy value (e.g. "1", "true", "yes",
    # "on", "enabled"), the file_readonly_tool-* handlers are passed via
    # tool_map. When unset or falsy, tool_map is omitted and the plan agent only
    # has access to the story_memory_tool and subagent_tool kits.
    use_tool_map = is_true(os.getenv("TOPSAILAI_AGENT_PLAN_USE_TOOL_MAP"))

    plan_agent_kwargs = dict(
        session_id=get_session_id(),
        disabled_tools=["agent_tool"],
        enabled_tools=["story_memory_tool", "subagent_tool"],
        agent_type="plan_and_execute",
    )
    if use_tool_map:
        plan_agent_kwargs["tool_map"] = get_tool_map()

    # plan agent
    plan_agent = get_agent_chat(**plan_agent_kwargs)

    # run
    plan_agent.run()
    return


if __name__ == "__main__":
    main()
