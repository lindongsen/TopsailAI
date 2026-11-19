"""Read the last complete per-agent stats record without owning the writer.

Author: DawsonLin

``{session_id}.{pid}.session.stats.jsonl`` is an append-only log of cumulative
snapshots: every record restates the totals observed so far, so the last
complete line is the current state and the earlier lines are history. The
writer lives in the core package, so this module only reads what it produced
and never composes a record of its own.

The file is per-PID, so it is the only source that describes one agent rather
than the session it belongs to. A session process and each task agent write
their own file, which is why a worker row can publish its own counters without
borrowing the manager's.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

#: The writer caps one record at 4096 bytes. A window of two caps therefore
#: always contains at least one complete line, even when the last two records
#: are both at the cap, so the read never grows with the file size.
LINE_CAP = 4096
_READ_WINDOW = 2 * LINE_CAP

#: Rotation renames the active file to ``{stem}.{index}.jsonl`` and keeps at
#: most three backups. The newest record can live in a backup when the active
#: file was just rotated and has not received its first record yet.
_MAX_BACKUP_INDEX = 3


def _file_session_id(session_id: Any) -> Optional[str]:
    """Map a display session identity to its on-disk filename prefix.

    Temporary sessions have no real identifier: they are displayed as
    ``(temp)`` and stored under the reserved ``topsailai`` prefix. An
    identifier that cannot be composed into a path safely yields ``None``
    instead of raising, because one unusable row must not abort the document.

    The mapping is delegated to the runtime module so the display-to-file
    translation has one owner. That module is optional enrichment elsewhere in
    the CLI, so an unavailable module degrades to ``None`` here as well: a
    missing mapper must cost the record, never the whole document.
    """
    try:
        from cli_topsailai.workspace_runtime import _file_session_id as map_identity
    except ImportError:
        LOGGER.warning("Session stats unavailable: reason=identity_mapper_missing")
        return None

    return map_identity(session_id)


def _candidate_paths(task_dir: Path, session_id: Any, pid: int) -> List[Path]:
    """Return the active stats file followed by its rotation backups.

    The order is newest-first, because a backup only holds the newest record
    when the active file is still empty after a rotation.
    """
    prefix = _file_session_id(session_id)
    if prefix is None:
        return []
    active = task_dir / f"{prefix}.{pid}.session.stats.jsonl"
    stem = active.stem
    return [active] + [
        task_dir / f"{stem}.{index}.jsonl"
        for index in range(1, _MAX_BACKUP_INDEX + 1)
    ]


def _last_complete_line(path: Path) -> Optional[bytes]:
    """Return the last newline-terminated line using one bounded tail read.

    ``None`` means the file is absent, empty, or holds no complete line, so the
    caller may look in a rotation backup. A trailing fragment without its
    newline is discarded rather than parsed, because the writer may be
    mid-append and a partial record is not a record.
    """
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size <= 0:
                return None
            start_offset = max(0, size - _READ_WINDOW)
            stream.seek(start_offset)
            window = stream.read(_READ_WINDOW)
    except OSError:
        return None
    if not window:
        return None
    if not window.endswith(b"\n"):
        cut = window.rfind(b"\n")
        if cut < 0:
            return None
        window = window[:cut + 1]
    boundary = window.rfind(b"\n", 0, len(window) - 1)
    if boundary < 0:
        # A single newline in a window that does not start at offset 0 means the
        # line began before the window, so its beginning was never read.
        if start_offset > 0:
            return None
        line = window
    else:
        line = window[boundary + 1:]
    if not line or len(line) > LINE_CAP:
        return None
    return line


def _reject_constant(value: str) -> None:
    """Reject JSON's nonstandard NaN and Infinity constants, as the writer does."""
    raise ValueError(f"nonfinite JSON: {value}")


def _decode(line: bytes) -> Optional[Dict[str, Any]]:
    """Return the record object, or ``None`` when the line is not a valid record."""
    try:
        value = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        return None
    if type(value) is not dict or value.get("schema_version") != 1:
        return None
    return value


def _owns_record(record: Dict[str, Any], session_id: Any, pid: int) -> bool:
    """Report whether the record was written by the process the row names.

    The record carries its own ``session_id`` and ``pid``, so it is evidence
    about one exact process. A record that names another process is rejected
    instead of being published as this row's counters.
    """
    from cli_topsailai.constants import TEMP_SESSION_ID

    prefix = _file_session_id(session_id)
    if prefix is None:
        return False
    expected = ("", TEMP_SESSION_ID) if prefix == TEMP_SESSION_ID else (prefix,)
    return (record.get("session_id") in expected
            and type(record.get("pid")) is int
            and record["pid"] == pid)


def read_last_stats_record(
    task_dir: Path, session_id: Any, pid: int
) -> Optional[Dict[str, Any]]:
    """Return the newest complete stats record written by *pid*, or ``None``.

    Only the last complete line is read, because every record restates the
    cumulative totals. A present but unusable newest record yields ``None``
    rather than an older backup, because publishing stale totals would be worse
    than publishing nothing.

    Args:
        task_dir: Absolute task directory holding the stats files.
        session_id: Display session identity of the row.
        pid: The row's own process identifier.

    Returns:
        The validated record object, or ``None`` when no usable record exists.
    """
    if type(pid) is not int or pid <= 0:
        return None
    for path in _candidate_paths(Path(task_dir), session_id, pid):
        line = _last_complete_line(path)
        if line is None:
            continue
        record = _decode(line)
        if record is None:
            LOGGER.warning("Session stats unreadable: file=%s reason=invalid_record",
                           path.name)
            return None
        if not _owns_record(record, session_id, pid):
            LOGGER.warning("Session stats unreadable: file=%s reason=identity_mismatch",
                           path.name)
            return None
        return record
    return None


def row_last_stats(row: dict) -> Optional[Dict[str, Any]]:
    """Return the row's own last stats record, or ``None``.

    The task directory is derived from the row's own log path, so the read
    cannot disagree with the directory discovery used, and the same call serves
    every JSON producer. The read is gated by the same filename-ownership rule
    the metadata enrichment uses, so a row never borrows another process's
    record.

    Only JSON producers call this. The table renderer does not, so a listing
    that never publishes the record pays nothing for it.

    This is enrichment, so any failure degrades to ``None`` and is logged. A
    listing must never lose its document because one row's stats file could not
    be read, which is the same contract the runtime enrichment already follows.
    """
    try:
        from cli_topsailai.workspace_hostname import _row_owns_filename

        if not _row_owns_filename(row):
            return None
        path = row.get("path")
        if not isinstance(path, str) or not path:
            return None
        return read_last_stats_record(
            Path(path).parent, row.get("session_id"), row.get("pid")
        )
    except Exception as error:  # noqa: BLE001 - enrichment must never abort
        LOGGER.warning(
            "Session stats unavailable: reason=read_failed error=%s: %s",
            type(error).__name__, error,
        )
        return None
