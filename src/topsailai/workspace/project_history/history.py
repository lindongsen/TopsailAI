"""
Project history logging.

Records each agent/LLM startup into a rotating JSONL file so the project
workspace used for each session can be traced later.

Author: AI
Created: 2026-07-03
"""

import json
import os
from datetime import datetime
from pathlib import Path

from topsailai.utils import env_tool
from topsailai.workspace.folder_constants import FILE_PROJECT_HISTORY


DEFAULT_MAX_SIZE = 1024 * 1024  # 1 MiB
DEFAULT_MAX_BACKUP = 1


def _get_max_size() -> int:
    """Return the configured rotation size in bytes.

    Reads ``TOPSAILAI_PROJECT_HISTORY_MAX_SIZE``. Defaults to ``1048576``
    (1 MiB). Values below or equal to ``0`` disable size-based rotation.
    """
    value = os.getenv("TOPSAILAI_PROJECT_HISTORY_MAX_SIZE")
    if not value:
        return DEFAULT_MAX_SIZE
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = DEFAULT_MAX_SIZE
    return max(size, 0)


def _get_max_backup() -> int:
    """Return the configured number of backup files to keep.

    Reads ``TOPSAILAI_PROJECT_HISTORY_MAX_BACKUP``. Defaults to ``1``.
    Values below ``0`` are treated as ``0`` (no backups kept).
    """
    value = os.getenv("TOPSAILAI_PROJECT_HISTORY_MAX_BACKUP")
    if value is None:
        return DEFAULT_MAX_BACKUP
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_MAX_BACKUP
    return max(count, 0)


def _rotate_if_needed(history_path: str, max_size: int, max_backup: int) -> None:
    """Rotate the history file when it exceeds ``max_size`` bytes."""
    if max_size <= 0:
        return
    if not os.path.exists(history_path):
        return

    try:
        current_size = os.path.getsize(history_path)
    except OSError:
        return

    if current_size <= max_size:
        return

    # Remove the oldest backup if it exists and we are about to shift into it.
    oldest_backup = f"{history_path}.{max_backup}"
    if max_backup == 0:
        # No backups kept: simply truncate the current file.
        try:
            with open(history_path, "w", encoding="utf-8"):
                pass
        except OSError:
            pass
        return

    if os.path.exists(oldest_backup):
        try:
            os.remove(oldest_backup)
        except OSError:
            pass

    # Shift existing backups upward: .N-1 -> .N, ..., .1 -> .2
    for i in range(max_backup - 1, 0, -1):
        src = f"{history_path}.{i}"
        dst = f"{history_path}.{i + 1}"
        if os.path.exists(src):
            try:
                os.replace(src, dst)
            except OSError:
                pass

    # Move current file to .1
    try:
        os.replace(history_path, f"{history_path}.1")
    except OSError:
        pass


def _now_iso8601() -> str:
    """Return the current local time as an ISO-8601 string."""
    return datetime.now().isoformat()


def record_project_history(session_id: str | None = None) -> bool:
    """Record a single startup entry into ``.project_history.jsonl``.

    Args:
        session_id: Optional session identifier. Defaults to the value resolved
            from environment variables via ``env_tool.get_session_id()``.

    Returns:
        bool: True if the entry was written, False otherwise.
    """
    project_workspace = os.getenv("TOPSAILAI_PROJECT_WORKSPACE") or os.getenv("TOPSAILAI_PWD") or ""
    pwd = os.getenv("TOPSAILAI_PWD") or ""

    if session_id is None:
        session_id = env_tool.get_session_id() or ""

    entry = {
        "ts": _now_iso8601(),
        "session_id": session_id,
        "project_workspace": project_workspace,
        "pwd": pwd,
    }

    history_path = FILE_PROJECT_HISTORY
    Path(history_path).parent.mkdir(parents=True, exist_ok=True)

    max_size = _get_max_size()
    max_backup = _get_max_backup()
    _rotate_if_needed(history_path, max_size, max_backup)

    try:
        with open(history_path, "a", encoding="utf-8") as fd:
            fd.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False
