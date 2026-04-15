"""
Validation functions for agent_daemon API.

All validation functions raise ValueError with descriptive messages on failure.
"""

import re


def validate_session_id(session_id: str) -> None:
    """
    Validate session_id format.

    Accepts:
    - UUID format (e.g., '550e8400-e29b-41d4-a716-446655440000')
    - Alphanumeric with underscores, hyphens, colons, and periods

    Args:
        session_id: The session ID to validate

    Raises:
        ValueError: If session_id format is invalid
    """
    if not session_id:
        raise ValueError("session_id cannot be empty")

    # Try alphanumeric format (letters, numbers, underscores, hyphens, colons, periods)
    if re.match(r'^[a-zA-Z0-9_:\.-]+$', session_id):
        return

    raise ValueError(
        f"Invalid session_id format: '{session_id}'. "
        "Expected UUID format (e.g., '550e8400-e29b-41d4-a716-446655440000') "
        "or alphanumeric format (e.g., 'session123')"
    )


def validate_message_content(content: str) -> None:
    """
    Validate message content.

    Args:
        content: The message content to validate

    Raises:
        ValueError: If content is empty or invalid
    """
    if not content:
        raise ValueError("message content cannot be empty")
    if not isinstance(content, str):
        raise ValueError("message must be a string")
    if not content.strip():
        raise ValueError("message content cannot be only whitespace")


def validate_role(role: str) -> None:
    """
    Validate message role.

    Args:
        role: The role to validate

    Raises:
        ValueError: If role is not 'user' or 'assistant'
    """
    valid_roles = ["user", "assistant"]
    if role not in valid_roles:
        raise ValueError(
            f"Invalid role: '{role}'. Expected one of: {', '.join(valid_roles)}"
        )


def validate_task_id(task_id: str) -> None:
    """
    Validate task_id format.

    Accepts:
    - UUID format (e.g., '550e8400-e29b-41d4-a716-446655440000')
    - Alphanumeric with underscores, hyphens, colons, and periods

    Args:
        task_id: The task ID to validate

    Raises:
        ValueError: If task_id format is invalid
    """
    if not task_id:
        raise ValueError("task_id cannot be empty")

    # Try alphanumeric format (letters, numbers, underscores, hyphens, colons, periods)
    if re.match(r'^[a-zA-Z0-9_:\.-]+$', task_id):
        return

    raise ValueError(
        f"Invalid task_id format: '{task_id}'. "
        "Expected UUID format or alphanumeric string"
    )


def validate_msg_id(msg_id: str) -> None:
    """
    Validate msg_id format.

    Accepts:
    - UUID format (e.g., '550e8400-e29b-41d4-a716-446655440000')
    - Alphanumeric with underscores and hyphens

    Args:
        msg_id: The message ID to validate

    Raises:
        ValueError: If msg_id format is invalid
    """
    if not msg_id:
        raise ValueError("msg_id cannot be empty")

    # Try alphanumeric format (letters, numbers, underscores, hyphens)
    if re.match(r'^[a-zA-Z0-9_-]+$', msg_id):
        return

    raise ValueError(
        f"Invalid msg_id format: '{msg_id}'. "
        "Expected UUID format or alphanumeric string"
    )
