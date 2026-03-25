#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-20
  Purpose: I am AI Manager who is a "Router and Coordinator"
  MD:
    "ai_team.md" is shared across the entire team;
    "ai_team_manager.md" is only used by the manager;
  Env:
    @SESSION_ID: required, string;
    @SYSTEM_PROMPT: file or content;
    @TOPSAILAI_TEAM_PROMPT: required, file or content;
    @TOPSAILAI_TEAM_PATH: required, the team folder;
    @TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE: team_agent can store the first message (task) and the last message (final_answer)
'''

import os
import sys

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")
os.chdir(project_root)

from topsailai.ai_team.manager import (
    get_members_cache,
    build_manager_message,
)
from topsailai.ai_team.role import (
    get_manager_name,
)
from topsailai.human.role import (
    get_human_name,
)
from topsailai.utils import (
    env_tool,
)
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)
from topsailai.workspace.agent_shell import get_agent_chat
from topsailai.ai_team.common import (
    DEFAULT_HEAD_TAIL_OFFSET,
    generate_system_prompt,
    get_session_id,
)


def hook_build_message(message:str, curr_count:int, **_) -> str:
    """
    Transform and format messages with agent mention format.

    This hook is called for each message to add the human name prefix
    and build manager messages for subsequent turns.

    Args:
        message: The message content to transform.
        curr_count: The current message count/turn number.
        **_: Additional keyword arguments (ignored).

    Returns:
        str: The transformed message with proper formatting.

    Example:
        >>> hook_build_message("Hello", 1)
        'Human Say:\\nHello'
        >>> hook_build_message("Hello", 2)
        'Human Say:\\n[Manager] Hello'
    """
    # env
    human_name = get_human_name()

    if curr_count != 1:
        message = build_manager_message(message)

    if human_name not in message[:len(human_name)+5]:
        message = f"{human_name} Say:\n" + message

    return message

def main():
    """
    Main entry point for the AI Team Manager.

    This function:
    1. Retrieves the manager name
    2. Generates the complete system prompt
    3. Displays team members
    4. Initializes and runs the agent chat with hooks

    Returns:
        The answer/response from the agent chat session.

    Environment Variables:
        TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET: Optional offset for session context (default: 7)
    """
    # agent name
    manager_name = get_manager_name()

    # prompt
    sys_prompt_content = generate_system_prompt()

    # show members
    print(get_members_cache())

    # agent chat
    agent_chat = get_agent_chat(
        system_prompt=sys_prompt_content,
        disabled_tools=[
            "agent_tool",
        ],

        agent_name=manager_name,
        session_id=get_session_id(),

        session_head_tail_offset=env_tool.EnvReaderInstance.get(
            "TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET",
            formatter=int,
        ) or DEFAULT_HEAD_TAIL_OFFSET,
    )

    ##########################################################################################
    # Hook Instruction
    ##########################################################################################
    def _member():
        """
        Display the list of team members.
        Shows separator line and all available team members.
        """
        print(f"\n\n{SPLIT_LINE}")
        print("Show members")
        print(get_members_cache())
        return

    # team.xxx
    instructions = {
        "team.member": _member,
    }

    agent_chat.hook_instruction.load_instructions(instructions)


    ##########################################################################################
    # main
    ##########################################################################################

    def hook_print_pre_input_message():
        """ print sth. before inputing message """
        _member()
        return

    answer = agent_chat.run(
        func_build_message=hook_build_message,
        func_print_pre_input_message=hook_print_pre_input_message,
    )

    return answer


if __name__ == "__main__":
    main()
