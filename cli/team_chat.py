#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Team Chat CLI - Chat with AI team members using LLM

This module provides a command-line interface for team chat functionality,
allowing users to interact with AI team members through an LLM-based chat system.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-19

Environment Variables:
    SESSION_ID: Optional session identifier for maintaining conversation history
    SYSTEM_PROMPT: Optional file path or content for system prompt
"""

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
    """
    Format messages for processing by extracting raw text from JSON content.
    
    This function processes messages in the conversation history, extracting
    the 'raw_text' field from JSON-formatted content when available.
    
    Args:
        messages (list): List of message dictionaries with 'role' and 'content' fields.
        
    Returns:
        list: Processed messages with raw text extracted from JSON content.
        
    Example:
        >>> msgs = [{"role": "user", "content": '{"raw_text": "Hello"}'}]
        >>> format_messages(msgs)
        [{"role": "user", "content": "Hello"}]
    """
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
    """
    Main entry point for team chat functionality.
    
    Initializes an LLM-based chat session with a team member, processes
    the conversation, and optionally saves the result to a file.
    
    The function:
    1. Gets the current team member name
    2. Creates a member prompt with output requirements
    3. Initializes the LLM chat with appropriate settings
    4. Processes the chat response and optionally saves it
    
    Environment Variables Used:
        TOPSAILAI_SYMBOL_STARTSWITH_ANSWER: Optional prefix for answer output
        TOPSAILAI_SAVE_RESULT_TO_FILE: Optional file path to save the result
        
    Returns:
        None
        
    Raises:
        Exception: Any exceptions from chat processing are handled internally
    """
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
