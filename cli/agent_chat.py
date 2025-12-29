#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-19
  Purpose:
  Env:
    @SESSION_ID: string;
    @SYSTEM_PROMPT: file or content;
'''

import sys
import os
from dotenv import load_dotenv

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.logger import logger
from topsailai.ai_base.llm_base import ContentStdout
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.agent_types import react
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.utils import env_tool

from topsailai.context import ctx_manager


def get_message():
    """ return str for message """
    message = ' '.join(sys.argv[1:])

    # message from file
    file_path = message
    if sys.argv[1] == '-':
        file_path = "/dev/stdin"
    if file_path and os.path.exists(file_path):
        with open(file_path) as fd:
            message = fd.read()

    message = message.strip()
    assert message, "message is null"
    return message

def get_agent(system_prompt="", to_dump_messages=False):
    """ return a agent object. """
    disabled_tools = env_tool.EnvReaderInstance.get_list_str("TOPSAILAI_CLI_AGENT_CHAT_DISABLED_TOOLS")
    if disabled_tools is None:
        disabled_tools = ["agent_tool"]
    elif not disabled_tools:
        disabled_tools = []

    agent = AgentRun(
        react.SYSTEM_PROMPT + "\n====\n" + system_prompt,
        tools=None,
        agent_name=react.AGENT_NAME,
        excluded_tool_kits=disabled_tools,
    )

    # set flags
    if to_dump_messages:
        agent.flag_dump_messages = True

    return agent

def main():
    """ main entry """
    load_dotenv()

    message = get_message()

    # session
    session_id = os.getenv("SESSION_ID")
    messages_from_session = None
    if session_id:
        print(f"session_id: {session_id}")

        messages_from_session = ctx_manager.get_messages_by_session(session_id)
        if not messages_from_session:
            ctx_manager.create_session(session_id, task=message)

    # system prompt
    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    sys_prompt_file = ""
    sys_prompt_content = ""
    if env_sys_prompt:
        if os.path.exists(env_sys_prompt):
            sys_prompt_file = env_sys_prompt
        else:
            sys_prompt_content = env_sys_prompt

    if sys_prompt_file:
        with open(sys_prompt_file, encoding="utf-8") as fd:
            sys_prompt_content = fd.read().strip()

    # agent
    agent = get_agent(sys_prompt_content)

    # llm
    llm_model = agent.llm_model
    llm_model.max_tokens = max(1600, llm_model.max_tokens)
    llm_model.temperature = max(0.97, llm_model.temperature)

    def hook_after_init_prompt(self):
        if messages_from_session:
            self.messages += messages_from_session

    def hook_after_new_session(self):
        ctx_manager.add_session_message(session_id, self.messages[-1])

    agent.hooks_after_init_prompt.append(hook_after_init_prompt)
    agent.hooks_after_new_session.append(hook_after_new_session)

    answer = agent.run(react.Step4ReAct(), message)
    if answer:
        ctx_manager.add_session_message(session_id, agent.messages[-1])

    if not env_tool.is_debug_mode():
        print()
        print(">>> answer:")
        print(answer)

    print()

if __name__ == "__main__":
    main()
