"""Read one workspace row enriched with runtime data from a chosen process.

Author: DawsonLin

``topsailai runtime info`` publishes the workspace-list item for one exact
process, minus the keys that exist only to render a listing. The item is produced
by the workspace list's own builder and the runtime record by the list's own
collector, so the two commands cannot drift in fields, values, states or error
codes. The rule is an exclusion rather than a keep-list, so a session-record
field the list gains later is published here without a change.

Both selectors are mandatory. One session may run several agents, so a session
identity alone does not name the process whose runtime should be reported, and a
PID alone does not prove which session the caller meant.
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
#: switches between the commands sees one contract.
_EXIT_CODES = {
    "usage_error": 2,
    "target_not_found": 3,
    "target_mismatch": 3,
    "session_not_found": 1,
    "lookup_failed": 1,
}

#: List-presentation keys removed from the workspace-list item.
#:
#: The published document is the list item minus these keys, so every
#: session-record field the list carries is published without being enumerated
#: here. A keep-list would silently drop each field the session record gains
#: later; an exclusion list cannot, because a new field is published by default.
#:
#: ``no``, ``filename``, ``created_at`` and ``completed`` describe the listing
#: (row number, log file, file birth time, DONE marker). ``hostname`` is dropped
#: because ``metafile.hostname`` already carries the same stored value.
#: ``driver`` and ``process_generation`` are dropped because they are display
#: and signal authority, and this command is read-only.
EXCLUDED_KEYS = (
    "no",
    "filename",
    "hostname",
    "created_at",
    "completed",
    "driver",
    "process_generation",
)


@dataclass(frozen=True)
class RuntimeInfoRequest:
    """Describe one read-only runtime info request.

    ``session_id`` and ``pid`` are both required: the session proves which
    session the caller meant and the PID selects which of its agents answers.
    ``timeout`` is ``None`` when the caller did not pass ``--timeout``, so the
    collector's own default budget applies.
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


def _display_session_id(session_id: str) -> str:
    """Map a session identity to the value discovered rows carry.

    Discovery reports a temporary session as ``(temp)`` while its files use the
    reserved ``topsailai`` prefix, so filtering rows with the caller's spelling
    would drop every temporary row when the caller passed the prefix.
    """
    from cli_topsailai.constants import TEMP_SESSION_ID, TEMP_SESSION_MARKER

    if _on_disk_session_id(session_id) == TEMP_SESSION_ID:
        return TEMP_SESSION_MARKER
    return session_id


def resolve_target(
    session_id: Optional[str], pid: Optional[int], home: str
) -> Tuple[str, int]:
    """Return the exact ``(session_id, pid)`` pair to describe.

    Both selectors are required. The PID is proven to belong to the requested
    session through a process log it wrote itself, because reporting another
    session's runtime data would be worse than failing. A task agent writes only
    a task log, so accepting that file is what makes a worker PID reachable.

    Args:
        session_id: Display session identity.
        pid: Explicit positive PID.
        home: Absolute ``TOPSAILAI_HOME`` directory.

    Returns:
        The session identity and the PID to describe.

    Raises:
        RuntimeInfoError: ``usage_error`` when a selector is missing,
            ``target_not_found`` when no process log records the PID, or
            ``target_mismatch`` when it records another session.
    """
    if session_id is None or pid is None:
        raise RuntimeInfoError(
            "usage_error", "Both a session and a PID are required"
        )
    expected = _on_disk_session_id(session_id)
    if expected is None:
        raise RuntimeInfoError(
            "target_mismatch", "The session identifier cannot name a process"
        )
    task_dir = os.path.join(home, TASK_SUBDIR)
    owners = [owner for owner, record_pid, _is_task
              in _process_records(task_dir) if record_pid == pid]
    if not owners:
        raise RuntimeInfoError(
            "target_not_found", "No process log records this PID"
        )
    if expected not in owners:
        raise RuntimeInfoError(
            "target_mismatch", "The PID belongs to another session"
        )
    return session_id, pid


