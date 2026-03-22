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

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.ai_base.prompt_base import ROLE_USER
from topsailai.ai_team.role import (
    get_member_name,
    get_member_prompt,
)
from topsailai.utils import (
    env_tool,
    json_tool,
)
from topsailai.workspace.llm_shell import get_llm_chat


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
    # team
    team_member_name = get_member_name()

    # member prompt
    member_prompt = get_member_prompt(team_member_name) + """
# Output Required
Directly output the content without any formatting.
"""

    # llm chat
    llm_chat = get_llm_chat(
        more_prompt=member_prompt,
        need_input_message=False,
        need_print_session=env_tool.is_debug_mode(),
        func_formatter_messages=format_messages,
    )

    answer = llm_chat.chat()
    if answer:
        symbol_start = os.getenv("TOPSAILAI_SYMBOL_STARTSWITH_ANSWER") or (f"From '{team_member_name}':\n" if team_member_name else "")
        if symbol_start and not answer.startswith(symbol_start.strip()):
            answer = symbol_start + answer

        file_path_result = os.getenv("TOPSAILAI_SAVE_RESULT_TO_FILE")
        if file_path_result:
            with open(file_path_result, encoding='utf-8', mode='w') as fd:
                fd.write(answer)

    return

if __name__ == "__main__":
    main()
