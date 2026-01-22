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
from topsailai.ai_base.llm_base import LLMModel, ContentStdout
from topsailai.ai_base.prompt_base import PromptBase, ROLE_USER
from topsailai.utils import (
    env_tool,
    json_tool,
    file_tool,
)
from topsailai.utils.thread_local_tool import set_thread_var, KEY_SESSION_ID

from topsailai.context import ctx_manager
from topsailai.workspace.input_tool import (
    get_message,
)

def format_messages(messages):
    for i, msg in enumerate(messages):
        content  = msg["content"]
        content_obj = None
        if content and content[0] in "[{":
            content_obj = json_tool.safe_json_load(content)
        if not content_obj:
            continue

        if msg["role"] == ROLE_USER:
            # only for raw_text
            if isinstance(content_obj, dict) and "raw_text" in content_obj:
                msg["content"] = content_obj["raw_text"]
    return messages

def main():
    """ main entry """
    load_dotenv()

    # message = get_message()
    message = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    message = message.strip() or None

    # team
    team_member_name = os.getenv("TOPSAIL_TEAM_MEMBER_NAME")

    # session
    session_id = os.getenv("SESSION_ID")
    messages_from_session = None
    if session_id:
        if env_tool.is_debug_mode():
            print(f"session_id: {session_id}")
        set_thread_var(KEY_SESSION_ID, session_id)

        messages_from_session = ctx_manager.get_messages_by_session(session_id)
        if not messages_from_session:
            ctx_manager.create_session(session_id, task=message)

    # system prompt
    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)
    if sys_prompt_content:
        sys_prompt_content += f"""
YOU ARE ({team_member_name})

# Output Required
Directly output the content without any formatting.
"""

    llm_model = LLMModel()
    llm_model.content_senders.append(ContentStdout())
    llm_model.max_tokens = max(1500, llm_model.max_tokens)
    llm_model.temperature = min(0.97, llm_model.temperature)

    # debug
    # logger.info("XXXXXX: %s", sys_prompt_content)
    prompt_ctl = PromptBase(sys_prompt_content)
    if messages_from_session:
        prompt_ctl.messages = format_messages(messages_from_session)
        if message:
            prompt_ctl.add_user_message(message)
    else:
        prompt_ctl.new_session(message or None)

    answer = llm_model.chat(prompt_ctl.messages, for_raw=True, for_stream=True)
    if answer:
        symbol_start = os.getenv("TOPSAILAI_SYMBOL_STARTSWITH_ANSWER") or (f"From '{team_member_name}':\n" if team_member_name else "")
        if symbol_start and not answer.startswith(symbol_start.strip()):
            answer = symbol_start + answer
        prompt_ctl.add_assistant_message(answer)

        file_path_result = os.getenv("TOPSAILAI_SAVE_RESULT_TO_FILE")
        if file_path_result:
            with open(file_path_result, encoding='utf-8', mode='w') as fd:
                fd.write(answer)

    return

if __name__ == "__main__":
    main()
