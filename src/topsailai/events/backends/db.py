"""
Database event storage backend (stub).

Future implementations can persist events to SQL/NoSQL databases and implement
:meth:`cleanup` to prune or archive old records.
"""

from __future__ import annotations

from typing import List

from topsailai.events.backends.base import EventBackend
from topsailai.events.models import Event


class DBEventBackend(EventBackend):
    """Placeholder database backend."""

    def write(self, events: List[Event]) -> bool:
        raise NotImplementedError("DBEventBackend.write() is not implemented")

    def close(self) -> None:
        pass

    def cleanup(self) -> None:
        """Prune or archive old database records."""
        pass
