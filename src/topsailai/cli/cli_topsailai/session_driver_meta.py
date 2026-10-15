"""Read validated driver metadata for the workspace CLI."""

from __future__ import annotations

import json
from pathlib import Path

from cli_topsailai.session_driver import (
    _parse_metadata,
    _read_metadata,
    metadata_path,
)
from cli_topsailai.session_meta import _validate_depth
from cli_topsailai.session_driver_logs import bind_driver_row


def read_driver_meta(home, session_id):
    """Read and validate one active driver metadata snapshot."""
    path = metadata_path(home, session_id)
    try:
        data = _read_metadata(path)
    except FileNotFoundError as error:
        raise ValueError("metadata_missing") from error
    except OSError as error:
        raise ValueError("metadata_unreadable") from error
    if data is None:
        raise ValueError("metadata_missing")
    if not data.strip():
        raise ValueError("metadata_empty")
    text = data.decode("utf-8")
    _validate_depth(text)
    value = json.loads(text)
    _parse_metadata(data, session_id)
    if not isinstance(value, dict):
        raise ValueError("invalid_metadata_shape")
    return path, text, value


def _metadata_missing_message(path):
    """Explain active-record absence without exposing metadata contents."""
    return (f"metadata_missing: path={path}; the active metadata may not have been "
            "created or may have been cleaned up when the driver exited")


def print_driver_meta(home, rows, index, discover):
    """Bind and print the complete validated driver metadata JSON."""
    session = None
    try:
        session, pid = bind_driver_row(rows, index, home, discover)
        path, text, _ = read_driver_meta(home, session)
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, RecursionError, OSError) as error:
        message = str(error)
        if message == "metadata_missing" and session is not None:
            message = _metadata_missing_message(metadata_path(home, session))
        print(f"[ERROR] Driver metadata rejected: {message}")
        return False
    print(f"[INFO] Driver metadata: session={session}; session_pid={pid}; path={path}; "
          "session-level latest-run record; embedded pid is the driver PID")
    print(text, end="" if text.endswith("\n") else "\n")
    return True
