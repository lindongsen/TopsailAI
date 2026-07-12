"""
Thread-safe bounded event buffer with drop-oldest overflow handling.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Iterable, List, Optional

from topsailai.events.models import Event


class EventBuffer:
    """
    In-memory bounded buffer for events.

    When the buffer reaches its capacity, the oldest event is dropped to make
    room for the newest one. All operations are thread-safe.
    """

    def __init__(self, max_size: int = 1000):
        if max_size < 1:
            max_size = 1
        self._max_size = max_size
        self._buffer: deque[Event] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def append(self, event: Event) -> None:
        """Append an event, dropping the oldest event if the buffer is full."""
        with self._lock:
            self._buffer.append(event)

    def extend(self, events: Iterable[Event]) -> None:
        """Append multiple events, dropping oldest events as needed."""
        with self._lock:
            for event in events:
                self._buffer.append(event)

    def prepend(self, events: Iterable[Event]) -> None:
        """Insert events at the front of the buffer, dropping oldest if needed."""
        with self._lock:
            new_events = list(events)
            remaining = max(0, self._max_size - len(new_events))
            keep = new_events + list(self._buffer)[-remaining:]
            self._buffer.clear()
            self._buffer.extend(keep)

    def drain(self, count: Optional[int] = None) -> List[Event]:
        """
        Remove and return events from the buffer.

        Args:
            count: Maximum number of events to drain. If None, drain all.

        Returns:
            List of drained events in insertion order.
        """
        with self._lock:
            if count is None or count >= len(self._buffer):
                events = list(self._buffer)
                self._buffer.clear()
                return events
            events = [self._buffer.popleft() for _ in range(count)]
            return events

    def snapshot(self) -> List[Event]:
        """Return a copy of the current buffer contents without draining."""
        with self._lock:
            return list(self._buffer)

    def peek(self) -> List[Event]:
        """Return a snapshot of the buffer without removing events."""
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Remove all events from the buffer."""
        with self._lock:
            self._buffer.clear()
