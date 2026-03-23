#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LLM Chats CLI - Multi-turn chat with LLM (Language Model)

This module provides a command-line interface for a multi-turn chat session
directly with an LLM (Language Model). Unlike llm_chat.py which runs for a
single turn, this module allows continuous conversation with the LLM.

Usage:
    llm_chats.py

Environment Variables:
    SESSION_ID: Optional session identifier for maintaining conversation history
    SYSTEM_PROMPT: Optional file path or content for system prompt

Examples:
    llm_chats.py
    SESSION_ID=my_session llm_chats.py

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

from topsailai.workspace.llm_shell import get_llm_chat
from topsailai.workspace.input_tool import input_message

def main():
    """
    Main entry point for multi-turn LLM chat.
    
    This function creates and runs a continuous chat session directly with
    an LLM (Language Model). It allows for multiple back-and-forth exchanges
    with a maximum of 100 turns.
    
    The function:
    1. Gets an LLM chat instance
    2. Runs a loop for up to 100 iterations
    3. In each iteration:
       - Prints ">>> LLM Answer:" prompt
       - Gets the LLM's response with the current message
       - Prints a blank line
       - If max iterations reached, breaks the loop
       - Otherwise, gets user input for the next message
    4. Returns None after the conversation ends
    
    Returns:
        None: The LLM's responses are printed to stdout during execution
        
    Note:
        - This is a multi-turn chat with a maximum of 100 iterations
        - No tools are available in this mode
        - Session history can be maintained via SESSION_ID environment variable
        - User can exit by pressing Ctrl+C
    """
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
