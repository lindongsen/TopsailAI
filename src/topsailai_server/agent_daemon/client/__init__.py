"""
Agent Daemon Client Package

This package provides client modules for interacting with the agent_daemon API.
Each module contains client classes for specific API endpoints.

Modules:
    - base: BaseClient class with common utilities
    - session: SessionClient for session operations
    - session_do: do_xxx functions for session CLI operations
    - message: MessageClient for message operations
    - message_do: do_xxx functions for message CLI operations
    - task: TaskClient for task operations
    - task_do: do_xxx functions for task CLI operations

Usage:
    from topsailai_server.agent_daemon.client import (
        BaseClient,
        SessionClient,
        MessageClient,
        TaskClient,
    )

    # Or import do_xxx functions
    from topsailai_server.agent_daemon.client.session_do import (
        do_client_health,
        do_client_list_sessions,
        do_client_get_session,
        do_client_delete_sessions,
        do_client_process_session,
    )
"""

from topsailai_server.agent_daemon.client.base import BaseClient, SPLIT_LINE, APIError
from topsailai_server.agent_daemon.client.session import SessionClient
from topsailai_server.agent_daemon.client.message import MessageClient
from topsailai_server.agent_daemon.client.task import TaskClient

# Import do_xxx functions
from topsailai_server.agent_daemon.client.session_do import (
    do_client_health,
    do_client_list_sessions,
    do_client_get_session,
    do_client_delete_sessions,
    do_client_process_session,
    add_session_parsers,
)
from topsailai_server.agent_daemon.client.message_do import (
    do_client_send_message,
    do_client_get_messages,
    add_message_parsers,
)
from topsailai_server.agent_daemon.client.task_do import (
    do_client_set_task_result,
    do_client_get_tasks,
    add_task_parsers,
)

__all__ = [
    # Base classes
    "BaseClient",
    "SPLIT_LINE",
    "APIError",
    # Client classes
    "SessionClient",
    "MessageClient",
    "TaskClient",
    # Session do functions
    "do_client_health",
    "do_client_list_sessions",
    "do_client_get_session",
    "do_client_delete_sessions",
    "do_client_process_session",
    "add_session_parsers",
    # Message do functions
    "do_client_send_message",
    "do_client_get_messages",
    "add_message_parsers",
    # Task do functions
    "do_client_set_task_result",
    "do_client_get_tasks",
    "add_task_parsers",
]

__version__ = "1.0.0"
