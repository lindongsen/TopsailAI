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
from typing import Any, Dict, List, Optional, Tuple

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


def _positive_pid(value: Any) -> Optional[int]:
    """Return *value* when it is a usable positive integer PID."""
    if type(value) is int and value > 0:
        return value
    return None


def _resolve_owner(row: Dict[str, Any],
                   task_dir: str) -> Tuple[Optional[int], bool]:
    """Return ``(pid, is_task)`` for the process that should answer the row.

    Every agent process starts its own control server keyed by its own PID, so
    a live task agent owns ``{session}.{task_pid}.session.sock`` exactly as a
    session process owns its own. The row's own PID is therefore the only owner:
    a row describes the process that wrote its log file, and a different process
    reports different counters, so substituting the parent would publish another
    agent's data under this row's identity.

    The one exception is a task row whose own PID equals its parent's PID, which
    is a subagent running inside the session process; there the two identities
    name the same process, so the session answers.

    *is_task* describes the process that answered, not the row kind.
    """
    from cli_topsailai.runtime_control import build_socket_path

    own_pid = _positive_pid(row.get("pid"))
    parent_pid = _positive_pid(row.get("session_pid"))
    # A task row whose own PID equals its parent's PID is a subagent running
    # inside the session process, so the answering process is the session.
    own_is_task = bool(row.get("is_task")) and own_pid != parent_pid
    file_session_id = _file_session_id(row.get("session_id"))
    if file_session_id is not None and own_pid is not None:
        socket_path = build_socket_path(task_dir, file_session_id, str(own_pid))
        if _is_socket(socket_path):
            return own_pid, own_is_task
    # No channel exists for this row's own process. Report that PID so the
    # failure names the process the row actually describes, instead of silently
    # answering with a different process's data.
    if own_pid is not None:
        return own_pid, own_is_task
    if parent_pid is not None:
        return parent_pid, False
    return None, False


