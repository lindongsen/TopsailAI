"""Read bounded driver log snapshots for the workspace CLI."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import stat

from cli_topsailai.runtime_logs import CHUNK_SIZE, SCAN_BUDGET, LogTail, _scan
from cli_topsailai.session_driver import _handoff_directory, metadata_path
from cli_topsailai.session_driver_launcher import _row_identity


def bind_driver_row(rows, index, home, discover):
    """Bind a displayed row to the same session stdout identity after refresh."""
    if type(index) is not int or not 1 <= index <= len(rows):
        raise ValueError("invalid_row_index")
    selected = rows[index - 1]
    session, pid = _row_identity(selected, Path(home))
    fresh = list(discover())
    matches = [row for row in fresh
               if row.get("session_id") == session
               and row.get("pid") == pid
               and row.get("filename") == selected.get("filename")
               and not row.get("is_task")]
    if len(matches) != 1:
        raise ValueError("ineligible_or_changed_row")
    return session, pid


def _open_regular(path):
    """Open a regular driver record through descriptor-relative no-follow custody."""
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NONBLOCK") or os.open not in os.supports_dir_fd):
        raise ValueError("safe_open_unsupported")
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    stream = None
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            parent = directory
            directory = None
            directory = _handoff_directory(parent, child)
        before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("log_not_regular")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        owned = True
        try:
            stream = os.fdopen(descriptor, "rb")
            owned = False
        finally:
            if owned:
                os.close(descriptor)
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError("log_changed")
        parent = directory
        directory = None
        os.close(parent)
        return stream
    except BaseException as error:
        if stream is not None:
            try:
                stream.close()
            except BaseException as cleanup_error:
                error.add_note(f"log stream cleanup failed: {cleanup_error!r}")
            stream = None
        raise
    finally:
        if directory is not None:
            os.close(directory)


def read_driver_log(home, session_id, *, lines=20):
    """Read the active session-level driver log once, without fallback files."""
    path = metadata_path(home, session_id).with_suffix(".log")
    try:
        stream = _open_regular(path)
        try:
            with stream:
                opened = os.fstat(stream.fileno())
                result = _scan(stream, opened.st_size, lines, CHUNK_SIZE, SCAN_BUDGET)
                after = os.fstat(stream.fileno())
                if after.st_size < opened.st_size or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                    raise ValueError("log_changed")
                content, total, truncated, limited, amount = result
                return LogTail(str(path), content, lines, len(content), total, truncated, limited, amount, opened.st_size)
        except (ValueError, OSError) as error:
            raise ValueError("log_read_failed") from error
    except FileNotFoundError as error:
        raise ValueError("log_missing") from error
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ValueError("log_unsafe_path") from error
        raise ValueError("log_unreadable") from error

def _record_missing_message(kind, path):
    """Describe absence without exposing rejected record contents."""
    return (f"{kind}_missing: path={path}; the active record may not have been "
            "created or may have been cleaned up when the driver exited")


def print_driver_log(home, rows, index, discover):
    """Bind and print the selected driver's bounded log snapshot."""
    session = None
    try:
        session, pid = bind_driver_row(rows, index, home, discover)
        result = read_driver_log(home, session)
    except (ValueError, TypeError, OSError) as error:
        message = str(error)
        if message == "log_missing" and session is not None:
            message = _record_missing_message("log", metadata_path(home, session).with_suffix(".log"))
        print(f"[ERROR] Driver log rejected: {message}")
        return False
    print(f"[INFO] Driver log: session={session}; session_pid={pid}; path={result.filename}; last={result.requested_lines} lines")
    if not result.lines:
        print("[INFO] Driver log is empty; it may not have been written yet or may have been cleaned up.")
    for line in result.lines:
        print(line)
    if result.truncated:
        print("[WARN] Driver log output is truncated to the requested tail.")
    if result.scan_limited:
        print("[WARN] Driver log scan budget limited the result.")
    return True
