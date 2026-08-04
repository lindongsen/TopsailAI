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