def _is_socket(path: str) -> bool:
    """Report whether the path itself is a socket, without following symlinks."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(info.st_mode)


def _process_log_records(task_dir: str) -> List[Tuple[str, int, bool]]:
    """Return ``(session_id, pid, is_task)`` for every process log, in one scan.

    A session process writes ``{session}.{pid}.session.stdout``. A task agent
    runs with session tee disabled, so it writes
    ``{session}.{pid}[.{task_id}].task.stdout`` instead and never creates a
    session stdout file. Both files are created by the process itself, so both
    prove which session owns the PID, and the file kind is the same evidence
    that answers whether the process is a task agent.

    The on-disk identity is used rather than the display identity, so a
    temporary session is named ``topsailai`` here exactly as its filename says.
    A file that does not parse into a positive PID is skipped instead of
    aborting the scan, because one unusable leftover must not hide the rest.
    """
    from cli_topsailai.log_files import parse_stdout_filename

    records: List[Tuple[str, int, bool]] = []
    try:
        entries = os.listdir(task_dir)
    except OSError:
        return records
    for entry in entries:
        is_task = entry.endswith(".task.stdout")
        if not is_task and not entry.endswith(".session.stdout"):
            continue
        session_id, raw_pid = parse_stdout_filename(entry)
        if session_id is None or raw_pid is None or not raw_pid.isdecimal():
            continue
        pid = int(raw_pid)
        if pid <= 0:
            continue
        records.append((session_id, pid, is_task))
    return records


def _failure(state: str, error_code: str, pid: Optional[int],
             is_task: bool = False) -> Dict[str, Any]:
    """Build one row result that carries no runtime data."""
    return {"state": state, "error_code": error_code, "pid": pid,
            "is_task": is_task, "data": None}


def _parse_result(response: Dict[str, Any], pid: Optional[int],
                  is_task: bool = False) -> Dict[str, Any]:
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
            return _failure("invalid_payload", "invalid_payload", pid, is_task)
        if not isinstance(data, dict):
            return _failure("invalid_payload", "invalid_payload", pid, is_task)
    else:
        return _failure("invalid_payload", "invalid_payload", pid, is_task)
    # ``state == "ok"`` must mean "usable runtime data is present", so an
    # instruction that answered with its own failure is reported as
    # unavailable while the raw payload stays available for diagnosis.
    if data.get("ok") is False:
        reported = data.get("error")
        error_code = reported if isinstance(reported, str) and reported else "no_data"
        return {"state": "unavailable", "error_code": error_code, "pid": pid,
                "is_task": is_task, "data": data}
    return {"state": "ok", "error_code": None, "pid": pid,
            "is_task": is_task, "data": data}


def _collect_one(row: Dict[str, Any], task_dir: str, timeout: float,
                 sender, pid: Optional[int],
                 is_task: bool = False) -> Dict[str, Any]:
    """Collect one row's runtime record, converting every failure to a state.

    *pid* and *is_task* describe the process that owns the answering channel,
    not the row that referenced it, so the caller resolves them first. Keeping
    the transport free of ownership rules means the workspace list and the
    single-session command cannot disagree about which process answers.
    """
    from cli_topsailai.runtime_control import (
        ControlDeliveryError,
        build_socket_path,
    )

    file_session_id = _file_session_id(row.get("session_id"))
    if file_session_id is None or pid is None:
        return _failure("unavailable", "unsupported_row", pid, is_task)
    socket_path = build_socket_path(task_dir, file_session_id, str(pid))
    # A socket file outlives its owner process, so existence proves only that a
    # channel once existed. Probing a stale endpoint fails in about a
    # millisecond, so checking existence first is a cheap fast path rather than
    # a liveness claim.
    if not _is_socket(socket_path):
        return _failure("unavailable", "endpoint_missing", pid, is_task)
    payload = {"instruction": RUNTIME_INSTRUCTION, "args": [RUNTIME_JSON_ARGUMENT]}
    try:
        result = sender(socket_path, "call_instruction", payload, timeout=timeout)
    except ControlDeliveryError as exc:
        state = _STATE_BY_ERROR_CODE.get(exc.error_code, "unavailable")
        return _failure(state, exc.error_code, pid, is_task)
    except Exception:
        # An unexpected failure is still one row's problem, never the
        # document's, so it is reported without a traceback.
        return _failure("unavailable", "internal_error", pid, is_task)
    return _parse_result(result.response, pid, is_task)


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
    # Ownership is resolved once per row before the pool starts, because the
    # decision reads the task directory and must not be repeated inside a
    # worker thread that also owns the transport budget.
    owners = {id(row): _resolve_owner(row, task_dir) for row in rows}
    collected: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _collect_one, row, task_dir, timeout, sender,
                owners[id(row)][0], owners[id(row)][1],
            ): row
            for row in rows
        }
        for future, row in futures.items():
            filename = row.get("filename")
            if not isinstance(filename, str) or not filename:
                continue
            try:
                collected[filename] = future.result()
            except Exception:
                owner_pid, owner_is_task = owners[id(row)]
                collected[filename] = _failure(
                    "unavailable", "internal_error", owner_pid, owner_is_task,
                )
    return collected


def collect_session_runtime(
    session_id: Any,
    pid: Optional[int],
    task_dir: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    sender=None,
    is_task: bool = False,
) -> Dict[str, Any]:
    """Collect one session's runtime record through its own control channel.

    This is the single-session entry point for the same contract
    :func:`collect_workspace_runtime` applies per row, so both commands report
    identical states, error codes and payloads. It exists instead of a second
    transport because a duplicated request builder is a second place for the
    instruction name or the argument form to drift.

    Args:
        session_id: Display session identity, including the ``(temp)`` sentinel.
        pid: The process that owns the session's control channel. ``None``
            means no live owner was resolved, so nothing is contacted.
        task_dir: Absolute task directory holding the control sockets.
        timeout: Transport budget in seconds.
        sender: Optional delivery seam, defaulting to the real transport.
        is_task: Whether *pid* is a task (child) agent rather than the session
            process. The caller knows this because it selected the PID, and the
            record reports it so a consumer can tell the two agents of one
            session apart.

    Returns:
        One ``{state, error_code, pid, is_task, data}`` record. A row that
        cannot be queried reports ``unsupported_row`` rather than raising,
        because runtime data is an optional enrichment of the session record.
    """
    row: Dict[str, Any] = {"session_id": session_id, "pid": pid}
    if sender is None:
        from cli_topsailai.runtime_control import send_to_control

        sender = send_to_control
    return _collect_one(row, task_dir, timeout, sender, pid, is_task)
