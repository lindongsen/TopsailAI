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
from datetime import datetime
from typing import Mapping, Optional, Tuple

import _import_topsailai

os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)
from topsailai.ai_base.constants import (
    AGENT_ROLE_MANAGER,
)
from topsailai.utils import env_tool
from topsailai.workspace.agent_shell import get_agent_chat

from cli_topsailai.colors import print_info

# Environment aliases that carry the session identity. Both are published
# together so the agent library, the session record, the session stdout
# filename, and any child process observe one identity.
SESSION_ID_ENV_KEYS = ("TOPSAILAI_SESSION_ID", "SESSION_ID")


def _generate_session_id() -> str:
    """Return a fresh session identity for a chat started without one.

    The identity is the compact local timestamp ``YYYYMMDDHHMMSS``, the same
    format the launcher already uses, so chat sessions sort by creation time
    and stay recognizable in the workspace session list.
    """
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _resolve_session_id(
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[str, bool]:
    """Resolve the effective session identity for this chat process.

    Presence decides, not content. An alias that is absent from the
    environment means "not configured", so a new identity is generated. An
    alias that is present is used verbatim, and a present value that carries no
    identity (empty or whitespace-only) means "run without a session", which is
    how a caller opts out of session persistence.

    The aliases are consulted in ``SESSION_ID_ENV_KEYS`` order, so a chat
    started from a launched session keeps that session's identity. An absent
    alias never stops the search, and a present alias never falls through to
    the next one, so the first configured alias always decides.

    Args:
        environ: Environment mapping to read. Defaults to ``os.environ``.

    Returns:
        Tuple of (session_id, generated). ``generated`` is True only when this
        call created the identity.
    """
    env = os.environ if environ is None else environ
    for key in SESSION_ID_ENV_KEYS:
        if key not in env:
            continue
        value = env[key]
        if value.strip():
            return value, False
        return "", False
    return _generate_session_id(), True


def _publish_session_id(session_id: str) -> None:
    """Export one session identity through both supported environment aliases."""
    for key in SESSION_ID_ENV_KEYS:
        os.environ[key] = session_id


def _library_prints_session() -> bool:
    """Return True when the agent library prints the session line itself.

    ``get_agent_chat`` prints ``session_id: ...`` only when it resolves
    ``need_print_session`` to true, which requires interactive mode and a
    non-debug run. Reusing the library's own predicates keeps this entry point
    from duplicating or suppressing that line.
    """
    return env_tool.is_interactive_mode() and not env_tool.is_debug_mode()


def main():
    """
    Main entry point for multi-turn agent chat.
    
    This function creates and runs a continuous chat session with an AI agent.
    The agent has access to various tools but the "agent_tool" is disabled
    to prevent recursive agent calls.
    
    The function:
    1. Resolves the session identity, generating one when none is configured
    2. Gets an agent chat instance with agent_tool disabled
    3. Runs the chat in continuous mode (no turn limit)
    4. Allows the user to have an interactive conversation
    
    Returns:
        None: The agent's responses are printed to stdout during execution
        
    Note:
        - This is a multi-turn chat (no turn limit, runs until exit)
        - The agent_tool is disabled to prevent nested agent calls
        - Session history can be maintained via SESSION_ID environment variable
        - A session ID is generated automatically when none is configured
        - User can exit by typing 'exit', 'quit', or Ctrl+C
    """
    """ main entry """
    session_id, generated = _resolve_session_id()
    _publish_session_id(session_id)
    if generated and not _library_prints_session():
        # The library prints the session line itself only in interactive,
        # non-debug runs. Announce the generated identity in the remaining
        # cases so it is never silently invented, and never printed twice.
        print_info(f"session_id: {session_id}")
    get_agent_chat(
        disabled_tools=["agent_tool"],
        agent_role=AGENT_ROLE_MANAGER,
        session_id=session_id,
    ).run()

if __name__ == "__main__":
    main()
