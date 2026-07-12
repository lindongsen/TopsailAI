"""Configuration for the TopsailAI events module.

All settings are read from environment variables via ``topsailai.utils.env_tool``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from topsailai.utils import env_tool


@dataclass
class EventConfig:
    """Runtime configuration for the event collector."""

    enabled: bool = True
    buffer_size: int = 1000
    flush_interval_ms: int = 100
    backend: str = "file"
    file_path: Optional[str] = None

    @classmethod
    def from_env(cls) -> "EventConfig":
        """Build a configuration from environment variables."""
        reader = env_tool.EnvReaderInstance
        enabled = reader.check_bool("TOPSAILAI_EVENTS_ENABLED", default=True)
        buffer_size = reader.get("TOPSAILAI_EVENTS_BUFFER_SIZE", default=1000, formatter=int)
        flush_interval_ms = reader.get(
            "TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS", default=100, formatter=int
        )
        backend = reader.get("TOPSAILAI_EVENTS_BACKEND", default="file")
        file_path = reader.get("TOPSAILAI_EVENTS_FILE_PATH", default="")
        return cls(
            enabled=enabled,
            buffer_size=buffer_size,
            flush_interval_ms=flush_interval_ms,
            backend=backend,
            file_path=file_path or None,
        )

    @property
    def flush_interval_seconds(self) -> float:
        """Return the flush interval as seconds."""
        return self.flush_interval_ms / 1000.0


def get_event_config() -> EventConfig:
    """Return a fresh configuration parsed from environment variables."""
    return EventConfig.from_env()
