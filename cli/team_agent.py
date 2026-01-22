#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-19
  Purpose:
  Env:
    @SESSION_ID: string; JUST USE history messages, DONOT SAVE any new messages.
    @SYSTEM_PROMPT: file or content;
    @TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE: 1 is save, 0 is not save. default is 0.
'''

import sys
import os
from dotenv import load_dotenv

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.ai_base.agent_types import react
from topsailai.ai_base.constants import (
    ROLE_ASSISTANT,
)
from topsailai.utils import env_tool
from topsailai.context import ctx_manager
from topsailai.workspace.agent_shell import get_agent_chat
from topsailai.workspace.input_tool import (
    get_message,
)


def main():
    """ main entry """
    load_dotenv()

    message = get_message()
    env_agent_name = os.getenv("TOPSAILAI_AGENT_NAME") or os.getenv("TOPSAIL_TEAM_MEMBER_NAME")

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

    # team role
    sys_prompt_content += f"""
YOU ARE ({env_agent_name})
"""

    # agent
    agent = get_agent_chat(sys_prompt_content, disabled_tools=["agent_tool"])
    if env_agent_name:
        # set agent name
        agent.agent_name = env_agent_name

        # team role
        message = f"@{env_agent_name}: {message}"

    # llm
    llm_model = agent.llm_model
    llm_model.max_tokens = max(1500, llm_model.max_tokens)
    llm_model.temperature = min(0.97, llm_model.temperature)

    def hook_after_init_prompt(self):
        if messages_from_session:
            self.messages += messages_from_session

    def hook_after_new_session(self):
        ctx_manager.add_session_message(session_id, self.messages[-1])

    agent.hooks_after_init_prompt.append(hook_after_init_prompt)
    if env_tool.EnvReaderInstance.check_bool("TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE"):
        agent.hooks_after_new_session.append(hook_after_new_session)

    answer = agent.run(react.Step4ReAct(), message)
    if answer:
        symbol_start = os.getenv("TOPSAILAI_SYMBOL_STARTSWITH_ANSWER")
        if not symbol_start and env_agent_name:
            symbol_start = f"From '{env_agent_name}':\n"
        if symbol_start and not answer.startswith(symbol_start.strip()):
            answer = symbol_start + answer

        if env_tool.EnvReaderInstance.check_bool("TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE"):
            ctx_manager.add_session_message(
                session_id,
                {"role": ROLE_ASSISTANT, "content": answer}
            )

        # save answer to file
        file_path_result = os.getenv("TOPSAILAI_SAVE_RESULT_TO_FILE")
        if file_path_result:
            with open(file_path_result, encoding='utf-8', mode='w') as fd:
                fd.write(answer)

    if not env_tool.is_debug_mode():
        print()
        print(">>> answer:")
        print(answer)

    print()

if __name__ == "__main__":
    main()
