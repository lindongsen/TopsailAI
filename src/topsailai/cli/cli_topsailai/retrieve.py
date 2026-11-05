"""Message/session retrieval helpers for the TopsailAI CLI."""

import json
import os
import stat
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from cli_topsailai.colors import Colors, print_error, print_info
from cli_topsailai.constants import DEFAULT_LIMIT, TEMP_SESSION_ID, TEMP_SESSION_MARKER
from cli_topsailai.formatting import print_header, sanitize_terminal_text
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.process import register_process, unregister_process

def load_session_index(sessions_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load the session index JSON file."""
    if sessions_dir is None:
        sessions_dir = os.path.join(get_topsailai_home(), "sessions")
    index_path = os.path.join(sessions_dir, "index.json")
    if not os.path.isfile(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_session_index(
    index: Dict[str, Any], sessions_dir: Optional[str] = None
) -> None:
    """Save the session index JSON file."""
    if sessions_dir is None:
        sessions_dir = os.path.join(get_topsailai_home(), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    index_path = os.path.join(sessions_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)


def list_sessions(
    sessions_dir: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List sessions from the session index.

    Args:
        sessions_dir: Directory containing session files.
        limit: Maximum number of sessions to return.
        offset: Number of sessions to skip.

    Returns:
        List of session metadata dictionaries.
    """
    index = load_session_index(sessions_dir)
    sessions = list(index.values())
    sessions.sort(key=lambda s: s.get("update_at_ms", 0), reverse=True)
    return sessions[offset : offset + limit]


def get_session_messages(
    session_id: str,
    sessions_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve messages for a session.

    Args:
        session_id: Session identifier.
        sessions_dir: Directory containing session files.

    Returns:
        List of message dictionaries.
    """
    if sessions_dir is None:
        sessions_dir = os.path.join(get_topsailai_home(), "sessions")
    messages_path = os.path.join(sessions_dir, f"{session_id}.json")
    if not os.path.isfile(messages_path):
        return []
    try:
        with open(messages_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("messages", [])
        return []
    except (json.JSONDecodeError, OSError):
        return []


def print_messages(messages: List[Dict[str, Any]], raw: bool = False) -> None:
    """Print messages in human-readable or raw JSON form."""
    if raw:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
        return
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        print_info(f"[{role}]")
        print(content)


def retrieve_session(
    session_id: str,
    max_chars: Optional[int] = None,
) -> None:
    """
    Retrieve session content via the ``topsailai_retrieve_messages`` command.

    The subprocess is tracked and will be cleaned up on script exit.

    Args:
        session_id: Session identifier to retrieve.
        max_chars: If provided, truncate message content to this many
            characters by passing ``--max-chars`` to the retrieval command.
    """
    print_header(f"Session Content: {session_id}")
    proc = None
    cmd = ["topsailai_retrieve_messages", session_id]
    if max_chars is not None:
        cmd.extend(["--max-chars", str(max_chars)])
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        stdout, stderr = proc.communicate(timeout=30)
        if proc.returncode == 0:
            print(f"{Colors.WHITE}{stdout}{Colors.RESET}")
        else:
            print(
                f"{Colors.RED}[ERROR] topsailai_retrieve_messages failed: "
                f"{stderr.strip()}{Colors.RESET}"
            )
    except FileNotFoundError:
        print(
            f"{Colors.RED}[ERROR] Command 'topsailai_retrieve_messages' not found. "
            f"Please ensure it is installed and in PATH.{Colors.RESET}"
        )
    except subprocess.TimeoutExpired:
        print(f"{Colors.RED}[ERROR] Command timed out after 30s.{Colors.RESET}")
        if proc and proc.poll() is None:
            proc.kill()
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to retrieve session: {e}{Colors.RESET}")
    finally:
        if proc:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass


# Instruction that returns the current session history as formatted text.
CONTROL_HISTORY_INSTRUCTION = "ctx.history"

# Characters that must never appear in a session identifier used as a filename
# component, because the identifier is composed into a socket path.
_UNSAFE_IDENTIFIER_CHARS = ("\0", "/", "\\")


class ControlHistoryError(ValueError):
    """Classify why a control-channel history request cannot proceed."""

    def __init__(self, error_code: str, message: str):
        """Store a stable machine category next to the diagnostic message."""
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class ControlHistoryTarget:
    """Record the exact endpoint and identity that may answer a history query."""

    socket_path: str
    session_id: str
    pid: int


def _file_session_id(session_id: Optional[str]) -> str:
    """Map a display session id to its on-disk filename prefix.

    Temporary sessions have no real identifier: they are displayed as
    ``(temp)`` and stored under the reserved ``topsailai`` prefix. Every other
    identifier is validated before it is composed into a path.
    """
    if session_id in (None, "", TEMP_SESSION_MARKER, TEMP_SESSION_ID):
        return TEMP_SESSION_ID
    if not isinstance(session_id, str):
        raise ControlHistoryError("usage_error", "invalid session id")
    if (session_id in (".", "..") or ".." in session_id
            or any(char in session_id for char in _UNSAFE_IDENTIFIER_CHARS)):
        raise ControlHistoryError(
            "usage_error", f"unsafe session id: {session_id!r}"
        )
    return session_id


def _row_session_pid(row: Dict[str, Any]) -> int:
    """Return the session-process PID that owns the row's control socket.

    A task row is owned by its parent session process, so its own PID is never
    used. An ambiguous parent fails closed instead of guessing.
    """
    if row.get("is_task"):
        pid = row.get("session_pid")
        if type(pid) is not int or pid <= 0:
            raise ControlHistoryError(
                "unsupported_row",
                "task row has no unambiguous parent session PID",
            )
        return pid
    pid = row.get("session_pid")
    if type(pid) is not int or pid <= 0:
        pid = row.get("pid")
    if type(pid) is not int or pid <= 0:
        raise ControlHistoryError("unsupported_row", "row has no usable session PID")
    return pid


def _is_socket(path: str) -> bool:
    """Report whether the path itself is a socket, without following symlinks."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(info.st_mode)


def _is_live_pid(pid: int) -> bool:
    """Report whether a socket owner is provably alive.

    A socket file outlives its owner process, so a stale file cannot answer a
    request. Only a provably alive owner counts as a channel; an unknown or
    unreadable process state is treated as not live, so a stale socket is never
    preferred over a live one.
    """
    from cli_topsailai.runtime_target import ProcessState, probe_process

    try:
        return probe_process(pid) is ProcessState.ALIVE
    except Exception:
        return False


def _scan_session_sockets(task_dir: str, file_session_id: str) -> List[Any]:
    """Enumerate existing control sockets belonging to one session identity."""
    try:
        entries = os.listdir(task_dir)
    except OSError:
        return []
    found = []
    for entry in entries:
        if not entry.endswith(".session.sock"):
            continue
        parts = entry[: -len(".session.sock")].split(".")
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid <= 0 or ".".join(parts[:-1]) != file_session_id:
            continue
        path = os.path.join(task_dir, entry)
        if _is_socket(path):
            found.append((path, pid))
    found.sort(key=lambda item: item[1])
    return found


def resolve_control_history_target(
    task_dir: str,
    *,
    row: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Optional[ControlHistoryTarget]:
    """Resolve the control socket that can answer ``ctx.history`` for a target.

    Args:
        task_dir: Trusted task directory that owns session sockets.
        row: A discovered log row, used when a list entry was selected.
        session_id: A literal session argument, used when no row was selected.

    Returns:
        The resolved target, or ``None`` when no control channel exists for the
        target. ``None`` is the only "no channel" answer, so a caller can keep
        its existing message instead of reporting a transport failure.

    Raises:
        ControlHistoryError: The target is unsafe or ambiguous.
    """
    from cli_topsailai.runtime_control import build_socket_path

    if row is not None:
        file_session_id = _file_session_id(row.get("session_id"))
        pid = _row_session_pid(row)
        socket_path = build_socket_path(task_dir, file_session_id, str(pid))
        if not _is_socket(socket_path):
            return None
        return ControlHistoryTarget(socket_path, file_session_id, pid)

    file_session_id = _file_session_id(session_id)
    candidates = _scan_session_sockets(task_dir, file_session_id)
    # A socket file outlives its owner process, so a stale file cannot answer a
    # request. Only a provably live owner is a channel, which also keeps an old
    # socket from making a single live identity look ambiguous.
    live = [item for item in candidates if _is_live_pid(item[1])]
    if not live:
        return None
    if len(live) > 1:
        raise ControlHistoryError(
            "ambiguous_target",
            f"multiple control sockets for session {file_session_id!r}",
        )
    socket_path, pid = live[0]
    return ControlHistoryTarget(socket_path, file_session_id, pid)


def _render_history_result(result: Any) -> str:
    """Render an instruction result, preserving real newlines in strings."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def retrieve_session_history_via_control(
    target: ControlHistoryTarget,
    *,
    timeout: float = 5.0,
    sender=None,
) -> bool:
    """Print one session's history through its control channel.

    Exactly one request is sent. A duplicate instruction call can have real
    effects, so a failure is reported and never retried.

    Args:
        target: The resolved endpoint and identity to query.
        timeout: Transport budget in seconds for the single request.
        sender: Optional delivery seam, defaulting to the real transport.

    Returns:
        ``True`` when a correlated ``ok`` response was printed, else ``False``.
    """
    from cli_topsailai.runtime_control import ControlDeliveryError, send_to_control

    display_id = (
        TEMP_SESSION_MARKER
        if target.session_id == TEMP_SESSION_ID
        else target.session_id
    )
    print_header(f"Session Content: {display_id}")
    send = sender or send_to_control
    try:
        result = send(
            target.socket_path,
            "call_instruction",
            {"instruction": CONTROL_HISTORY_INSTRUCTION},
            timeout=timeout,
        )
    except ControlDeliveryError as exc:
        print(
            f"{Colors.RED}[ERROR] Control history request failed: "
            f"{exc.error_code}: {exc}{Colors.RESET}"
        )
        return False
    except Exception as exc:
        print(
            f"{Colors.RED}[ERROR] Control history request failed: "
            f"{type(exc).__name__}: {exc}{Colors.RESET}"
        )
        return False
    print(sanitize_terminal_text(_render_history_result(result.response.get("result"))))
    return True
