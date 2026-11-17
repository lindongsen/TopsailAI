"""Collect per-row runtime data for the workspace JSON document.

Author: DawsonLin

The collector asks every listed session process for its own runtime report
through the existing control channel, so the CLI never reads another process's
memory or log files. Collection is bounded and concurrent: a slow or wedged
agent costs one timeout, never the whole document.
"""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from cli_topsailai.constants import TEMP_SESSION_ID, TEMP_SESSION_MARKER

# The instruction and argument form are fixed by the core contract:
# ``static_data(*args, **kwargs)`` parses named parameters out of ``args``
# only, so the keyword form is rejected as an unknown parameter.
RUNTIME_INSTRUCTION = "runtime.static-data"
RUNTIME_JSON_ARGUMENT = "json=1"

# ``/runtime.static-data`` only reads plain attributes and collection lengths,
# so one request performs no token counting or other derived computation in the
# answering process. A wide pool is therefore safe: every request is dominated
# by waiting on another process, and the bound exists only to keep one list
# command from opening an unbounded number of sockets at once.
DEFAULT_MAX_WORKERS = 20
DEFAULT_TIMEOUT = 2.0

_UNSAFE_IDENTIFIER_CHARS = ("\0", "/", "\\")

# Transport error codes collapse into the small state vocabulary a consumer
# switches on. The original code is preserved in ``error_code`` so no
# diagnostic detail is lost.
_STATE_BY_ERROR_CODE = {
    "control_rejected": "rejected",
    "timeout": "timeout",
    "endpoint_missing": "unavailable",
    "endpoint_invalid": "unavailable",
    "permission_denied": "unavailable",
    "unsupported_transport": "unavailable",
    "transport_error": "unavailable",
    "invalid_response": "unavailable",
}


def _file_session_id(session_id: Any) -> Optional[str]:
    """Map a display session id to its on-disk filename prefix.

    Temporary sessions have no real identifier: they are displayed as
    ``(temp)`` and stored under the reserved ``topsailai`` prefix. An
    identifier that cannot be composed into a path safely yields ``None``
    instead of raising, because one unusable row must not abort the document.
    """
    if session_id in (None, "", TEMP_SESSION_MARKER, TEMP_SESSION_ID):
        return TEMP_SESSION_ID
    if not isinstance(session_id, str):
        return None
    if (session_id in (".", "..") or ".." in session_id
            or any(char in session_id for char in _UNSAFE_IDENTIFIER_CHARS)):
        return None
    return session_id


def _row_owner_pid(row: Dict[str, Any]) -> Optional[int]:
    """Return the PID of the session process that owns the row's socket.

    A task row is a child process log, so its own PID never owns a control
    channel; only the parent session PID does. A task row whose parent is not
    resolvable reports no owner rather than probing the child's PID, which
    would silently describe a different process.
    """
    pid = row.get("session_pid")
    if type(pid) is int and pid > 0:
        return pid
    if row.get("is_task"):
        return None
    pid = row.get("pid")
    if type(pid) is int and pid > 0:
        return pid
    return None


def _is_socket(path: str) -> bool:
    """Report whether the path itself is a socket, without following symlinks."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(info.st_mode)


def _failure(state: str, error_code: str, pid: Optional[int]) -> Dict[str, Any]:
    """Build one row result that carries no runtime data."""
    return {"state": state, "error_code": error_code, "pid": pid, "data": None}


def _parse_result(response: Dict[str, Any], pid: Optional[int]) -> Dict[str, Any]:
    """Decode the instruction's ``result`` into the published runtime record.

    ``result`` is a JSON string produced by the answering process, not a nested
    object, so it must be decoded here. A payload that cannot be decoded, or
    that reports its own failure, is a per-row state rather than an exception.
    """
    result = response.get("result")
    if isinstance(result, dict):
        data = result
    elif isinstance(result, str):
        try:
            data = json.loads(result)
        except (ValueError, RecursionError):
            return _failure("invalid_payload", "invalid_payload", pid)
        if not isinstance(data, dict):
            return _failure("invalid_payload", "invalid_payload", pid)
    else:
        return _failure("invalid_payload", "invalid_payload", pid)
    # ``state == "ok"`` must mean "usable runtime data is present", so an
    # instruction that answered with its own failure is reported as
    # unavailable while the raw payload stays available for diagnosis.
    if data.get("ok") is False:
        reported = data.get("error")
        error_code = reported if isinstance(reported, str) and reported else "no_data"
        return {"state": "unavailable", "error_code": error_code, "pid": pid,
                "data": data}
    return {"state": "ok", "error_code": None, "pid": pid, "data": data}


def _collect_one(row: Dict[str, Any], task_dir: str, timeout: float,
                 sender) -> Dict[str, Any]:
    """Collect one row's runtime record, converting every failure to a state."""
    from cli_topsailai.runtime_control import (
        ControlDeliveryError,
        build_socket_path,
    )

    file_session_id = _file_session_id(row.get("session_id"))
    pid = _row_owner_pid(row)
    if file_session_id is None or pid is None:
        return _failure("unavailable", "unsupported_row", pid)
    socket_path = build_socket_path(task_dir, file_session_id, str(pid))
    # A socket file outlives its owner process, so existence proves only that a
    # channel once existed. Probing a stale endpoint fails in about a
    # millisecond, so checking existence first is a cheap fast path rather than
    # a liveness claim.
    if not _is_socket(socket_path):
        return _failure("unavailable", "endpoint_missing", pid)
    payload = {"instruction": RUNTIME_INSTRUCTION, "args": [RUNTIME_JSON_ARGUMENT]}
    try:
        result = sender(socket_path, "call_instruction", payload, timeout=timeout)
    except ControlDeliveryError as exc:
        state = _STATE_BY_ERROR_CODE.get(exc.error_code, "unavailable")
        return _failure(state, exc.error_code, pid)
    except Exception:
        # An unexpected failure is still one row's problem, never the
        # document's, so it is reported without a traceback.
        return _failure("unavailable", "internal_error", pid)
    return _parse_result(result.response, pid)


def collect_workspace_runtime(
    rows: List[Dict[str, Any]],
    task_dir: str,
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout: float = DEFAULT_TIMEOUT,
    sender=None,
) -> Dict[str, Dict[str, Any]]:
    """Collect runtime data for every row, keyed by the row's filename.

    The filename is unique within one task directory, so it identifies a row
    without depending on a session identity that a temporary session does not
    have. Collection runs in a bounded thread pool because each request is
    dominated by waiting on another process, and a single row's failure is
    reported in its own record instead of aborting the document.

    Args:
        rows: Discovered workspace rows, already filtered for output.
        task_dir: Absolute task directory holding the control sockets.
        max_workers: Upper bound on concurrent requests.
        timeout: Transport budget in seconds for one row.
        sender: Optional delivery seam, defaulting to the real transport.

    Returns:
        A mapping from row filename to ``{state, error_code, pid, data}``.
        Rows that cannot be queried are absent from the mapping only when the
        row itself carries no filename.
    """
    if not rows:
        return {}
    if sender is None:
        from cli_topsailai.runtime_control import send_to_control

        sender = send_to_control
    workers = max(1, min(int(max_workers), len(rows)))
    collected: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_collect_one, row, task_dir, timeout, sender): row
            for row in rows
        }
        for future, row in futures.items():
            filename = row.get("filename")
            if not isinstance(filename, str) or not filename:
                continue
            try:
                collected[filename] = future.result()
            except Exception:
                collected[filename] = _failure(
                    "unavailable", "internal_error", _row_owner_pid(row),
                )
    return collected
