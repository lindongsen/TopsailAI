'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from topsailai.utils import (
    time_tool,
    env_tool,
)


def get_session_id() -> str:
    """
    Generate or retrieve a session ID for the current session.

    Uses SESSION_ID environment variable if set, otherwise generates
    one based on current date and time.

    Returns:
        str: A unique session identifier string.

    Example:
        >>> get_session_id()
        '20260120123456'
    """
    session_id = env_tool.get_session_id() or time_tool.get_current_date(with_t=True).replace('-', '')
    session_id = session_id.replace(':', '')
    return session_id
