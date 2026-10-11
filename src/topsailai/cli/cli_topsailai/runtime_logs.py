"""Read bounded session log snapshots without requiring a living process.

Author: DawsonLin
"""

from dataclasses import dataclass, asdict
import errno
import os
from pathlib import Path
import re
import stat

from cli_topsailai.runtime_target import RuntimeTarget, RuntimeTargetError
from cli_topsailai.log_files import parse_stdout_filename

MAX_LINES = 10000
SCAN_BUDGET = 8 * 1024 * 1024
CHUNK_SIZE = 64 * 1024


class RuntimeLogError(RuntimeTargetError):
    """Classify local read errors without transport semantics."""

    @property
    def exit_code(self):
        """Map snapshot failures to the existing I/O error category."""
        return 5 if self.error_code in ("log_changed", "log_read_failed") else super().exit_code


@dataclass(frozen=True)
class LogTail:
    """Capture a bounded read and its explicit completeness evidence."""

    filename: str
    lines: tuple[str, ...]
    requested_lines: int
    returned_lines: int
    total_lines: int | None
    truncated: bool
    scan_limited: bool
    bytes_read: int
    snapshot_size_bytes: int

    def response(self):
        """Detach the immutable result into the public JSON shape."""
        value = asdict(self)
        value["lines"] = list(self.lines)
        return value


def _io_error(exc, *, discovery=False):
    """Translate filesystem failures without echoing paths or exception text."""
    if isinstance(exc, PermissionError):
        code = "permission_denied"
    elif isinstance(exc, FileNotFoundError):
        code = "target_not_found" if discovery else "endpoint_missing"
    elif exc.errno in (errno.ELOOP, errno.ENOTDIR):
        code = "endpoint_invalid"
    else:
        code = "log_read_failed"
    return RuntimeLogError(code, "Unable to read session log")


def resolve_log_target(task_dir, *, session_id=None, pid=None):
    """Select exactly one regular session stdout, without process probes."""
    if (session_id is None and pid is None) or (pid is not None and (type(pid) is not int or pid <= 0)):
        raise RuntimeTargetError("usage_error", "Supply a session or positive PID")
    if session_id is not None and (not isinstance(session_id, str) or not session_id or
                                  session_id in (".", "..") or re.search(r"[\s/\\\x00]", session_id)):
        raise RuntimeTargetError("usage_error", "Invalid session identifier")
    folder = Path(task_dir)
    if not folder.is_absolute() or ".." in folder.parts:
        raise RuntimeTargetError("usage_error", "Task directory must be absolute")
    try:
        if not stat.S_ISDIR(folder.lstat().st_mode):
            raise RuntimeLogError("endpoint_invalid", "Invalid task directory")
        candidates = []
        for path in folder.iterdir():
            if not path.name.endswith(".session.stdout"):
                continue
            parsed_session, raw_pid = parse_stdout_filename(path.name)
            parsed_pid = int(raw_pid) if raw_pid and raw_pid.isdecimal() else None
            if parsed_pid is None or parsed_pid <= 0 or not stat.S_ISREG(path.lstat().st_mode):
                continue
            candidates.append(RuntimeTarget(session_id=parsed_session or "topsailai", pid=parsed_pid,
                                            stdout_path=path, task_dir=folder))
    except OSError as exc:
        raise _io_error(exc, discovery=True) from exc
    matches = [item for item in candidates if
               (session_id is None or item.session_id == session_id) and
               (pid is None or item.pid == pid)]
    if not matches:
        code = "target_mismatch" if session_id is not None and pid is not None and any(
            item.pid == pid for item in candidates) else "target_not_found"
        raise RuntimeTargetError(code, "No matching session log")
    if len(matches) != 1:
        raise RuntimeTargetError("ambiguous_target", "Specify an exact session PID")
    return matches[0]


def _same_identity(left, right):
    """Compare meaningful file identities without requiring POSIX support."""
    return not (left.st_ino and right.st_ino) or (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _scan(stream, size, count, chunk_size, budget):
    """Read backwards up to a byte budget, locating physical LF boundaries."""
    position, chunks, bytes_read, delimiters = size, [], 0, 0
    terminal_lf = False
    while position > 0 and bytes_read < budget:
        amount = min(position, chunk_size, budget - bytes_read)
        position -= amount
        stream.seek(position)
        chunk = stream.read(amount)
        if len(chunk) != amount:
            raise RuntimeLogError("log_changed", "Session log changed during read")
        if not chunks:
            terminal_lf = chunk.endswith(b"\n")
        chunks.append(chunk)
        bytes_read += len(chunk)
        delimiters += chunk.count(b"\n")
        if delimiters >= count + int(terminal_lf):
            break
    data = b"".join(reversed(chunks))
    limited = position > 0 and delimiters < count + int(terminal_lf)
    if position > 0:
        boundary = data.find(b"\n")
        data = data[boundary + 1:] if boundary >= 0 else b""
    records = data.split(b"\n") if data else []
    if data.endswith(b"\n"):
        records.pop()
    total = len(records) if position == 0 else None
    truncated = position > 0 or len(records) > count
    start = max(0, len(records) - count)
    lines = tuple((record.removesuffix(b"\r") if index < len(records) - 1 or
                   terminal_lf else record).decode("utf-8", errors="replace")
                  for index, record in enumerate(records) if index >= start)
    return lines, total, truncated, limited, bytes_read


def read_log_tail(target, count=20, *, chunk_size=CHUNK_SIZE, budget=SCAN_BUDGET):
    """Open one regular file, tail its captured size, and close on every exit."""
    if type(count) is not int or not 1 <= count <= MAX_LINES:
        raise RuntimeTargetError("usage_error", "Invalid line count")
    if type(chunk_size) is not int or type(budget) is not int or chunk_size <= 0 or budget <= 0:
        raise RuntimeTargetError("usage_error", "Invalid read bounds")
    try:
        path = Path(target.stdout_path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeLogError("endpoint_invalid", "Invalid session log file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            stream = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        with stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise RuntimeLogError("endpoint_invalid", "Invalid session log file")
            if not _same_identity(before, opened):
                raise RuntimeLogError("log_changed", "Session log changed before read")
            lines, total, truncated, limited, amount = _scan(stream, opened.st_size, count, chunk_size, budget)
            after = os.fstat(stream.fileno())
            if after.st_size < opened.st_size or not _same_identity(opened, after):
                raise RuntimeLogError("log_changed", "Session log changed during read")
        return LogTail(str(path), lines, count, len(lines), total, truncated, limited, amount, opened.st_size)
    except OSError as exc:
        raise _io_error(exc) from exc