def _workspace_row(session_id: str, pid: int, home: str) -> Dict[str, Any]:
    """Return the workspace-list row whose filename records *pid*.

    The row is produced by the same discovery and enrichment calls the list
    makes, in the same order, restricted to one session. ``metafile`` is
    attached by the hostname enrichment that the driver enrichment invokes, so
    skipping either step would publish ``null`` for a session that has a record.

    Raises:
        RuntimeInfoError: ``session_not_found`` when the session has no row, or
            ``target_not_found`` when no row of it records the PID.
    """
    from cli_topsailai.core import _driver_authority, _enrich_driver_rows
    from cli_topsailai.log_files import discover_workspace_log_files
    from cli_topsailai.session_info import enrich_files_with_session_names

    task_dir = os.path.join(home, TASK_SUBDIR)
    rows = discover_workspace_log_files(
        task_dir, session_ids=[_display_session_id(session_id)]
    )
    if not rows:
        raise RuntimeInfoError(
            "session_not_found", f"Session not found: {session_id}"
        )
    enrich_files_with_session_names(rows)
    _enrich_driver_rows(rows, home, _driver_authority(os.environ))
    for row in rows:
        # The filename PID is the identity evidence, so it selects the row even
        # when the published ``pid`` is a display fallback for a dead process.
        if row.get("pid") == pid:
            return row
    raise RuntimeInfoError(
        "target_not_found", "No process log records this PID"
    )


def _project(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return the list item minus the keys that only describe a listing.

    Everything the list carries is published, so a session-record field the list
    gains later appears here without a change. ``runtime`` and ``metafile`` are
    guaranteed present because they are the two groups this command exists for,
    and ``status_raw`` keeps its conditional presence: the list omits it when
    the session lookup produced no record, and emitting ``null`` would claim an
    observation that never happened.
    """
    document = {
        key: value for key, value in item.items() if key not in EXCLUDED_KEYS
    }
    document.setdefault("runtime", None)
    document.setdefault("metafile", None)
    return document


def build_document(
    session_id: str,
    pid: int,
    home: str,
    timeout: Optional[float] = None,
) -> str:
    """Return the projected workspace item as one JSON string.

    The item comes from the workspace list's own builder and the runtime record
    from the list's own collector, so every published value is the value the
    list publishes for the same row. Only one row is collected, so the command
    costs one transport call instead of a directory-wide fan-out.

    Raises:
        RuntimeInfoError: ``session_not_found`` when the session has no row, or
            ``target_not_found`` when no row of it records the PID.
    """
    from cli_topsailai.core import _workspace_json_item
    from cli_topsailai.workspace_runtime import collect_workspace_runtime

    row = _workspace_row(session_id, pid, home)
    task_dir = os.path.join(home, TASK_SUBDIR)
    if timeout is None:
        collected = collect_workspace_runtime([row], task_dir)
    else:
        collected = collect_workspace_runtime([row], task_dir, timeout=timeout)
    runtime = collected.get(row.get("filename"))
    item = _workspace_json_item(row, 1, runtime)
    return json.dumps(_project(item), ensure_ascii=False, indent=2)


def _failure_document(session_id: str, error_code: str, message: str) -> str:
    """Return the same failure object ``session info`` prints for this case.

    A failure carries no metafile and no runtime, so inventing empty groups
    would make a failure indistinguishable from a real record whose fields
    happen to be empty.
    """
    import topsailai_session_info as session_info

    return session_info._format_failure_json(session_id, error_code, message)


def run_info(request: RuntimeInfoRequest, *, home: str) -> int:
    """Print one projected workspace item and return its exit status.

    The document is always JSON, because the requested content is a JSON
    record. Every failure path prints the same failure object instead of a text
    line, so a machine consumer never receives an unparseable document on
    stdout.
    """
    session_id = request.session_id or ""
    try:
        resolved_session, resolved_pid = resolve_target(
            request.session_id, request.pid, home
        )
        document = build_document(
            resolved_session, resolved_pid, home, request.timeout
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
