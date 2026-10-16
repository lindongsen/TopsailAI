"""Helpers for resolving session metadata from external commands."""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

from cli_topsailai.colors import Colors
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

    def set_if_absent(
        self, session_id: str, value: Tuple[Optional[str], Optional[str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Store value only when *session_id* is absent and return the winner."""
        with self._lock:
            existing = self._data.get(session_id, _MISSING)
            if existing is _MISSING:
                self._data[session_id] = value
                return value
            return existing


# Module-level cache shared across refreshes and threads.
_SESSION_INFO_CACHE = _SessionInfoCache()


def has_complete_cached_session_info(session_id: str) -> bool:
    """Return whether cached display metadata is complete for *session_id*."""
    if (
        not isinstance(session_id, str)
        or not session_id.strip()
        or session_id == "(temp)"
    ):
        return False

    cached = _SESSION_INFO_CACHE.get(session_id)
    if cached is _MISSING or not isinstance(cached, tuple) or len(cached) != 2:
        return False
    name, project_workspace = cached
    return (
        isinstance(name, str)
        and bool(name.strip())
        and isinstance(project_workspace, str)
        and bool(project_workspace.strip())
        and os.path.isabs(project_workspace)
    )


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


def _completed_meta_snapshot(file_info: dict) -> Optional[Tuple[str, int, str, Optional[str]]]:
    """Return a valid scan-local completed metadata snapshot for a row."""
    snapshot = file_info.get("_completed_session_meta")
    if not isinstance(snapshot, tuple) or len(snapshot) != 4:
        return None
    session_id, parent_pid, name, project_workspace = snapshot
    row_session_id = file_info.get("session_id")
    if (
        not isinstance(session_id, str)
        or not session_id
        or session_id != row_session_id
        or type(parent_pid) is not int
        or parent_pid <= 0
        or not isinstance(name, str)
        or not name.strip()
    ):
        return None
    row_pid = file_info.get("pid")
    if file_info.get("is_task"):
        if file_info.get("session_pid") != parent_pid:
            return None
    elif row_pid != parent_pid:
        return None
    if project_workspace is not None and (
        not isinstance(project_workspace, str)
        or not project_workspace.strip()
        or not os.path.isabs(project_workspace)
    ):
        project_workspace = None
    return session_id, parent_pid, name.strip(), project_workspace


def enrich_files_with_session_names(files: List[dict]) -> None:
    """Add session names and workspaces while reusing completed scan metadata."""
    if not files:
        return

    distinct_ids: list[str] = []
    seen: set[str] = set()
    snapshots: dict[int, Tuple[str, int, str, Optional[str]]] = {}
    query_required: set[str] = set()
    for file_info in files:
        session_id = file_info.get("session_id")
        if session_id is None or session_id == "(temp)" or session_id == "":
            file_info["session_name"] = None
            file_info["project_workspace"] = None
            continue
        if session_id not in seen:
            seen.add(session_id)
            distinct_ids.append(session_id)

        snapshot = _completed_meta_snapshot(file_info)
        if snapshot is not None:
            snapshots[id(file_info)] = snapshot
            _SESSION_INFO_CACHE.set_if_absent(
                session_id, (snapshot[2], snapshot[3])
            )

    for file_info in files:
        session_id = file_info.get("session_id")
        if session_id is None or session_id == "(temp)" or session_id == "":
            continue
        snapshot = snapshots.get(id(file_info))
        cached = _SESSION_INFO_CACHE.get(session_id)
        cached_path = (
            cached[1]
            if cached is not _MISSING and isinstance(cached[1], str)
            and cached[1].strip()
            else None
        )
        if snapshot is not None:
            if cached_path is None and snapshot[3] is None:
                query_required.add(session_id)
        elif cached is _MISSING:
            query_required.add(session_id)

    if query_required:
        _fetch_missing_session_info(
            [session_id for session_id in distinct_ids if session_id in query_required]
        )

    workspace_lookup = load_project_workspace_lookup() if distinct_ids else {}
    for file_info in files:
        session_id = file_info.get("session_id")
        if session_id is None or session_id == "(temp)" or session_id == "":
            continue
        snapshot = snapshots.get(id(file_info))
        cached = _SESSION_INFO_CACHE.get(session_id)
        if cached is _MISSING:
            cached_name = None
            cached_path = None
        else:
            cached_name, cached_path = cached

        if snapshot is not None:
            _session_id, _pid, name, meta_path = snapshot
            file_info["session_name"] = name
            project_workspace = cached_path or meta_path
        else:
            file_info["session_name"] = cached_name
            project_workspace = cached_path
        file_info["project_workspace"] = (
            project_workspace or workspace_lookup.get(session_id)
        )


def _is_pid_alive(pid: Optional[int]) -> bool:
    """Return True if *pid* refers to a currently running process.

    On Linux, the existence of ``/proc/{pid}`` is checked first because it
    is the authoritative, signal-free way to determine whether a process is
    alive.  ``os.kill(pid, 0)`` is used only as a fallback when ``/proc`` is
    unavailable or is not a directory.  On non-Linux platforms ``os.kill`` is
    used directly.
    """
    if pid is None:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False

    if sys.platform.startswith("linux"):
        if os.path.isdir("/proc"):
            return os.path.isdir(f"/proc/{pid}")
        # /proc is unavailable; fall back to os.kill.

    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _has_real_session_id(file_info: dict) -> bool:
    """Return True when *file_info* has a real (non-temp) session ID."""
    session_id = file_info.get("session_id")
    if session_id is None:
        return False
    if not isinstance(session_id, str):
        return False
    if session_id == "(temp)" or session_id.strip() == "":
        return False
    return True


def _is_unnamed_running_session(file_info: dict) -> bool:
    """Return True when *file_info* is a running session with no name.

    A file matches when all of the following hold:
      1. It has a real session ID (not empty, not ``(temp)``, not None).
      2. Its PID is alive.
      3. Its ``session_name`` is missing or empty.
    """
    if not _has_real_session_id(file_info):
        return False
    session_name = file_info.get("session_name")
    if isinstance(session_name, str) and session_name.strip():
        return False
    return _is_pid_alive(file_info.get("pid"))


def _fetch_session_names(session_ids: List[str]) -> dict[str, str]:
    """Fetch non-empty session names concurrently.

    Returns a mapping from session ID to session name.  Lookups that fail or
    return an empty/whitespace-only name are omitted.  Failures are silent so
    the caller can continue refreshing the list without blocking.
    """
    if not session_ids:
        return {}

    results: dict[str, str] = {}
    max_workers = min(_MAX_SESSION_INFO_WORKERS, len(session_ids))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {}
        for sid in session_ids:
            print(f"{Colors.DIM}Querying session info for session: {sid}{Colors.RESET}")
            sys.stdout.flush()
            future_to_id[executor.submit(_get_session_info, sid)] = sid
        for future in as_completed(future_to_id):
            session_id = future_to_id[future]
            try:
                lookup = future.result()
            except Exception:
                continue
            if lookup.success and lookup.name:
                results[session_id] = lookup.name
    return results


def enrich_running_unnamed_sessions(files: List[dict]) -> None:
    """Backfill session names for running sessions that currently have none.

    When the workspace task list is refreshed, running sessions may already
    have received a display name from the agent.  This function queries
    ``topsailai_session_info`` for sessions that meet all of the following
    criteria:

      1. A real session ID exists (not empty, not ``(temp)``, not None).
      2. The embedded PID is alive.
      3. The ``session_name`` field is missing or empty.

    Lookups are deduplicated and run concurrently.  Failures are silent and
    do not block the refresh.  Only the ``session_name`` field is updated;
    ``project_workspace`` is left untouched because it is already resolved by
    :func:`enrich_files_with_session_names`.
    """
    if not files:
        return

    targets = [f for f in files if _is_unnamed_running_session(f)]
    if not targets:
        return

    distinct_ids: list[str] = []
    seen: set[str] = set()
    for file_info in targets:
        session_id = file_info["session_id"]
        if session_id not in seen:
            seen.add(session_id)
            distinct_ids.append(session_id)

    names = _fetch_session_names(distinct_ids)
    for file_info in targets:
        session_id = file_info["session_id"]
        if session_id in names:
            file_info["session_name"] = names[session_id]
