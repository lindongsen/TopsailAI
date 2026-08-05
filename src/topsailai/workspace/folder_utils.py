"""
Folder path utilities for TopsailAI.

This module provides helper functions that build file and socket paths from
the static folder constants defined in ``topsailai.workspace.folder_constants``.
Keeping these functions separate keeps ``folder_constants.py`` static-variable-only.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
"""

import os

from topsailai.utils import env_tool


def resolve_session_id_for_files(ctx_runtime_data=None) -> str:
    """Resolve the session identifier used for session-scoped file paths.

    Many runtime files (control sockets, interrupt flags, Agent2LLM inject
    files) are named with the session id. This helper centralizes the fallback
    chain so every file follows the same convention:

    1. ``ctx_runtime_data.session_id`` when a context runtime data object is
       provided and has a non-empty session id.
    2. ``env_tool.get_session_id()`` from the runtime environment.
    3. The literal ``"topsailai"`` as the final default.

    Args:
        ctx_runtime_data: Optional context runtime data object that may expose
            a ``session_id`` attribute. When omitted, the function falls back
            directly to the environment/default value.

    Returns:
        A non-empty session id string suitable for file and socket path names.
    """
    if ctx_runtime_data is not None:
        session_id = getattr(ctx_runtime_data, "session_id", None)
        if session_id:
            return session_id
    return env_tool.get_session_id() or "topsailai"


def get_interrupt_flag_path(task_folder: str, session_id: str, pid: int) -> str:
    """Return the absolute hard-interrupt flag path for a session process."""
    return os.path.abspath(
        os.path.join(
            task_folder,
            f"{session_id}.{pid}.session.agent2llm_interrupt.flag",
        )
    )


def get_control_socket_path(task_folder: str, session_id: str, pid: int) -> str:
    """Return the absolute UDS control socket path for a session process."""
    return os.path.abspath(
        os.path.join(
            task_folder,
            f"{session_id}.{pid}.session.sock",
        )
    )
