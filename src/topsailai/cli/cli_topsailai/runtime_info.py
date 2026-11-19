"""Read one session record enriched with runtime data from a chosen process.

Author: DawsonLin

``topsailai runtime info`` publishes exactly the document that
``topsailai session info --include-runtime --json`` publishes, with one
addition: the process that answers the runtime query can be selected by PID,
because one session may run several agents at the same time.

The record projection and the runtime transport are both reused instead of
reimplemented, so the two commands cannot drift in fields, ordering, states or
error codes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

#: Task subdirectory holding session stdout files and control sockets.
TASK_SUBDIR = "workspace/task"

#: Exit categories. ``session_not_found`` and ``lookup_failed`` keep the status
#: ``session info`` already returns for the same failures, so a caller that
#: switches between the two commands sees one contract.
_EXIT_CODES = {
    "usage_error": 2,
    "target_not_found": 3,
    "target_mismatch": 3,
    "session_not_found": 1,
    "lookup_failed": 1,
}


@dataclass(frozen=True)
class RuntimeInfoRequest:
    """Describe one read-only runtime info request.

    ``timeout`` is ``None`` when the caller did not pass ``--timeout``, so the
    collector's own default budget applies and the default invocation keeps the
    same transport cost as ``session info --include-runtime``.
    """

    session_id: Optional[str] = None
    pid: Optional[int] = None
    timeout: Optional[float] = None


class RuntimeInfoError(Exception):
    """Carry a stable machine error code and its exit category."""

    def __init__(self, error_code: str, message: str):
        """Store the classification without printing or exiting."""
        super().__init__(message)
        self.error_code = error_code
        self.message = message

    @property
    def exit_code(self) -> int:
        """Return the exit status for this failure class."""
        return _EXIT_CODES[self.error_code]


def _process_records(task_dir: str) -> List[Tuple[str, int, bool]]:
    """Return ``(session_id, pid, is_task)`` for every process log.

    The scan lives in the collector module because the collector owns the
    socket-path contract, and a second copy here would be a second place for
    the filename convention to drift.
    """
    from cli_topsailai.workspace_runtime import _process_log_records

    return _process_log_records(task_dir)


def _on_disk_session_id(session_id: Optional[str]) -> Optional[str]:
    """Map a display session identity to its on-disk filename prefix.

    The collector composes the socket path from this same mapping, so ownership
    and endpoint resolution cannot disagree about which file names the session.
    """
    from cli_topsailai.workspace_runtime import _file_session_id

    return _file_session_id(session_id)


def _display_session_id(on_disk_session_id: str) -> str:
    """Map an on-disk filename prefix back to the identity users see.

    A temporary session is stored under the reserved ``topsailai`` prefix but is
    displayed as ``(temp)`` everywhere else, so a PID-only lookup must translate
    the prefix instead of publishing the storage detail as a session name.
    """
    from cli_topsailai.constants import TEMP_SESSION_ID, TEMP_SESSION_MARKER

    if on_disk_session_id == TEMP_SESSION_ID:
        return TEMP_SESSION_MARKER
    return on_disk_session_id


def resolve_target(
    session_id: Optional[str], pid: Optional[int], home: str
) -> Tuple[str, Optional[int], bool]:
    """Return the exact ``(session_id, pid, is_task)`` triple to query.

    Without an explicit PID the answer is the one ``session info`` already
    produces: the PID that proved the session live. An idle or unverifiable
    session therefore yields ``(session_id, None, False)`` and is never probed,
    so a process that does not exist is not reported as a collection failure.

    With an explicit PID the caller asserted a specific process, so it is
    queried even when the session looks idle. The PID is first proven to belong
    to the requested session through a process log it wrote itself, because
    reporting another session's runtime data would be worse than failing. A
    task agent writes only a task log, so accepting that file is what makes a
    worker PID reachable at all.

    Args:
        session_id: Display session identity, or ``None`` when only a PID was
            given.
        pid: Explicit positive PID, or ``None`` to resolve the live owner.
        home: Absolute ``TOPSAILAI_HOME`` directory.

    Returns:
        The session identity, the PID to query (``None`` when no live owner was
        resolved), and whether that PID is a task agent rather than the session
        process.

    Raises:
        RuntimeInfoError: ``target_not_found`` when no process log records the
            PID, or ``target_mismatch`` when it records another session.
    """
    if pid is None:
        from cli_topsailai.process_liveness import live_session_pid

        return session_id or "", live_session_pid(session_id or "", home=home), False

    task_dir = os.path.join(home, TASK_SUBDIR)
    owners = [(owner, is_task) for owner, record_pid, is_task
              in _process_records(task_dir) if record_pid == pid]
    if not owners:
        raise RuntimeInfoError(
            "target_not_found", "No process log records this PID"
        )
    # A session process writes a session log, so its own record wins when a PID
    # somehow left both kinds behind; the session log is the stronger identity.
    is_task = all(record_is_task for _owner, record_is_task in owners)
    if session_id is None:
        # Only a PID was given, so the filename is the only identity evidence.
        # The on-disk prefix is translated back to the display identity, so a
        # temporary session is reported as ``(temp)`` like every other command.
        return _display_session_id(owners[0][0]), pid, is_task
    expected = _on_disk_session_id(session_id)
    if expected is None:
        raise RuntimeInfoError(
            "target_mismatch", "The session identifier cannot name a process"
        )
    if expected not in [owner for owner, _is_task in owners]:
        raise RuntimeInfoError(
            "target_mismatch", "The PID belongs to another session"
        )
    return session_id, pid, is_task


def build_document(
    session_id: str,
    pid: Optional[int],
    home: str,
    timeout: Optional[float] = None,
    is_task: bool = False,
) -> str:
    """Return the session record document as one JSON string.

    The projection is ``topsailai_session_info``'s own formatter, so the
    document is identical to ``session info --include-runtime --json`` for the
    same session. ``runtime`` is ``None`` when no PID was resolved, which is the
    same "not running" answer that command publishes.

    *is_task* is forwarded to the collector so the runtime record states which
    kind of process answered; the session record itself is unchanged, which is
    what keeps the two commands byte-identical.

    Raises:
        RuntimeInfoError: ``session_not_found`` when the session has no stored
            record, because a record cannot be produced without one.
    """
    import topsailai_session_info as session_info
    from topsailai.context.ctx_manager import get_session_manager
    from cli_topsailai.workspace_runtime import collect_session_runtime

    manager = get_session_manager(None)
    session = manager.get_session(session_id)
    if session is None:
        raise RuntimeInfoError(
            "session_not_found", f"Session not found: {session_id}"
        )
    runtime: Optional[Dict[str, Any]] = None
    if pid is not None:
        task_dir = os.path.join(home, TASK_SUBDIR)
        if timeout is None:
            runtime = collect_session_runtime(
                session_id, pid, task_dir, is_task=is_task
            )
        else:
            runtime = collect_session_runtime(
                session_id, pid, task_dir, timeout=timeout, is_task=is_task
            )
    return session_info._format_session_json(session, home, runtime)


def _failure_document(session_id: str, error_code: str, message: str) -> str:
    """Return the same failure object ``session info`` prints for this case."""
    import topsailai_session_info as session_info

    return session_info._format_failure_json(session_id, error_code, message)


def run_info(request: RuntimeInfoRequest, *, home: str) -> int:
    """Print one session record document and return its exit status.

    The document is always JSON, because the requested content is a JSON
    record. Every failure path prints the same failure object instead of a text
    line, so a machine consumer never receives an unparseable document on
    stdout.
    """
    session_id = request.session_id or ""
    try:
        resolved_session, resolved_pid, is_task = resolve_target(
            request.session_id, request.pid, home
        )
        document = build_document(
            resolved_session, resolved_pid, home, request.timeout, is_task
        )
    except RuntimeInfoError as error:
        print(_failure_document(session_id, error.error_code, error.message))
        return error.exit_code
    except Exception as error:
        # A storage or import failure is reported as a classified result rather
        # than a traceback, matching the reference command's failure contract.
        print(_failure_document(session_id, "lookup_failed", str(error)))
        return 1
    print(document)
    return 0
