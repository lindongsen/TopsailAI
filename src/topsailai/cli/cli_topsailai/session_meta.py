"""Read exact session metadata without acquiring process authority.

Author: DawsonLin
"""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re

from cli_topsailai.constants import TEMP_SESSION_ID, TEMP_SESSION_MARKER
from cli_topsailai.session_driver import _read_metadata

LOGGER = logging.getLogger(__name__)

# Session identifiers are used as filename components, so they are validated
# before any path is composed. Temporary sessions are the only exception: they
# have no real identifier and use the reserved ``topsailai`` file prefix.
_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}")


class SessionMetaError(ValueError):
    """Expose a safe failure category without including metadata contents."""


@dataclass(frozen=True)
class SessionMeta:
    """Retain the source identity, original text and validated JSON object."""

    path: Path
    text: str
    data: dict


def _validate_depth(text: str) -> None:
    """Bound JSON nesting before parsing, ignoring brackets inside strings."""
    depth = 0
    quoted = escaped = False
    for char in text:
        if escaped:
            escaped = False
            continue
        if quoted and char == "\\":
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if char in "[{":
            depth += 1
            if depth > 64:
                raise SessionMetaError("metadata_too_deep")
        elif char in "]}":
            depth -= 1


def _file_session_id(session_id) -> str:
    """Map a display session id to its on-disk filename prefix.

    Temporary sessions have no real identifier: they are displayed as
    ``(temp)`` and stored under the reserved ``topsailai`` prefix. Every other
    identifier must be safe to use as a single filename component.
    """
    if session_id in (TEMP_SESSION_MARKER, TEMP_SESSION_ID):
        return TEMP_SESSION_ID
    if (not isinstance(session_id, str) or ".." in session_id
            or _SESSION_ID_PATTERN.fullmatch(session_id) is None):
        raise SessionMetaError("unsafe_session_id")
    return session_id


def _task_directory(home: str) -> Path:
    """Resolve the trusted task directory that owns session metadata."""
    root = Path(home)
    if not root.is_absolute() or ".." in root.parts:
        raise SessionMetaError("invalid_home")
    # The caller-configured HOME is trusted deployment authority and may be an
    # alias. Resolve only that root; _read_metadata still rejects symlinks in
    # the canonical path and subtree.
    return root.resolve() / "workspace" / "task"


def read_session_meta(home: str, session_id: str, pid: int) -> SessionMeta:
    """Read at most 65537 bytes through verified no-follow file custody."""
    target = f"{session_id!r}/{pid!r}"
    try:
        if type(pid) is not int or pid <= 0:
            raise SessionMetaError("invalid_pid")
        prefix = _file_session_id(session_id)
        path = _task_directory(home) / f"{prefix}.{pid}.session.meta"
        content = _read_metadata(path)
        if content is None:
            raise SessionMetaError("missing")
        text = content.decode("utf-8")
        _validate_depth(text)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise SessionMetaError("invalid_object")
        # A temporary session persists an empty identifier, so both the empty
        # value and the reserved prefix denote the same absent identity.
        expected = ("", TEMP_SESSION_ID) if prefix == TEMP_SESSION_ID else (prefix,)
        if (data.get("session_id") not in expected or type(data.get("pid")) is not int
                or data["pid"] != pid):
            raise SessionMetaError("identity_mismatch")
        return SessionMeta(path, text, data)
    except (OSError, ValueError, RecursionError) as error:
        if isinstance(error, SessionMetaError):
            category = str(error)
        elif isinstance(error, FileNotFoundError):
            category = "missing"
        elif isinstance(error, (UnicodeError, json.JSONDecodeError, RecursionError)):
            category = type(error).__name__
        elif isinstance(error, OSError):
            category = f"{type(error).__name__}: errno={error.errno} detail={str(error)!r}"
        else:
            category = str(error)
        if category != "missing":
            LOGGER.warning("Session metadata unreadable: target=%s type=%s reason=%s",
                           target, type(error).__name__, category)
        raise SessionMetaError(category) from None


def print_workspace_meta(home: str, row: dict) -> bool:
    """Display only a standard session row's exact metadata, without refresh."""
    session_id, pid = row.get("session_id"), row.get("pid")
    target = f"{session_id!r}/{pid!r}"
    try:
        if row.get("is_task"):
            raise SessionMetaError("unsupported_task: select the corresponding session row")
        if type(pid) is not int or pid <= 0:
            raise SessionMetaError("unsupported_row")
        if ("session_pid" in row and
                (type(row["session_pid"]) is not int or row["session_pid"] != pid)):
            raise SessionMetaError("unsupported_row")
        # Temporary rows are displayed as ``(temp)`` but stored under the
        # reserved ``topsailai`` prefix, so compare against the file identity.
        prefix = _file_session_id(session_id)
        if row.get("filename") not in (
                f"{prefix}.{pid}.session.stdout", f"{prefix}.{pid}.session.stderr"):
            raise SessionMetaError("unsupported_row")
        result = read_session_meta(home, session_id, pid)
    except SessionMetaError as error:
        LOGGER.warning("Workspace meta failed: target=%s reason=%s", target, error)
        print(f"[ERROR] {error}: target={target}")
        return False
    print(f"[INFO] Session metadata: {str(result.path)!r}")
    print(result.text, end="" if result.text.endswith("\n") else "\n")
    return True
