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

from topsailai.utils import env_tool
from topsailai.workspace.llm_shell import get_llm_chat


def main():
    """ main entry """
    llm_chat = get_llm_chat(need_input_message=False)
    if not env_tool.is_debug_mode():
        print(f">>> message:\n{llm_chat.first_message}")
        print(">>> answer:")
    llm_chat.chat()
    print()

if __name__ == "__main__":
    main()
