"""
Event backend adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from topsailai.events.backends.base import EventBackend
from topsailai.events.backends.file import FileEventBackend, get_default_events_file_path
from topsailai.events.backends.db import DBEventBackend
from topsailai.events.backends.webhook import WebhookEventBackend

if TYPE_CHECKING:
    from topsailai.events.config import EventConfig

__all__ = [
    "EventBackend",
    "FileEventBackend",
    "get_default_events_file_path",
    "DBEventBackend",
    "WebhookEventBackend",
    "create_backend",
]


def create_backend(config: "EventConfig") -> Optional[EventBackend]:
    """Create an event backend from the given configuration."""
    backend = (config.backend or "file").lower()
    if backend == "db":
        return DBEventBackend()
    if backend == "webhook":
        return WebhookEventBackend()
    # Unknown or "file" backend falls back to file storage.
    return FileEventBackend(
        file_path=config.file_path,
        retention_days=config.retention_days,
        max_count=config.max_count,
        delete_on_exit=config.delete_on_exit,
        fsync=config.fsync,
    )
