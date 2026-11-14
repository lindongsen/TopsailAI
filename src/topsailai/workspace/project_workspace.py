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

# Successful lookups are cached per process. A miss is never cached, so a
# session record created later in the same process is still observable. The
# cache is bounded because a long-lived process may resolve many distinct
# sessions, and an unbounded map would grow without limit.
_LOOKUP_CACHE_MAX_ENTRIES = 256
_LOOKUP_CACHE: "OrderedDict[str, str]" = OrderedDict()


def _read_persisted_workspace(session_id: str) -> str | None:
    """Return the persisted project workspace for *session_id*, if any.

    The record is read through the shared context manager, which is the single
    supported way for this layer to reach session storage. The import is lazy
    because ``topsailai.context`` imports this package's siblings, so a
    module-level import would create a cycle.

    Any failure degrades to ``None`` so a caller can keep its own default
    instead of failing the whole startup.
    """
    try:
        from topsailai.context import ctx_manager

        manager = ctx_manager.get_session_manager()
        session = manager.get_session(session_id) if manager is not None else None
        workspace = getattr(session, "project_workspace", None)
    except Exception as exc:
        logger.warning(
            "Cannot read persisted project workspace for session %s: %s",
            session_id, exc,
        )
        return None
    if not isinstance(workspace, str) or not workspace.strip():
        return None
    return workspace


def _lookup_persisted_workspace(session_id: str) -> str | None:
    """Return the cached persisted workspace for *session_id*, if any.

    Only a hit is cached, so a session created later in the same process is
    still observable. The cache is bounded and evicts the least recently used
    entry first.
    """
    if not session_id:
        return None
    cached = _LOOKUP_CACHE.get(session_id)
    if cached is not None:
        _LOOKUP_CACHE.move_to_end(session_id)
        return cached
    workspace = _read_persisted_workspace(session_id)
    if workspace is None:
        return None
    _LOOKUP_CACHE[session_id] = workspace
    _LOOKUP_CACHE.move_to_end(session_id)
    while len(_LOOKUP_CACHE) > _LOOKUP_CACHE_MAX_ENTRIES:
        _LOOKUP_CACHE.popitem(last=False)
    return workspace


def resolve_project_workspace(
    explicit: str | None = None, session_id: str | None = None
) -> str | None:
    """Resolve the project workspace, preferring the environment.

    The order is: explicit argument, ``TOPSAILAI_PROJECT_WORKSPACE``,
    ``TOPSAILAI_PROJECT_FOLDER``, then the persisted session record. Storage is
    consulted only when no environment value is present, so a correctly
    exported environment never pays for a lookup.

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
