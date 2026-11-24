"""Collect per-row session lock state for the workspace JSON document.

Author: DawsonLin

The lock state answers a different question than the row's ``status`` field:
``status`` describes what the agent process is doing (``input``, ``running``,
``idle``), while the lock state describes whether a task currently holds the
session (``processing``) or the session is free (``idle``). A session can be
``idle`` while its process still exists, and ``processing`` while no process is
visible, so the two values are independent and neither can be derived from the
other.

This collector does not probe the lock itself. The existing
``topsailai_session_status`` command owns that detection, so this module only
runs that command and reads its JSON answer. Keeping one implementation means
"locked" cannot come to mean two different things in two places.
"""

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

from cli_topsailai.constants import TEMP_SESSION_ID, TEMP_SESSION_MARKER

#: The existing command that owns lock-state detection. It is invoked as a child
#: process rather than imported, because a compiled build ships every top-level
#: CLI script as a standalone executable and never as an importable module.
SESSION_STATUS_COMMAND = "topsailai_session_status"

#: Exit status used when the child command is not installed.
COMMAND_MISSING = 127

#: The child's own status vocabulary. Reusing it instead of inventing new words
#: keeps ``session_status.status`` identical to what the command prints.
STATUS_IDLE = "idle"
STATUS_PROCESSING = "processing"

_UNSAFE_IDENTIFIER_CHARS = ("\0", "/", "\\")


def _file_session_id(session_id: Any) -> Optional[str]:
    """Map a display session id to the identity the lock command expects.

    Temporary sessions have no real identifier: they are displayed as
    ``(temp)`` and stored under the reserved ``topsailai`` prefix, which is also
    the name the lock command resolves. An identifier that cannot be passed to
    the child safely yields ``None`` instead of raising, because one unusable
    row must not abort the document.
    """
    if session_id in (None, "", TEMP_SESSION_MARKER, TEMP_SESSION_ID):
        return TEMP_SESSION_ID
    if not isinstance(session_id, str):
        return None
    if (session_id in (".", "..") or ".." in session_id
            or any(char in session_id for char in _UNSAFE_IDENTIFIER_CHARS)):
        return None
    return session_id


def _failure(error_code: str, message: str) -> Dict[str, Any]:
    """Build one row's failure record with the same shape as a success."""
    return {"status": None, "error_code": error_code, "message": message}


def _parse_status(stdout: str) -> Dict[str, Any]:
    """Convert the child's JSON answer into one row record.

    The child prints ``{"session_id", "status", "error_code", "message"}``. The
    session identity is dropped because the row already carries it, so the
    record holds only the three fields a consumer needs. A document that cannot
    be decoded is reported as ``invalid_payload`` rather than being guessed at.
    """
    try:
        document = json.loads(stdout)
    except (TypeError, ValueError):
        return _failure("invalid_payload", "Session status answer was not JSON")
    if not isinstance(document, dict):
        return _failure("invalid_payload", "Session status answer was not an object")
    status = document.get("status")
    if status not in (STATUS_IDLE, STATUS_PROCESSING):
        # The child reports a failure as ``status: null`` plus its own
        # ``error_code``, so an unusable status is forwarded with that code
        # instead of being replaced by a locally invented one.
        return _failure(
            document.get("error_code") or "invalid_payload",
            document.get("message") or "Session status answer carried no usable status",
        )
    return {"status": status, "error_code": None, "message": None}


def _query_one(session_id: str) -> Dict[str, Any]:
    """Ask the existing command for one session's lock state.

    The child runs through the shared lookup runner, which starts it as a
    process-group leader and kills the whole group on timeout. A plain
    ``subprocess.run(timeout=...)`` would kill only the direct child and leave
    the ``uv run`` grandchild behind, which is the orphan this project already
    fixed once.
    """
    from cli_topsailai.session_info import _run_lookup_command

    try:
        completed = _run_lookup_command(
            [SESSION_STATUS_COMMAND, "-s", session_id, "--json"],
        )
    except FileNotFoundError:
        return _failure("command_missing", f"Command not found: {SESSION_STATUS_COMMAND}")
    except OSError as error:
        return _failure("command_missing", f"Unable to run {SESSION_STATUS_COMMAND}: {error}")
    except subprocess.TimeoutExpired:
        return _failure("timeout", "Session status command did not answer in time")
    if completed.returncode == COMMAND_MISSING:
        return _failure("command_missing", f"Command not found: {SESSION_STATUS_COMMAND}")
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        return _failure(
            "status_unavailable",
            detail or f"Session status command exited {completed.returncode}",
        )
    return _parse_status(completed.stdout)


def collect_workspace_session_status(
    rows: List[Dict[str, Any]],
    *,
    query=None,
) -> Dict[str, Dict[str, Any]]:
    """Collect lock state for every row, keyed by the row's filename.

    The filename is unique within one task directory, so it identifies a row
    without depending on a session identity that a temporary session does not
    have.

    Several rows of one session share one lock, so each distinct on-disk session
    identity is queried once and the answer is reused for every row of that
    session. One invocation therefore runs the child at most once per session,
    never once per row.

    Args:
        rows: Discovered workspace rows, already filtered for output.
        query: Optional seam replacing the child command, used by tests.

    Returns:
        A mapping from row filename to ``{status, error_code, message}``. A row
        whose filename is unusable is absent from the mapping, because there is
        no key to report it under.
    """
    if not rows:
        return {}
    if query is None:
        query = _query_one
    # One answer per session identity, resolved before the rows are projected so
    # a session with several rows pays for exactly one child process.
    answers: Dict[str, Dict[str, Any]] = {}
    collected: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        filename = row.get("filename")
        if not isinstance(filename, str) or not filename:
            continue
        identity = _file_session_id(row.get("session_id"))
        if identity is None:
            collected[filename] = _failure(
                "unsupported_row", "Row carries no usable session identity",
            )
            continue
        if identity not in answers:
            try:
                answers[identity] = query(identity)
            except Exception as error:
                # One row's probe must never abort the document, so an
                # unexpected failure is reported in that session's rows.
                answers[identity] = _failure("internal_error", str(error))
        collected[filename] = dict(answers[identity])
    return collected
