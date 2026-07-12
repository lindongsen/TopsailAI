"""
File-based event storage backend.

Events are appended as JSON Lines to a file under ``TOPSAILAI_HOME/workspace/task``.
The filename follows the session stdout convention with a ``.events`` extension:
``{session_id}.{pid}.session.events`` when a session id is available, otherwise
``topsailai.{pid}.session.events``.
"""

from __future__ import annotations

import atexit
import glob
import json
import os
import time
from typing import List

from topsailai.events.backends.base import EventBackend
from topsailai.events.models import Event
from topsailai.utils import env_tool
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK


class FileEventBackend(EventBackend):
    """
    Append-only JSONL backend for events.

    The backend optionally registers an ``atexit`` handler to delete the current
    process's events file when the interpreter shuts down. Deletion is disabled
    by default and is controlled by ``TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT``.
    It also implements ``cleanup()`` to remove old events files based on
    retention days and an optional maximum file count.
    """

    def __init__(
        self,
        file_path: str | None = None,
        retention_days: int | None = None,
        max_count: int | None = None,
        register_atexit: bool = True,
        delete_on_exit: bool | None = None,
        fsync: bool | None = None,
    ):
        self._file_path = file_path or self._resolve_default_path()
        self._retention_days = (
            retention_days if retention_days is not None else self._resolve_retention_days()
        )
        self._max_count = max_count if max_count is not None else self._resolve_max_count()
        self._delete_on_exit = (
            delete_on_exit if delete_on_exit is not None else self._resolve_delete_on_exit()
        )
        self._fsync = fsync if fsync is not None else self._resolve_fsync()
        self._ensure_directory()
        if register_atexit and self._delete_on_exit:
            atexit.register(self._atexit_cleanup)

    @property
    def file_path(self) -> str:
        """Return the resolved output file path."""
        return self._file_path


    @staticmethod
    def _resolve_default_path() -> str:
        session_id = env_tool.get_session_id()
        pid = os.getpid()
        if session_id:
            filename = f"{session_id}.{pid}.session.events"
        else:
            filename = f"topsailai.{pid}.session.events"
        return os.path.join(FOLDER_WORKSPACE_TASK, filename)

    @staticmethod
    def _resolve_retention_days() -> int:
        value = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_EVENTS_FILE_RETENTION_DAYS", default=7, formatter=int
        )
        return value if value is not None and value >= 0 else 7

    @staticmethod
    def _resolve_max_count() -> int:
        value = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_EVENTS_FILE_MAX_COUNT", default=0, formatter=int
        )
        return value if value is not None and value >= 0 else 0

    @staticmethod
    def _resolve_delete_on_exit() -> bool:
        return env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT", default=False
        )

    @staticmethod
    def _resolve_fsync() -> bool:
        return env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_EVENTS_FILE_FSYNC", default=True
        )

    def _ensure_directory(self) -> None:
        directory = os.path.dirname(self._file_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
            except Exception:
                pass

    def _atexit_cleanup(self) -> None:
        """Delete the current process's events file on interpreter shutdown."""
        # Capture module references defensively because globals may be None during shutdown.
        _os = os
        if _os is None:
            return
        path = self._file_path
        if not path:
            return
        basename = _os.path.basename(path)
        if str(_os.getpid()) not in basename:
            return
        try:
            if _os.path.exists(path):
                _os.remove(path)
        except Exception:
            pass

    def write(self, events: List[Event]) -> bool:
        if not events:
            return True
        try:
            lines = [event.to_json_line() for event in events]
            with open(self._file_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
                handle.flush()
                if self._fsync:
                    try:
                        os.fsync(handle.fileno())
                    except Exception:
                        pass
            return True
        except Exception:
            return False

    def close(self) -> None:
        pass

    def cleanup(self) -> None:
        """
        Remove old events files based on retention days and max count.

        Only files matching ``*.events`` in the configured directory are
        considered, and only those whose basename contains ``.session.events``.
        """
        _os = os
        _glob = glob
        _time = time
        if _os is None or _glob is None or _time is None:
            return

        directory = _os.path.dirname(self._file_path) or FOLDER_WORKSPACE_TASK
        pattern = _os.path.join(directory, "*.events")
        try:
            paths = _glob.glob(pattern)
        except Exception:
            return

        now = _time.time()
        retention_seconds = self._retention_days * 86400

        event_files = []
        for path in paths:
            try:
                if not _os.path.isfile(path):
                    continue
                basename = _os.path.basename(path)
                if ".session.events" not in basename:
                    continue
                event_files.append((path, _os.path.getmtime(path)))
            except Exception:
                continue

        # Delete files older than the retention period.
        surviving = []
        for path, mtime in event_files:
            if retention_seconds > 0 and now - mtime > retention_seconds:
                try:
                    _os.remove(path)
                except Exception:
                    pass
            else:
                surviving.append((path, mtime))

        # Enforce maximum file count by removing oldest files first.
        if self._max_count > 0 and len(surviving) > self._max_count:
            surviving.sort(key=lambda item: item[1])
            for path, _ in surviving[: len(surviving) - self._max_count]:
                try:
                    _os.remove(path)
                except Exception:
                    pass
