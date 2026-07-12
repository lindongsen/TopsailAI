"""
File-based event storage backend.

Writes newline-delimited JSON (JSONL) to a session-scoped file under
TOPSAILAI_HOME/workspace/task. The filename follows the session stdout
convention but uses the ``.events`` extension.
"""

from __future__ import annotations

import os
from typing import List

from topsailai.events.backends.base import EventBackend
from topsailai.events.models import Event
from topsailai.utils.env_tool import get_session_id
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK


class FileEventBackend(EventBackend):
    """
    Default file backend for event persistence.

    Each event is serialized as one JSON line. The file is opened in append
    mode and closed after each write to keep the implementation simple and
    robust against process crashes.
    """

    def __init__(self, file_path: str | None = None):
        self._file_path = file_path or self._resolve_default_path()
        self._ensure_directory()

    @property
    def file_path(self) -> str:
        return self._file_path

    @staticmethod
    def _resolve_default_path() -> str:
        """Build the default event file path following session stdout convention."""
        pid = os.getpid()
        session_id = get_session_id()
        if session_id:
            filename = f"{session_id}.{pid}.session.events"
        else:
            filename = f"topsailai.{pid}.session.events"
        return os.path.join(FOLDER_WORKSPACE_TASK, filename)

    def _ensure_directory(self) -> None:
        directory = os.path.dirname(self._file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def write(self, events: List[Event]) -> bool:
        if not events:
            return True
        try:
            self._ensure_directory()
            with open(self._file_path, "a", encoding="utf-8") as f:
                for event in events:
                    f.write(event.to_json_line())
                    f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception:
            # Fail open: keep events in the buffer for retry.
            return False

    def close(self) -> None:
        # No persistent resources to release for the file backend.
        pass
