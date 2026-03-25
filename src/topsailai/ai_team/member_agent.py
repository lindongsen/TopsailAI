'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

import os

from topsailai.ai_team.role import (
    get_member_prompt,
)
from topsailai.utils import (

    file_tool,
)

def extend_system_prompt():
    """
    Set default SYSTEM_PROMPT_EXTRA_FILES environment variable.

    This function sets a default value for SYSTEM_PROMPT_EXTRA_FILES if it's
    not already set. The default is "work_mode/sop/work_agreement.md" which
    contains work-related agreements and SOPs.

    Returns:
        None

    Note:
        This function modifies the environment variable SYSTEM_PROMPT_EXTRA_FILES
        if it doesn't exist.
    """
    if not os.getenv("SYSTEM_PROMPT_EXTRA_FILES"):
        os.environ["SYSTEM_PROMPT_EXTRA_FILES"] = "work_mode/sop/work_agreement.md"
    return


def get_system_prompt(agent_name:str) -> str:
    """
    Get and extend the system prompt for the agent.

    This function retrieves the system prompt from environment variables or files,
    then extends it with the team member prompt specific to the given agent.

    Args:
        agent_name (str): The name of the team member/agent. Used to retrieve
                         the appropriate member prompt.

    Returns:
        str: The complete system prompt content including:
             - Base system prompt from SYSTEM_PROMPT environment variable
             - Team member prompt from get_member_prompt()
             - Extra system prompt files (set by extend_system_prompt())

    Environment Variables Used:
        SYSTEM_PROMPT: File path or content for base system prompt

    Example:
        >>> prompt = get_system_prompt("mm-m25")
        >>> print(prompt[:100])
        You are a helpful AI assistant...
    """
    # system prompt
    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)

    # team role
    member_prompt = get_member_prompt(agent_name)
    if member_prompt not in sys_prompt_content:
        sys_prompt_content += member_prompt

    # extra system prompt
    extend_system_prompt()

    return sys_prompt_content
