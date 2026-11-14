'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-14
  Purpose: Resolve the project workspace for a session, preferring the
           environment and falling back to the persisted session record.
'''

import logging
import os
from collections import OrderedDict

logger = logging.getLogger(__name__)

PROJECT_WORKSPACE_ENV = "TOPSAILAI_PROJECT_WORKSPACE"
PROJECT_FOLDER_ENV = "TOPSAILAI_PROJECT_FOLDER"

# Successful lookups are cached per process and per connection string. A miss is
# never cached, so a session row created later in the same process is still
# observable. The cache is bounded because a long-lived process may resolve many
# distinct sessions, and an unbounded map would grow without limit.
_LOOKUP_CACHE_MAX_ENTRIES = 256
_LOOKUP_CACHE: "OrderedDict[tuple[str, str], str]" = OrderedDict()


def _session_database_conn() -> str | None:
    """Return an absolute SQLite connection string for the session database.

    The shared default connection string is relative, so it resolves against the
    process working directory. Several entry points change that directory to the
    source tree, where an unrelated empty database exists, so the path is
    composed from ``TOPSAILAI_HOME`` instead. A missing file yields ``None``
    because opening it would silently create an empty database and turn a
    lookup miss into a false negative.
    """
    from topsailai.workspace.folder_constants import TOPSAILAI_HOME

    path = os.path.join(TOPSAILAI_HOME, "memory.db")
    if not os.path.isfile(path):
        return None
    return f"sqlite:///{path}"


def _lookup_persisted_workspace(session_id: str) -> str | None:
    """Return the persisted project workspace for *session_id*, if any.

    Any failure degrades to ``None`` so a caller can keep its own default
    instead of failing the whole startup.
    """
    if not session_id:
        return None
    conn = _session_database_conn()
    if conn is None:
        return None
    cache_key = (session_id, conn)
    if cache_key in _LOOKUP_CACHE:
        return _LOOKUP_CACHE[cache_key]
    try:
        from topsailai.context import ctx_manager

        manager = ctx_manager.get_session_manager(default_conn=conn)
        session = manager.get_session(session_id)
    except Exception as exc:
        logger.warning(
            "Cannot read persisted project workspace for session %s: %s",
            session_id, exc,
        )
        return None
    workspace = getattr(session, "project_workspace", None)
    if not isinstance(workspace, str) or not workspace:
        return None
    _LOOKUP_CACHE[cache_key] = workspace
    _LOOKUP_CACHE.move_to_end(cache_key)
    while len(_LOOKUP_CACHE) > _LOOKUP_CACHE_MAX_ENTRIES:
        _LOOKUP_CACHE.popitem(last=False)
    return workspace


def resolve_project_workspace(
    explicit: str | None = None, session_id: str | None = None
) -> str | None:
    """Resolve the project workspace, preferring the environment.

    The order is: explicit argument, ``TOPSAILAI_PROJECT_WORKSPACE``,
    ``TOPSAILAI_PROJECT_FOLDER``, then the persisted session record. The
    database is consulted only when no environment value is present, so a
    correctly exported environment never pays for a lookup.

    Args:
        explicit: Value supplied by the caller, which always wins.
        session_id: Session identity used for the fallback lookup. When omitted
            the runtime session identity is used.

    Returns:
        The resolved workspace path, or ``None`` when nothing is available.
    """
    if explicit:
        return explicit
    for name in (PROJECT_WORKSPACE_ENV, PROJECT_FOLDER_ENV):
        value = os.getenv(name)
        if value:
            return value
    if session_id is None:
        from topsailai.utils import env_tool

        session_id = env_tool.get_session_id()
    return _lookup_persisted_workspace(session_id or "")
