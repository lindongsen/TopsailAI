#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LLM Chat CLI - Single-turn chat with LLM (Language Model)

This module provides a command-line interface for a single-turn chat session
directly with an LLM (Language Model). Unlike the agent chat which can use
tools, this module provides a simpler interface for direct LLM interaction.

Usage:
    llm_chat.py

Environment Variables:
    SESSION_ID: Optional session identifier for maintaining conversation history
    SYSTEM_PROMPT: Optional file path or content for system prompt

Examples:
    llm_chat.py
    SESSION_ID=my_session llm_chat.py

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-19
"""

import os
import sys

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.utils import env_tool
from topsailai.workspace.llm_shell import get_llm_chat


def main():
    """
    Main entry point for single-turn LLM chat.
    
    This function creates and runs a single-turn chat session directly with
    an LLM (Language Model). It provides a simpler interface compared to
    the agent chat, without tool usage capabilities.
    
    The function:
    1. Gets an LLM chat instance
    2. If not in debug mode, prints the first message and ">>> answer:" prompt
    3. Runs the chat for one interaction
    4. Prints a blank line after completion
    
    Returns:
        None: The LLM's response is printed to stdout during execution
        
    Note:
        - This is a single-turn chat
        - No tools are available in this mode
        - Session history can be maintained via SESSION_ID environment variable
        - In debug mode, the first message is not printed
    """
    """ main entry """
    llm_chat = get_llm_chat(need_input_message=False)
    if not env_tool.is_debug_mode():
        print(f">>> message:\n{llm_chat.first_message}")
        print(">>> answer:")
    llm_chat.chat()
    print()

if __name__ == "__main__":
    main()
