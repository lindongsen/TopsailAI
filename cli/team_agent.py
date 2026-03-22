#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-19
  Purpose: I am AI member
  Env:
    @SESSION_ID: string; JUST USE history messages, DONOT SAVE any new messages.
    @SYSTEM_PROMPT: file or content;
    @TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE: 1 is save, 0 is not save. default is 0.
    @TOPSAILAI_TASK: file or content.
    @TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET: one number for offset (msgs[:offset] + msgs[-offset:]), default is 7.
'''

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
    """ set default SYSTEM_PROMPT_EXTRA_FILES to eviron """
    if not os.getenv("SYSTEM_PROMPT_EXTRA_FILES"):
        os.environ["SYSTEM_PROMPT_EXTRA_FILES"] = "work_mode/sop/work_agreement.md"
    return

def get_system_prompt(agent_name:str) -> str:
    """ get & extend system prompt  """
    # system prompt
    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)

    # team role
    sys_prompt_content += get_member_prompt(agent_name)

    # extra system prompt
    extend_system_prompt()

    return sys_prompt_content

def hook_build_message(message:str, **kwargs) -> str:
    """ return new message """
    agent_name = get_member_name()

    if agent_name not in message[:len(agent_name)+5]:
        message = f"@{agent_name}: {message}"

    return message

def main():
    """ main entry """
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
        only_save_final=True,
    )

    return answer

if __name__ == "__main__":
    main()
