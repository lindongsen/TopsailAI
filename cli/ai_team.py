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
    get_team_list,
    g_members,
    generate_team_prompt,
    build_manager_message,
)
from topsailai.ai_team.role import (
    get_manager_name,
    get_manager_prompt,
)
from topsailai.human.role import (
    get_human_name,
)
from topsailai.utils import (
    env_tool,
    time_tool,
    file_tool,
)
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)
from topsailai.workspace.agent_shell import get_agent_chat


DEFAULT_HEAD_TAIL_OFFSET = 7
PROMPT_FILE_AI_TEAM = f"{project_root}/cli/ai_team.md"
PROMPT_FILE_AI_TEAM_MANAGER = f"{project_root}/cli/ai_team_manager.md"

g_flag_only_agent = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_TEAM_MANAGER_ONLY_AGENT")
if g_flag_only_agent:
    PROMPT_FILE_AI_TEAM_MANAGER = f"{project_root}/cli/ai_team_manager_only_agent.md"


def hook_build_message(message:str, curr_count:int, **_) -> str:
    """ return  new message """
    # env
    human_name = get_human_name()

    if curr_count != 1:
        message = build_manager_message(message)

    if human_name not in message[:len(human_name)+5]:
        message = f"{human_name} Say:\n" + message

    return message


def generate_system_prompt():
    """
    Generate the complete system prompt by combining multiple sources.

    Combines:
    - Team information from get_team_list() and generate_team_prompt()
    - System prompt from environment variable or file
    - Team prompt from environment variable or default file

    Returns:
        str: The complete system prompt content

    Environment Variables Used:
        SYSTEM_PROMPT: File path or content for system prompt
        TOPSAILAI_TEAM_PROMPT: File path for team prompt (defaults to PROMPT_FILE_AI_TEAM)
        TOPSAILAI_TEAM_PATH: Path to team member directory (used by get_team_list())
    """
    # team info
    team_list = get_team_list()
    team_info = generate_team_prompt(team_list, g_flag_only_agent)

    # system prompt
    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)

    # team prompt
    if not os.getenv("TOPSAILAI_TEAM_PROMPT"):
        os.environ["TOPSAILAI_TEAM_PROMPT"] = PROMPT_FILE_AI_TEAM
    env_team_prompt = os.getenv("TOPSAILAI_TEAM_PROMPT")
    _, team_prompt_content = file_tool.get_file_content_fuzzy(env_team_prompt)
    if team_prompt_content:
        sys_prompt_content += "\n" + team_prompt_content.strip()

    team_prompt_content += team_info

    # team info
    sys_prompt_content += team_info

    # agent will use this
    os.environ["TOPSAILAI_TEAM_PROMPT_CONTENT"] = team_prompt_content

    # print(team_prompt_content)

    # manager prompt
    _, manager_prompt_content = file_tool.get_file_content_fuzzy(PROMPT_FILE_AI_TEAM_MANAGER)

    # team role info
    sys_prompt_content += (
        get_manager_prompt() +
        manager_prompt_content +
        "\n\n---"
    )

    print(sys_prompt_content)

    return sys_prompt_content

def main():
    """ main entry """
    # agent name
    manager_name = get_manager_name()

    # prompt
    sys_prompt_content = generate_system_prompt()

    # show members
    print(g_members)

    # agent chat
    agent_chat = get_agent_chat(
        system_prompt=sys_prompt_content,
        disabled_tools=[
            "agent_tool",
        ],

        agent_name=manager_name,
        session_id=os.getenv("SESSION_ID") or time_tool.get_current_date(with_t=True),

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
        print(g_members)
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
