'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from topsailai.context import common as ctx_common
from topsailai.ai_team.constants import DEFAULT_HEAD_TAIL_OFFSET
from topsailai.utils import env_tool


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
    return ctx_common.get_session_id()


def get_session_head_tail_offset(default: int = DEFAULT_HEAD_TAIL_OFFSET) -> int:
    """
    Resolve the session head/tail offset for team agents.

    Precedence:
        1. TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET (if set and integer value >= 0)
        2. TOPSAILAI_SESSION_HEAD_TAIL_OFFSET (if set and integer value >= 0)
        3. The provided default value

    Empty or non-integer environment values are treated as unset and fall back
    to the next rule.

    Args:
        default: Value to use when neither environment variable is set to a
            valid non-negative integer. Defaults to DEFAULT_HEAD_TAIL_OFFSET.

    Returns:
        int: The resolved head/tail offset.

    Example:
        >>> get_session_head_tail_offset()
        7
    """
    team_offset = env_tool.EnvReaderInstance.get(
        "TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET",
        default=None,
        formatter=int,
    )
    if team_offset is not None and team_offset >= 0:
        return team_offset

    global_offset = env_tool.EnvReaderInstance.get(
        "TOPSAILAI_SESSION_HEAD_TAIL_OFFSET",
        default=None,
        formatter=int,
    )
    if global_offset is not None and global_offset >= 0:
        return global_offset

    return default
