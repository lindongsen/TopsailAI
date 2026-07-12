"""
Database event storage backend (stub).

Reserved for future implementations that persist events to a SQL/NoSQL
database. The interface matches EventBackend.
"""

from __future__ import annotations

from typing import List

from topsailai.events.backends.base import EventBackend
from topsailai.events.models import Event


class DBEventBackend(EventBackend):
    """
    Stub database backend for event persistence.

    Raises NotImplementedError on write to signal that concrete configuration
    (connection string, schema, etc.) is required before use.
    """

    def __init__(self, connection_string: str | None = None):
        self._connection_string = connection_string or ""

    def write(self, events: List[Event]) -> bool:
        raise NotImplementedError(
            "DBEventBackend is not implemented yet; configure a connection string and schema."
        )

    def close(self) -> None:
        pass
