"""Log file discovery, filename parsing, and process detection helpers."""

import ctypes
import os
import re
import subprocess
from typing import Callable, List, Optional, Tuple

from cli_topsailai.constants import (
    TEMP_SESSION_ID,
    TEMP_SESSION_MARKER,
    _TEMP_SESSION_ID,
    _TEMP_SESSION_MARKER,
)
from cli_topsailai.process import register_process, unregister_process


# Linux statx constants for retrieving file birth time.
_AT_FDCWD = -100
_STATX_BTIME = 0x00000800


class _StatxTimestamp(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_int64),
        ("tv_nsec", ctypes.c_uint32),
        ("__reserved", ctypes.c_int32),
    ]


class _Statx(ctypes.Structure):
    _fields_ = [
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("__spare0", ctypes.c_uint16 * 1),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", _StatxTimestamp),
        ("stx_btime", _StatxTimestamp),
        ("stx_ctime", _StatxTimestamp),
        ("stx_mtime", _StatxTimestamp),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("__spare2", ctypes.c_uint64 * 14),
    ]


def _get_birth_time(path: str) -> Optional[float]:
    """
    Return the file birth time as a float timestamp, or None if unavailable.

    Priority:
      1. ``os.stat().st_birthtime`` (available on macOS, Windows, some BSDs).
      2. The ``statx`` syscall with ``STATX_BTIME`` (Linux 4.11+).
      3. ``None`` if neither source can provide a birth time.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None

    birth = getattr(st, "st_birthtime", None)
    if birth is not None:
        return float(birth)

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        statx = libc.statx
        statx.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.POINTER(_Statx),
        ]
        statx.restype = ctypes.c_int
        buf = _Statx()
        rc = statx(_AT_FDCWD, os.fsencode(path), 0, _STATX_BTIME, ctypes.byref(buf))
        if rc == 0 and (buf.stx_mask & _STATX_BTIME):
            return buf.stx_btime.tv_sec + buf.stx_btime.tv_nsec / 1e9
    except (OSError, AttributeError, ctypes.ArgumentError):
        pass

    return None


def _parse_stdout_filename(filename: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Parse a session/task stdout filename.

    Filename conventions:
      - Session stdout: ``{session_id}.{pid}.session.stdout``
        The ``{pid}`` is the session process PID.  When ``{session_id}`` is
        ``topsailai`` the session id is undefined and is displayed as ``(temp)``.
      - Task stdout: ``{session_id}.{pid}[.{other}].task.stdout``
        The ``{pid}`` is the task (child) process PID.  ``{other}`` is an
        optional extra identifier.  ``topsailai`` as ``{session_id}`` means the
        same as for session stdout.

    Backward-compatible legacy formats are also accepted:
      - ``topsailai.{pid}.session.stdout`` / ``topsailai.{pid}.task.stdout``
      - ``{name}.{pid}.stdout`` / ``{name}.{pid}.stderr`` (generic)

    Returns:
        Tuple of (session_id, pid). session_id is None for temp sessions;
        pid is None if the filename does not match the expected format.
    """
    if filename.endswith(".task.stdout"):
        base = filename[: -len(".task.stdout")]
        if not base:
            return None, None
        parts = base.split(".")

        # Standard format: {session_id}.{pid}[.{other...}]
        # or topsailai.{pid}[.{other...}] for temp sessions.
        if len(parts) >= 2:
            try:
                pid = int(parts[1])
            except ValueError:
                return None, None
            session_id = None if parts[0] == "topsailai" else parts[0]
            return session_id, pid

    if filename.endswith(".session.stdout"):
        base = filename[: -len(".session.stdout")]
        if not base:
            return None, None

        parts = base.split(".")
        if len(parts) == 2 and parts[0] == "topsailai":
            # topsailai.{pid}.session.stdout
            try:
                return None, int(parts[1])
            except ValueError:
                return None, None

        # {session_id}.{pid}.session.stdout (pid is the last dot-separated part)
        try:
            pid = int(parts[-1])
        except ValueError:
            return None, None
        session_id = ".".join(parts[:-1])
        return session_id, pid

    # Generic .stdout / .stderr files: {name}.{pid}.stdout
    if filename.endswith(".stdout") or filename.endswith(".stderr"):
        base = filename.rsplit(".", 1)[0]
        if not base:
            return None, None
        parts = base.split(".")
        try:
            pid = int(parts[-1])
        except ValueError:
            return None, None
        return None, pid

    return None, None


