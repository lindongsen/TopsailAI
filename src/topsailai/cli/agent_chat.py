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

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
import os

import _import_topsailai

os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)
if TYPE_CHECKING:
    from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy, SummaryPreparationRequest

from topsailai.workspace.agent_shell import get_agent_chat
from topsailai.workspace.hooks_application import HooksApplication


def main(*, request: SummaryPreparationRequest | None = None, trust_policy: ConfiguredTrustPolicy | None = None, temp_root: str | None = None):
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
    with HooksApplication(request=request, trust_policy=trust_policy, temp_root=temp_root) as application:

        get_agent_chat(summary_hooks_executor=application.executor, disabled_tools=["agent_tool"]).run(times=1)

if __name__ == "__main__":
    main()
