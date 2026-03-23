#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Agent Chat CLI - Single-turn chat with AI agent

This module provides a command-line interface for a single-turn chat session
with an AI agent. The agent is configured with the ability to use tools but
with the "agent_tool" disabled for this specific use case.

Usage:
    agent_chat.py

Environment Variables:
    SESSION_ID: Optional session identifier for maintaining conversation history
    SYSTEM_PROMPT: Optional file path or content for system prompt

Examples:
    agent_chat.py
    SESSION_ID=my_session agent_chat.py

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-19
"""

import sys
import os

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.workspace.agent_shell import get_agent_chat


def main():
    """
    Main entry point for single-turn agent chat.
    
    This function creates and runs a single-turn chat session with an AI agent.
    The agent has access to various tools but the "agent_tool" is disabled
    to prevent recursive agent calls.
    
    The function:
    1. Gets an agent chat instance with agent_tool disabled
    2. Runs the chat for exactly one iteration (single-turn)
    3. Returns the agent's response
    
    Returns:
        None: The agent's response is printed to stdout during execution
        
    Note:
        - This is a single-turn chat (times=1)
        - The agent_tool is disabled to prevent nested agent calls
        - Session history can be maintained via SESSION_ID environment variable
    """
    """ main entry """
    get_agent_chat(disabled_tools=["agent_tool"]).run(times=1)

if __name__ == "__main__":
    main()