def _get_pid_from_stdout_path(stdout_path: str) -> Optional[int]:
    """
    Extract the session process PID from a stdout file path.

    The stdout filename is created by the session process using its own PID
    (e.g. ``{session_id}.{pid}.session.stdout``).  This is more reliable than
    scanning for processes that currently have the file open, because other
    tools such as ``tail -f`` or stream watchers may also hold the file open
    and appear first in ``lsof`` output.

    Args:
        stdout_path: Absolute path to the session stdout file.

    Returns:
        The PID embedded in the filename, or ``None`` if the filename does
        not follow the expected convention.
    """
    if not stdout_path:
        return None
    filename = os.path.basename(stdout_path)
    _session_id, pid = _parse_stdout_filename(filename)
    return pid


def _is_temp_session(session_id: Optional[str]) -> bool:
    """Return True if the session_id represents a temporary session."""
    return session_id == "topsailai"


def _display_session_id(session_id: Optional[str], is_task: bool = False) -> str:
    """Return the user-facing label for a session id."""
    if _is_temp_session(session_id):
        label = "(temp)"
    else:
        label = session_id or "-"
    if is_task:
        label = f"(task) {label}"
    return label


# Public alias used by formatting helpers and other modules.
display_session_id = _display_session_id


def discover_log_files(
    task_dir: str,
    on_item: Optional[Callable[[dict], None]] = None,
) -> List[dict]:
    """
    Discover all .stdout and .stderr log files in the task directory.
    Supports .session.stdout, .task.stdout, and generic naming conventions.

    If *on_item* is provided, it is invoked for each discovered file dict
    before the final sorted list is returned.  This lets callers show
    incremental progress while scanning a large task directory.
    """
    log_files = []
    if not os.path.isdir(task_dir):
        return log_files

    for entry in os.listdir(task_dir):
        if not (entry.endswith(".stdout") or entry.endswith(".stderr")):
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.isfile(full_path):
            continue

        session_id = None
        pid = None
        is_task = False
        if entry.endswith(".session.stdout") or entry.endswith(".task.stdout"):
            session_id, pid = _parse_stdout_filename(entry)
            is_task = entry.endswith(".task.stdout")
            # Skip files that do not match the expected naming convention.
            if pid is None:
                continue
            # Temp sessions have no real session id; expose a user-facing label.
            if session_id is None and entry.startswith("topsailai."):
                session_id = "(temp)"
        elif entry.endswith(".stdout") or entry.endswith(".stderr"):
            session_id, pid = _parse_stdout_filename(entry)

        stat_info = os.stat(full_path)
        # Prefer real birth time when available.  On Linux this requires the
        # statx syscall; fall back to st_ctime (inode change time) otherwise.
        created = _get_birth_time(full_path)
        if created is None:
            created = stat_info.st_ctime
        file_info = {
            "filename": entry,
            "path": full_path,
            "session_id": session_id,
            "is_task": is_task,
            "pid": pid,
            "size": stat_info.st_size,
            "mtime": stat_info.st_mtime,
            "ctime": created,
        }
        log_files.append(file_info)
        if on_item is not None:
            on_item(file_info)

    log_files.sort(key=lambda x: x["ctime"])
    return log_files


