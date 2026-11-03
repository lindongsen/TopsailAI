"""Worker session identity initialization.

Author: DawsonLin
"""

import os

from topsailai.utils.env_tool import get_session_id


def initialize_session_id(session_id: str | None = None) -> str | None:
    """Resolve an optional ID and publish a non-empty ID to both runtime aliases.

    None uses the existing environment lookup; an explicit empty string remains
    empty and leaves the environment unchanged. File-only defaults are not
    published as real session identities.
    """
    if session_id is None:
        session_id = get_session_id()
    if session_id:
        os.environ["SESSION_ID"] = session_id
        os.environ["TOPSAILAI_SESSION_ID"] = session_id
    return session_id
