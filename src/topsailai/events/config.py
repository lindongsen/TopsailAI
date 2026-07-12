"""
Event module configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from topsailai.utils import env_tool


@dataclass
class EventConfig:
    """
    Configuration for the event subsystem.

    Attributes:
        enabled: Master switch for event recording.
        buffer_size: Maximum number of events kept in memory before dropping oldest.
        flush_interval_ms: Interval between background flushes to the backend.
        backend: Backend adapter name (``file``, ``db``, ``webhook``).
        file_path: Optional override for the file backend output path.
        retention_days: Number of days to retain events files (file backend).
        max_count: Maximum number of events files to keep (0 = unlimited).
    """

    enabled: bool = True
    buffer_size: int = 1000
    flush_interval_ms: int = 100
    backend: str = "file"
    file_path: Optional[str] = None
    retention_days: int = 7
    max_count: int = 0

    @classmethod
    def from_env(cls) -> "EventConfig":
        reader = env_tool.EnvReaderInstance

        enabled = reader.check_bool("TOPSAILAI_EVENTS_ENABLED", default=True)
        buffer_size = reader.get("TOPSAILAI_EVENTS_BUFFER_SIZE", default=1000, formatter=int)
        flush_interval_ms = reader.get(
            "TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS", default=100, formatter=int
        )
        backend = reader.get("TOPSAILAI_EVENTS_BACKEND", default="file")
        file_path = reader.get("TOPSAILAI_EVENTS_FILE_PATH", default=None)
        retention_days = reader.get(
            "TOPSAILAI_EVENTS_FILE_RETENTION_DAYS", default=7, formatter=int
        )
        max_count = reader.get("TOPSAILAI_EVENTS_FILE_MAX_COUNT", default=0, formatter=int)

        return cls(
            enabled=enabled,
            buffer_size=buffer_size if buffer_size is not None and buffer_size > 0 else 1000,
            flush_interval_ms=flush_interval_ms
            if flush_interval_ms is not None and flush_interval_ms > 0
            else 100,
            backend=backend if backend else "file",
            file_path=file_path if file_path else None,
            retention_days=retention_days if retention_days is not None and retention_days >= 0 else 7,
            max_count=max_count if max_count is not None and max_count >= 0 else 0,
        )


def get_event_config() -> EventConfig:
    """Return a fresh configuration parsed from the current environment."""
    return EventConfig.from_env()
