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

import os
import sys
# DONOT DELETE THIS FOR FUNCTION 'input'
import readline
from dotenv import load_dotenv

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.logger import logger
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.base_class import ContentStdout
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.utils import env_tool
from topsailai.utils.thread_local_tool import set_thread_var, KEY_SESSION_ID
from topsailai.workspace.input_tool import get_message, input_message

from topsailai.context import ctx_manager


def main():
    """ main entry """
    load_dotenv()

    message = get_message()

    # session
    session_id = os.getenv("SESSION_ID")
    messages_from_session = None
    if session_id:
        print(f"session_id: {session_id}")
        set_thread_var(KEY_SESSION_ID, session_id)

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

    llm_model = LLMModel()
    llm_model.content_senders.append(ContentStdout())
    llm_model.max_tokens = max(1600, llm_model.max_tokens)
    llm_model.temperature = 0.97

    prompt_ctl = PromptBase(sys_prompt_content or "You are a helpful assistant.")
    if messages_from_session:
        prompt_ctl.messages = messages_from_session
        prompt_ctl.add_user_message(message)
    else:
        prompt_ctl.new_session(message)

    max_count = 100
    while True:
        max_count -= 1
        print(">>> LLM Answer:")
        answer = llm_model.chat(prompt_ctl.messages, for_raw=True, for_stream=True)
        prompt_ctl.add_assistant_message(answer)
        print()
        if max_count == 0:
            break
        message = input_message()
        prompt_ctl.add_user_message(message)
        prompt_ctl.update_message_for_env()

    return


if __name__ == "__main__":
    main()
