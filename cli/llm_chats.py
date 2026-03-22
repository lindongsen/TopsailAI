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

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.workspace.llm_shell import get_llm_chat
from topsailai.workspace.input_tool import input_message

def main():
    """ main entry """
    llm_chat = get_llm_chat()
    message = ""
    max_count = 100
    while True:
        max_count -= 1
        print(">>> LLM Answer:")
        llm_chat.chat(message)
        print()
        if max_count == 0:
            break
        message = input_message()

    return


if __name__ == "__main__":
    main()
