"""Helpers for resolving session metadata from external commands."""

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional


# Timeout for each external session-info lookup, in seconds.
_SESSION_INFO_TIMEOUT = 5

# Maximum number of concurrent subprocess lookups per refresh.
_MAX_SESSION_INFO_WORKERS = 8

# Sentinel used to distinguish "not cached" from "cached None".
_MISSING = object()


class _SessionNameCache:
    """Thread-safe cache mapping session_id to resolved session_name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Optional[str]] = {}

    def get(self, session_id: str) -> Optional[str]:
        """Return cached value or _MISSING if not present."""
        with self._lock:
            value = self._data.get(session_id, _MISSING)
        return value

    def set(self, session_id: str, name: Optional[str]) -> None:
        """Store value in cache."""
        with self._lock:
            self._data[session_id] = name


# Module-level cache shared across refreshes and threads.
_SESSION_NAME_CACHE = _SessionNameCache()


class _LookupResult:
    """Internal result wrapper to distinguish success from transient failure."""

    __slots__ = ("name", "success")

    def __init__(self, name: Optional[str], success: bool) -> None:
        self.name = name
        self.success = success


def _get_session_name(session_id: str) -> _LookupResult:
    """Return the session name for *session_id* using ``topsailai_session_info``.

    Temporary sessions are skipped and a successful result with ``None`` is
    returned immediately.  Transient failures (timeout, missing command,
    non-zero exit, invalid JSON, etc.) return ``success=False`` so the caller
    can avoid poisoning the cache.
    """
    if not session_id or session_id == "(temp)":
        return _LookupResult(None, True)

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
        return _LookupResult(None, False)

    if result.returncode != 0 or not result.stdout:
        return _LookupResult(None, False)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _LookupResult(None, False)

    if not isinstance(data, dict):
        return _LookupResult(None, False)

    name = data.get("session_name")
    if isinstance(name, str):
        return _LookupResult(name.strip() or None, True)
    return _LookupResult(None, True)


def _fetch_missing_session_names(session_ids: List[str]) -> None:
    """Fetch session names concurrently and cache only successful results.

    Each lookup runs in its own thread so slow subprocess calls do not block
    each other.  Transient failures are not cached, allowing retries on the
    next refresh.
    """
    if not session_ids:
        return

    max_workers = min(_MAX_SESSION_INFO_WORKERS, len(session_ids))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(_get_session_name, sid): sid for sid in session_ids
        }
        for future in as_completed(future_to_id):
            session_id = future_to_id[future]
            try:
                lookup = future.result()
            except Exception:
                continue
            if lookup.success:
                _SESSION_NAME_CACHE.set(session_id, lookup.name)


def enrich_files_with_session_names(files: List[dict]) -> None:
    """Add a ``session_name`` key to each file dict by looking up unique IDs.

    Lookups are deduplicated and cached so the same session ID is only queried
    once across the process lifetime.  Missing IDs are fetched concurrently via
    a thread pool.  Transient failures are not cached, so the next refresh will
    retry them.  Missing or permanently empty lookups are stored as ``None``
    and can be rendered as ``-`` by the caller.
    """
    if not files:
        return

    distinct_ids: list[str] = []
    seen: set[str] = set()
    for file_info in files:
        session_id = file_info.get("session_id")
        if session_id is None:
            continue
        if session_id not in seen:
            seen.add(session_id)
            distinct_ids.append(session_id)

    missing_ids = [
        sid for sid in distinct_ids if _SESSION_NAME_CACHE.get(sid) is _MISSING
    ]
    if missing_ids:
        _fetch_missing_session_names(missing_ids)

    for file_info in files:
        session_id = file_info.get("session_id")
        name = _SESSION_NAME_CACHE.get(session_id) if session_id is not None else _MISSING
        file_info["session_name"] = None if name is _MISSING else name