def get_file_pid(filepath: str) -> Optional[int]:
    """
    Extract the PID associated with a stdout/stderr log file.

    First tries to parse the PID from the filename itself (e.g.
    ``{session_id}.{pid}.task.stdout``).  If the filename does not contain a
    parseable PID, falls back to scanning for processes that currently have
    the file open using ``lsof`` and then ``fuser``.

    All spawned subprocesses are tracked and cleaned up on exit.
    """
    if not filepath:
        return None

    filename = os.path.basename(filepath)
    _session_id, pid = _parse_stdout_filename(filename)
    if pid is not None:
        return pid

    # Fallback to lsof
    try:
        proc = subprocess.Popen(
            ["lsof", "-t", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        try:
            stdout, _ = proc.communicate(timeout=3)
            if proc.returncode == 0 and stdout.strip():
                pids = stdout.strip().splitlines()
                if pids:
                    return int(pids[0])
        finally:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1)
    except Exception:
        pass

    # Fallback to fuser
    try:
        proc = subprocess.Popen(
            ["fuser", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        try:
            stdout, _ = proc.communicate(timeout=3)
            if proc.returncode == 0 and stdout.strip():
                parts = stdout.strip().split(":")
                if len(parts) >= 2:
                    pids = parts[1].strip().split()
                    if pids:
                        return int(pids[0])
        finally:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1)
    except Exception:
        pass

    return None


def is_file_in_use(filepath: str) -> bool:
    """Return True if any process currently has *filepath* open.

    Checks ``lsof`` first, then falls back to ``fuser``.  If neither tool is
    available or neither reports a holder, the file is considered not in use.
    All spawned subprocesses are tracked and cleaned up on exit.
    """
    if not filepath or not os.path.exists(filepath):
        return False

    for cmd in (["lsof", "-t", filepath], ["fuser", filepath]):
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            register_process(proc)
            try:
                stdout, _ = proc.communicate(timeout=3)
                if proc.returncode == 0 and stdout.strip():
                    return True
            finally:
                unregister_process(proc)
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=1)
        except Exception:
            pass

    return False


def _find_session_stdout_file(task_dir: str, session_id: str) -> Optional[str]:
    """
    Find the most recent session stdout file for a session.

    Only ``*.session.stdout`` files are considered because they are created
    by the session process using its own PID.  Task stdout files
    (``*.task.stdout``) belong to child task processes and must not be used
    to resolve the session's named pipe.
    """
    if not os.path.isdir(task_dir):
        return None

    candidates = []
    for entry in os.listdir(task_dir):
        if not entry.endswith(".session.stdout"):
            continue
        full_path = os.path.join(task_dir, entry)
        if not os.path.isfile(full_path):
            continue
        sid, _pid = _parse_stdout_filename(entry)
        if sid == session_id or (sid is None and session_id == _TEMP_SESSION_ID):
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue
            candidates.append((full_path, mtime))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def _build_pipe_path(task_dir: str, session_id: str, pid: int) -> str:
    """Build the named-pipe path for a session and process."""
    if session_id == _TEMP_SESSION_MARKER:
        session_id = _TEMP_SESSION_ID
    return os.path.join(task_dir, f"{session_id}.{pid}.session.pipe")


def _resolve_literal_session_id(arg: str) -> str:
    """Map user-facing '(temp)' back to the internal temporary session ID."""
    if arg == _TEMP_SESSION_MARKER:
        return _TEMP_SESSION_ID
    return arg


def _resolve_session_id_from_arg(
    arg: str, task_dir: str, log_files: List[dict], allow_temp: bool = False
) -> Optional[str]:
    """
    Resolve a session identifier from a command argument.

    Numeric arguments are mapped to the corresponding 1-based entry in the
    file list. Literal session IDs are returned as-is, with '(temp)' mapped
    to the internal temporary session ID.

    By default, temporary sessions are excluded when resolving by numeric
    index to avoid accidentally targeting a transient session. Callers that
    explicitly want to allow this (e.g. /send) can pass allow_temp=True.
    """
    arg = arg.strip()
    if not arg:
        return None
    if arg.isdigit():
        idx = int(arg) - 1
        if idx < 0 or idx >= len(log_files):
            return None
        entry = log_files[idx]
        session_id = entry.get("session_id", "")
        if session_id == _TEMP_SESSION_MARKER:
            if not allow_temp:
                return None
            session_id = _TEMP_SESSION_ID
        return session_id

    session_id = _resolve_literal_session_id(arg)
    return session_id if session_id else None


def _resolve_send_target_from_arg(
    arg: str, log_files: List[dict]
) -> Optional[Tuple[str, Optional[str], Optional[int]]]:
    """
    Resolve a /send argument to a concrete session target.

    Returns a tuple of (session_id, stdout_path, pid). For numeric selections
    the exact stdout file path and the PID recorded in the task list entry are
    returned so that temporary sessions are not confused with each other and
    the caller can prefer the list-recorded PID. For named session IDs the
    stdout path and pid are left None and resolved later.
    """
    arg = arg.strip()
    if not arg:
        return None
    if arg.isdigit():
        idx = int(arg) - 1
        if idx < 0 or idx >= len(log_files):
            return None
        entry = log_files[idx]
        session_id = entry.get("session_id", "")
        if session_id == _TEMP_SESSION_MARKER:
            session_id = _TEMP_SESSION_ID
        return session_id, entry.get("path"), entry.get("pid")

    session_id = _resolve_session_id_from_arg(arg, "", log_files, allow_temp=True)
    return (session_id, None, None) if session_id else None
