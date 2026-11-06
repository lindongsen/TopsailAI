"""Helpers for resolving session metadata from external commands."""

import json
import os
import signal
import subprocess
import sys
import threading
from typing import List, Optional, Tuple

from cli_topsailai.project_scope import load_project_workspace_lookup

# Timeout for each external session-info lookup, in seconds.
_SESSION_INFO_TIMEOUT = 5

# Maximum time to wait for a killed process group to be reaped, in seconds.
_SESSION_INFO_REAP_TIMEOUT = 2

# External command that resolves many session identifiers in one invocation.
_SESSIONS_INFO_COMMAND = "topsailai_sessions_info"

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


def _kill_process_group(process: "subprocess.Popen[str]") -> None:
    """Terminate *process* and every process in its process group.

    The CLI dispatcher wraps the script in ``uv run``, so the interpreter that
    actually burns CPU is a grandchild of this process.  Killing only the
    direct child leaves that grandchild running as an orphan, which is why a
    timed-out lookup kept consuming CPU after the refresh had already finished.
    ``start_new_session=True`` makes the child a process-group leader, so the
    whole tree can be signalled at once.

    A process-group ID cannot be reused while the group still has members, so
    signalling ``process.pid`` as the group ID stays safe even when the direct
    child already exited; an empty group raises ``ProcessLookupError`` and is
    treated as already terminated.  The group signal is therefore attempted
    unconditionally, because a reaped leader can still have live descendants.

    ``os.killpg`` and ``signal.SIGKILL`` are POSIX-only, so platforms without
    them fall back to killing the direct child only.
    """
    killpg = getattr(os, "killpg", None)
    sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
    if killpg is not None:
        try:
            killpg(process.pid, sigkill)
        except OSError:
            # The group is already gone or cannot be signalled; fall back to
            # the direct child so a survivor is never left unattended.
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=_SESSION_INFO_REAP_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def _run_lookup_command(cmd: List[str]) -> "subprocess.CompletedProcess[str]":
    """Run *cmd* in its own process group and kill the group on timeout.

    Raises ``subprocess.TimeoutExpired`` only after the whole process group has
    been terminated, so the caller can treat the timeout as a transient failure
    without leaving orphaned children behind.
    """
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=_SESSION_INFO_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        raise
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def _parse_session_record(record: object) -> Optional[_LookupResult]:
    """Convert one JSON session record into a normalized lookup result."""
    if not isinstance(record, dict):
        return None

    name = record.get("session_name")
    if isinstance(name, str):
        name = name.strip() or None

    project_workspace = record.get("project_workspace")
    if not isinstance(project_workspace, str) or not project_workspace.strip():
        project_workspace = None

    return _LookupResult(name, project_workspace, True)


def _get_sessions_info(session_ids: List[str]) -> dict[str, _LookupResult]:
    """Return metadata for *session_ids* from one ``topsailai_sessions_info`` call.

    A single invocation resolves every identifier, so the cost of a refresh no
    longer grows with the number of listed sessions.  The command exits ``1``
    when any requested identifier is unknown, so a non-zero exit code is not a
    failure by itself: the JSON array on stdout is authoritative and unknown
    identifiers are simply absent from it.  Only an unusable response (timeout,
    missing command, unparseable or non-array payload) yields an empty mapping,
    which the caller treats as a transient failure and retries on the next
    refresh.
    """
    if not session_ids:
        return {}

    try:
        result = _run_lookup_command(
            [_SESSIONS_INFO_COMMAND, "--json", *session_ids]
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}

    if not result.stdout:
        return {}

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, list):
        return {}

    requested = set(session_ids)
    resolved: dict[str, _LookupResult] = {}
    for record in payload:
        if not isinstance(record, dict):
            continue
        session_id = record.get("session_id")
        if not isinstance(session_id, str) or session_id not in requested:
            continue
        lookup = _parse_session_record(record)
        if lookup is not None:
            resolved[session_id] = lookup
    return resolved


def _fetch_missing_session_info(session_ids: List[str]) -> None:
    """Fetch session metadata in one batch and cache only non-empty results.

    All identifiers are resolved by a single subprocess call.  Transient
    failures are not cached, allowing retries on the next refresh.
    Empty/whitespace-only names are also not cached, but a valid
    ``project_workspace`` without a name is still cached so the workspace can
    be reused.
    """
    if not session_ids:
        return

    for session_id, lookup in _get_sessions_info(session_ids).items():
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


def _workspace_meta_fallback(file_info: dict) -> Tuple[Optional[str], Optional[str]]:
    """Return the exact session metadata name and workspace for one row.

    The fallback is consulted only when the primary lookup produced nothing.
    It reuses the discovery snapshot, which ``read_session_meta`` already
    validated for identity, and re-checks that identity against the row so a
    snapshot for another session or PID can never be substituted.
    """
    snapshot = file_info.get("_workspace_meta_snapshot")
    if not isinstance(snapshot, tuple) or len(snapshot) != 4:
        return None, None
    _home, session_id, pid, data = snapshot
    if not isinstance(data, dict):
        return None, None
    if not isinstance(session_id, str) or session_id != file_info.get("session_id"):
        return None, None
    expected_pid = (
        file_info.get("session_pid") if file_info.get("is_task")
        else file_info.get("pid")
    )
    if type(pid) is not int or pid != expected_pid:
        return None, None
    if data.get("session_id") != session_id or data.get("pid") != pid:
        return None, None

    name = data.get("session_name")
    name = name.strip() if isinstance(name, str) and name.strip() else None
    project_workspace = data.get("project_workspace")
    if (not isinstance(project_workspace, str) or not project_workspace.strip()
            or not os.path.isabs(project_workspace)):
        project_workspace = None
    return name, project_workspace


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
        # Fallback: consult the row's exact session metadata record only when
        # the primary lookup produced nothing, so a renamed session keeps its
        # primary name and a failed lookup still shows the recorded one.
        if not file_info["session_name"] or not file_info["project_workspace"]:
            meta_name, meta_path = _workspace_meta_fallback(file_info)
            if not file_info["session_name"]:
                file_info["session_name"] = meta_name
            if not file_info["project_workspace"]:
                file_info["project_workspace"] = meta_path


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
    """Fetch non-empty session names in one batch.

    Returns a mapping from session ID to session name.  Lookups that fail or
    return an empty/whitespace-only name are omitted.  Failures are silent so
    the caller can continue refreshing the list without blocking.
    """
    if not session_ids:
        return {}

    results: dict[str, str] = {}
    for session_id, lookup in _get_sessions_info(session_ids).items():
        if lookup.name:
            results[session_id] = lookup.name
    return results


def enrich_running_unnamed_sessions(files: List[dict]) -> None:
    """Backfill session names for running sessions that currently have none.

    When the workspace task list is refreshed, running sessions may already
    have received a display name from the agent.  This function queries
    ``topsailai_sessions_info`` for sessions that meet all of the following
    criteria:

      1. A real session ID exists (not empty, not ``(temp)``, not None).
      2. The embedded PID is alive.
      3. The ``session_name`` field is missing or empty.

    Lookups are deduplicated and resolved by one batch call.  Failures are
    silent and do not block the refresh.  Only the ``session_name`` field is
    updated; ``project_workspace`` is left untouched because it is already
    resolved by :func:`enrich_files_with_session_names`.
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
