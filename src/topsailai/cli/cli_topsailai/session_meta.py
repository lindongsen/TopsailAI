"""Read exact session metadata without acquiring process authority.

Author: DawsonLin
"""

from dataclasses import dataclass
import json
import logging
from pathlib import Path

from cli_topsailai.session_driver import metadata_path, _read_metadata

LOGGER = logging.getLogger(__name__)


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


def read_session_meta(home: str, session_id: str, pid: int) -> SessionMeta:
    """Read at most 65537 bytes through verified no-follow file custody."""
    target = f"{session_id!r}/{pid!r}"
    try:
        if type(pid) is not int or pid <= 0:
            raise SessionMetaError("invalid_pid")
        directory = metadata_path(home, session_id).parent.parent
        path = directory / f"{session_id}.{pid}.session.meta"
        content = _read_metadata(path)
        if content is None:
            raise SessionMetaError("missing")
        text = content.decode("utf-8")
        _validate_depth(text)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise SessionMetaError("invalid_object")
        if (data.get("session_id") != session_id or type(data.get("pid")) is not int
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
        if row.get("filename") not in (
                f"{session_id}.{pid}.session.stdout", f"{session_id}.{pid}.session.stderr"):
            raise SessionMetaError("unsupported_row")
        result = read_session_meta(home, session_id, pid)
    except SessionMetaError as error:
        LOGGER.warning("Workspace meta failed: target=%s reason=%s", target, error)
        print(f"[ERROR] {error}: target={target}")
        return False
    print(f"[INFO] Session metadata: {str(result.path)!r}")
    print(result.text, end="" if result.text.endswith("\n") else "\n")
    return True
