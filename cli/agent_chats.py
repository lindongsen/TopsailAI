#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Agent Chats CLI - Multi-turn chat with AI agent

This module provides a command-line interface for a multi-turn chat session
with an AI agent. Unlike agent_chat.py which runs for a single turn, this
module allows continuous conversation until the user exits.

Usage:
    agent_chats.py

Environment Variables:
    SESSION_ID: Optional session identifier for maintaining conversation history
    SYSTEM_PROMPT: Optional file path or content for system prompt

Examples:
    agent_chats.py
    SESSION_ID=my_session agent_chats.py

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

from topsailai.workspace.agent_shell import get_agent_chat


def main():
    """
    Main entry point for multi-turn agent chat.
    
    This function creates and runs a continuous chat session with an AI agent.
    The agent has access to various tools but the "agent_tool" is disabled
    to prevent recursive agent calls.
    
    The function:
    1. Gets an agent chat instance with agent_tool disabled
    2. Runs the chat in continuous mode (no turn limit)
    3. Allows the user to have an interactive conversation
    
    Returns:
        None: The agent's responses are printed to stdout during execution
        
    Note:
        - This is a multi-turn chat (no turn limit, runs until exit)
        - The agent_tool is disabled to prevent nested agent calls
        - Session history can be maintained via SESSION_ID environment variable
        - User can exit by typing 'exit', 'quit', or Ctrl+C
    """
    """ main entry """
    get_agent_chat(disabled_tools=["agent_tool"]).run()

if __name__ == "__main__":
    main()
