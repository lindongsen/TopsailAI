"""Resolve a single runtime session without fallback or endpoint I/O.

Filename evidence and PID liveness assume trusted per-user task storage; they
cannot prove process ownership or prevent PID reuse and post-check races.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import stat
from typing import Callable, Literal

from cli_topsailai.log_files import parse_stdout_filename


class ProcessState(Enum):
    """Represent process observations without treating uncertainty as death."""

    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


_EXIT_CODES = {
    "usage_error": 2,
    "target_not_found": 3,
    "target_mismatch": 3,
    "stale_target": 3,
    "ambiguous_target": 3,
    "permission_denied": 4,
    "endpoint_missing": 4,
    "endpoint_invalid": 4,
    "unsupported_transport": 4,
}


class RuntimeTargetError(Exception):
    """Carry a stable machine error and its read-only exit-code mapping."""

    def __init__(self, error_code: str, message: str):
        """Initialize a classified failure without printing or exiting."""
        super().__init__(message)
        self.error_code = error_code

    @property
    def exit_code(self) -> int:
        """Return the exit category for this target failure."""
        return _EXIT_CODES[self.error_code]


@dataclass(frozen=True)
class RuntimeTarget:
    """Record exact session evidence; no endpoint may select another PID."""

    session_id: str
    pid: int
    stdout_path: Path
    task_dir: Path


def _valid_session(session_id: object) -> bool:
    """Validate identifiers without normalization or wildcard interpretation."""
    return (
        isinstance(session_id, str)
        and bool(session_id)
        and session_id not in (".", "..")
        and not any(char in session_id for char in ("\0", "/", "\\"))
    )


def _absolute_path(path: Path) -> Path:
    """Require an absolute path and normalize only lexical dot components."""
    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimeTargetError("usage_error", "An absolute Path is required")
    return Path(os.path.abspath(path))


def _lstat(path: Path):
    """Translate access denial while preserving all other OS error evidence."""
    try:
        return path.lstat()
    except PermissionError as exc:
        raise RuntimeTargetError("permission_denied", "Path inspection denied") from exc


def _check_directory(task_dir: Path, *, missing_code: str) -> None:
    """Require a real task directory, without following its final symlink."""
    try:
        mode = _lstat(task_dir).st_mode
    except FileNotFoundError as exc:
        raise RuntimeTargetError(missing_code, "Task directory is missing") from exc
    if not stat.S_ISDIR(mode):
        raise RuntimeTargetError("endpoint_invalid", "Task path is not a directory")


def probe_process(pid: int) -> ProcessState:
    """Use signal zero only on POSIX; fail closed on unsupported platforms."""
    if os.name != "posix":
        # Windows os.kill(pid, 0) is not a portable harmless liveness probe.
        return ProcessState.UNKNOWN
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ProcessState.DEAD
    except PermissionError as exc:
        raise RuntimeTargetError("permission_denied", "Process inspection denied") from exc
    except (OverflowError, ValueError, NotImplementedError):
        return ProcessState.UNKNOWN
    except OSError:
        return ProcessState.UNKNOWN
    return ProcessState.ALIVE


def _observe(pid: int, process_probe: Callable[[int], ProcessState]) -> ProcessState:
    """Fail closed on unknown results and translate injected permission errors."""
    try:
        state = process_probe(pid)
    except PermissionError as exc:
        raise RuntimeTargetError("permission_denied", "Process inspection denied") from exc
    if state not in (ProcessState.ALIVE, ProcessState.DEAD):
        raise RuntimeTargetError("unsupported_transport", "Process state cannot be verified")
    return state


def _session_record(path: Path, task_dir: Path) -> RuntimeTarget | None:
    """Accept only regular session stdout files parsed by the shared helper."""
    if not path.name.endswith(".session.stdout"):
        return None
    try:
        mode = _lstat(path).st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode):
        return None
    session_id, pid_text = parse_stdout_filename(path.name)
    if not _valid_session(session_id) or pid_text is None:
        return None
    pid = int(pid_text)
    if pid <= 0:
        return None
    return RuntimeTarget(session_id, pid, path, task_dir)


def resolve_runtime_target(
    task_dir: Path,
    *,
    session_id: str | None = None,
    pid: int | None = None,
    process_probe: Callable[[int], ProcessState] = probe_process,
) -> RuntimeTarget:
    """Resolve exactly one living session, never by age or endpoint presence."""
    if session_id is None and pid is None:
        raise RuntimeTargetError("usage_error", "A session or PID selector is required")
    if session_id is not None and not _valid_session(session_id):
        raise RuntimeTargetError("usage_error", "Invalid session identifier")
    if pid is not None and (type(pid) is not int or pid <= 0):
        raise RuntimeTargetError("usage_error", "PID must be a positive integer")
    task_dir = _absolute_path(task_dir)
    _check_directory(task_dir, missing_code="target_not_found")
    try:
        records = [record for path in task_dir.iterdir()
                   if (record := _session_record(path, task_dir)) is not None]
    except PermissionError as exc:
        raise RuntimeTargetError("permission_denied", "Task enumeration denied") from exc
    matches = [record for record in records
               if (session_id is None or record.session_id == session_id)
               and (pid is None or record.pid == pid)]
    if not matches:
        mismatch = session_id is not None and pid is not None and any(
            record.pid == pid and record.session_id != session_id for record in records
        )
        code = "target_mismatch" if mismatch else "target_not_found"
        raise RuntimeTargetError(code, "No exact session/PID target matches")
    alive = [record for record in matches
             if _observe(record.pid, process_probe) is ProcessState.ALIVE]
    if not alive:
        raise RuntimeTargetError("stale_target", "Matching session processes have exited")
    if len(alive) != 1:
        raise RuntimeTargetError("ambiguous_target", "More than one session target is alive")
    return alive[0]


def revalidate_runtime_target(
    target: RuntimeTarget,
    *,
    process_probe: Callable[[int], ProcessState] = probe_process,
) -> None:
    """Recheck original evidence and the same PID without target rediscovery."""
    task_dir = _absolute_path(target.task_dir)
    stdout_path = _absolute_path(target.stdout_path)
    if stdout_path.parent != task_dir:
        raise RuntimeTargetError("stale_target", "Session evidence is outside task directory")
    _check_directory(task_dir, missing_code="stale_target")
    record = _session_record(stdout_path, task_dir)
    if record is None or (record.session_id, record.pid) != (target.session_id, target.pid):
        raise RuntimeTargetError("stale_target", "Original session evidence has changed")
    if _observe(target.pid, process_probe) is ProcessState.DEAD:
        raise RuntimeTargetError("stale_target", "Original session process has exited")


def validate_runtime_endpoint(
    target: RuntimeTarget,
    *,
    endpoint_path: Path,
    endpoint_kind: Literal["fifo", "socket", "injection"],
) -> Path:
    """Check endpoint type and lexical custody without creating or opening it.

    The caller must recheck the opened resource where supported; this snapshot
    does not protect a later open against concurrent filesystem replacement.
    """
    if endpoint_kind not in ("fifo", "socket", "injection"):
        raise RuntimeTargetError("usage_error", "Unknown endpoint kind")
    task_dir = _absolute_path(target.task_dir)
    endpoint_path = _absolute_path(endpoint_path)
    if not endpoint_path.is_relative_to(task_dir) or endpoint_path == task_dir:
        raise RuntimeTargetError("endpoint_invalid", "Endpoint is outside task directory")
    _check_directory(task_dir, missing_code="endpoint_missing")
    # Reject intermediate links as well as the endpoint itself.
    for parent in reversed(endpoint_path.parent.relative_to(task_dir).parents):
        _check_directory(task_dir / parent, missing_code="endpoint_missing")
    if endpoint_path.parent != task_dir:
        _check_directory(endpoint_path.parent, missing_code="endpoint_missing")
    try:
        mode = _lstat(endpoint_path).st_mode
    except FileNotFoundError as exc:
        if endpoint_kind == "injection":
            return endpoint_path
        raise RuntimeTargetError("endpoint_missing", "Required endpoint is missing") from exc
    expected = {"fifo": stat.S_ISFIFO, "socket": stat.S_ISSOCK, "injection": stat.S_ISREG}
    if not expected[endpoint_kind](mode):
        raise RuntimeTargetError("endpoint_invalid", "Endpoint has an invalid type")
    return endpoint_path
