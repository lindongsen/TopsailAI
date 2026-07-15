"""Helpers for resolving session metadata from external commands."""

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

from cli_topsailai.project_scope import load_project_workspace_lookup


# Timeout for each external session-info lookup, in seconds.
_SESSION_INFO_TIMEOUT = 5

# Maximum number of concurrent subprocess lookups per refresh.
_MAX_SESSION_INFO_WORKERS = 8

# Sentinel used to distinguish "not cached" from "cached None".
_MISSING = object()


class _SessionInfoCache:
    """Thread-safe cache mapping session_id to resolved session metadata."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Tuple[Optional[str], Optional[str]]] = {}

    def get(self, session_id: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
        """Return cached value or _MISSING if not present."""
        with self._lock:
            value = self._data.get(session_id, _MISSING)
        return value

    def set(
        self, session_id: str, value: Tuple[Optional[str], Optional[str]]
    ) -> None:
        """Store value in cache."""
        with self._lock:
            self._data[session_id] = value


# Module-level cache shared across refreshes and threads.
_SESSION_INFO_CACHE = _SessionInfoCache()


class _LookupResult:
    """Internal result wrapper to distinguish success from transient failure."""

    __slots__ = ("name", "project_workspace", "success")

    def __init__(
        self,
        name: Optional[str],
        project_workspace: Optional[str],
        success: bool,
    ) -> None:
        self.name = name
        self.project_workspace = project_workspace
        self.success = success


def _get_session_info(session_id: str) -> _LookupResult:
    """Return session metadata for *session_id* using ``topsailai_session_info``.

    Empty or whitespace-only names are treated as successful lookups but are
    not cached by the caller, so the next refresh will retry them.  Transient
    failures (timeout, missing command, non-zero exit, invalid JSON, etc.)
    return ``success=False`` so the caller can avoid poisoning the cache.
    """
    try:
        result = subprocess.run(
            ["topsailai_session_info", "--json", session_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_SESSION_INFO_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return _LookupResult(None, None, False)

    if result.returncode != 0 or not result.stdout:
        return _LookupResult(None, None, False)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _LookupResult(None, None, False)

    if not isinstance(data, dict):
        return _LookupResult(None, None, False)

    name = data.get("session_name")
    if isinstance(name, str):
        name = name.strip() or None

    project_workspace = data.get("project_workspace")
    if not isinstance(project_workspace, str) or not project_workspace.strip():
        project_workspace = None

    return _LookupResult(name, project_workspace, True)


def _fetch_missing_session_info(session_ids: List[str]) -> None:
    """Fetch session metadata concurrently and cache only non-empty results.

    Each lookup runs in its own thread so slow subprocess calls do not block
    each other.  Transient failures are not cached, allowing retries on the
    next refresh.  Empty/whitespace-only names are also not cached, but a
    valid ``project_workspace`` without a name is still cached so the
    workspace can be reused.
    """
    if not session_ids:
        return

    max_workers = min(_MAX_SESSION_INFO_WORKERS, len(session_ids))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(_get_session_info, sid): sid for sid in session_ids
        }
        for future in as_completed(future_to_id):
            session_id = future_to_id[future]
            try:
                lookup = future.result()
            except Exception:
                continue
            if not lookup.success:
                continue
            # Cache when we have at least one useful piece of metadata.
            if lookup.name or lookup.project_workspace:
                _SESSION_INFO_CACHE.set(
                    session_id, (lookup.name, lookup.project_workspace)
                )


def enrich_files_with_session_names(files: List[dict]) -> None:
    """Add ``session_name`` and ``project_workspace`` keys to each file dict.

    Lookups are deduplicated and cached so the same session ID is only queried
    once across the process lifetime.  Missing IDs are fetched concurrently via
    a thread pool.  Transient failures are not cached, so the next refresh will
    retry them.  Temporary sessions (``(temp)``) and files without a session ID
    are assigned ``None`` and skipped entirely.

    The ``project_workspace`` value is resolved from ``topsailai_session_info``
    when possible because that reflects the workspace stored in the session
    record (the authoritative value).  If the session cannot be queried, the
    value falls back to the most recent entry in ``.project_history.jsonl``.
    """
    if not files:
        return

    distinct_ids: list[str] = []
    seen: set[str] = set()
    for file_info in files:
        session_id = file_info.get("session_id")
        if session_id is None or session_id == "(temp)" or session_id == "":
            file_info["session_name"] = None
            file_info["project_workspace"] = None
            continue
        if session_id not in seen:
            seen.add(session_id)
            distinct_ids.append(session_id)

    missing_ids = [
        sid for sid in distinct_ids if _SESSION_INFO_CACHE.get(sid) is _MISSING
    ]
    if missing_ids:
        _fetch_missing_session_info(missing_ids)

    # Only load history fallback when there are real sessions to enrich.
    workspace_lookup = load_project_workspace_lookup() if distinct_ids else {}
    for file_info in files:
        session_id = file_info.get("session_id")
        if session_id is None or session_id == "(temp)" or session_id == "":
            file_info["session_name"] = None
            file_info["project_workspace"] = None
            continue
        cached = _SESSION_INFO_CACHE.get(session_id)
        if cached is _MISSING:
            name = None
            project_workspace = None
        else:
            name, project_workspace = cached

        file_info["session_name"] = name
        # Prefer the authoritative session record; fall back to history.
        if project_workspace:
            file_info["project_workspace"] = project_workspace
        else:
            file_info["project_workspace"] = workspace_lookup.get(session_id)
