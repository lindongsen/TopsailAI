"""
Abstract base class for event storage backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from topsailai.events.models import Event


class EventBackend(ABC):
    """
    Adapter interface for event storage.

    Concrete backends may write to files, databases, webhooks, or any other
    durable sink. Backends are also responsible for implementing their own
    recycling/cleanup logic via :meth:`cleanup`.
    """

    @abstractmethod
    def write(self, events: List[Event]) -> bool:
        """Persist a batch of events. Return True on success."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the backend."""
        raise NotImplementedError

    @abstractmethod
    def cleanup(self) -> None:
        """
        Perform backend-specific recycling/cleanup of old events.

        For file backends this may delete files older than a retention period
        or enforce a maximum file count. Database/webhook backends may
        implement equivalent pruning or archival logic.
        """
        raise NotImplementedError
