#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Team Agent CLI - AI Team Member Agent

This module provides an AI team member agent that can participate in team
discussions and collaborate with other team members. The agent is designed
to work within the TopsailAI team framework, responding to tasks and
interacting with the team manager.

The agent operates in a read-only mode by default (using history messages
without saving new messages), but can be configured to save messages.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-19

Environment Variables:
    SESSION_ID: Optional session identifier (just use history messages, don't save new messages)
    SYSTEM_PROMPT: Optional file path or content for system prompt
    TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE: Set to "1" to save messages, "0" to not save (default: 0)
    TOPSAILAI_TASK: Optional file path or content for the task
    TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET: Number for offset (msgs[:offset] + msgs[-offset:]), default is 7
"""

import sys
import os

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.ai_team.role import (
    get_member_name,
    get_member_prompt,
)
from topsailai.utils import (
    env_tool,
    file_tool,
)
from topsailai.workspace.agent_shell import get_agent_chat


DEFAULT_HEAD_TAIL_OFFSET = 7


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


def hook_build_message(message:str, **kwargs) -> str:
    """
    Transform the input message to include agent mention format.
    
    This hook function modifies the message to include the agent's mention
    format, which is used to direct the message to a specific team member.
    
    Args:
        message (str): The original input message.
        **kwargs: Additional keyword arguments (unused, for compatibility).
    
    Returns:
        str: The modified message with agent mention prefix in format "@agent_name: message"
        
    Example:
        >>> msg = "Please complete the task"
        >>> hook_build_message(msg)
        '@mm-m25: Please complete the task'
    """
    agent_name = get_member_name()

    if agent_name not in message[:len(agent_name)+5]:
        message = f"@{agent_name}: {message}"

    return message


def main():
    """
    Main entry point for the Team Agent.
    
    This function:
    1. Gets the team member name from the role configuration
    2. Generates the system prompt with team member context
    3. Creates an agent chat instance with appropriate configuration
    4. Runs the agent to process the task and return an answer
    
    The agent operates in a team context, where:
    - It uses history messages from the session
    - It can optionally save messages based on environment variable
    - It uses a ReAct-style agent for task execution
    - It formats messages with agent mention prefix
    
    Environment Variables Used:
        TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE: Whether to save messages (default: false)
        TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET: Session message offset (default: 7)
    
    Returns:
        str or None: The final answer from the agent, or None if no answer generated.
        
    Example:
        $ python team_agent.py
        Processing task...
        Answer: Task completed successfully.
    """
    # agent name
    agent_name = get_member_name()

    # system prompt
    system_prompt = get_system_prompt(agent_name)

    # agent chat
    agent_chat = get_agent_chat(
        system_prompt=system_prompt,
        disabled_tools=["agent_tool"],
        agent_type="react",

        agent_name=agent_name,
        session_head_tail_offset=env_tool.EnvReaderInstance.get(
            "TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET",
            formatter=int,
        ) or DEFAULT_HEAD_TAIL_OFFSET,
        need_print_session=False,
        need_input_message=False,
    )

    answer = agent_chat.run(
        times=1,
        func_build_message=hook_build_message,
        need_save_answer=env_tool.EnvReaderInstance.check_bool("TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE"),
        need_confirm_abort=False,
        need_symbol_for_answer=True,
        only_save_final=True,
    )

    return answer


if __name__ == "__main__":
    main()
