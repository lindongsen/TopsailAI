"""
Abstract base class for event storage backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from topsailai.events.models import Event


class EventBackend(ABC):
    """
    Abstract base class for event storage adapters.

    Implementations must be thread-safe for concurrent writes.
    """

    @abstractmethod
    def write(self, events: List[Event]) -> bool:
        """
        Persist a batch of events.

        Args:
            events: Non-empty list of events to persist.

        Returns:
            True when all events were persisted successfully. Returning False
            signals the collector to keep the events in the buffer for retry.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the backend."""
        raise NotImplementedError
