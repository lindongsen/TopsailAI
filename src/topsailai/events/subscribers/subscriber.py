"""A single event-channel subscriber with a bounded queue.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: In-memory subscriber state for the event channel
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import List, Optional, Sequence

from topsailai.events.models import Event

DEFAULT_QUEUE_SIZE = 1000


def matches_event_type(event_type: str, patterns: Sequence[str]) -> bool:
    """Return True when an event type satisfies at least one filter pattern.

    Supported pattern forms:
        - ``*`` matches every event type.
        - An exact string matches that event type only.
        - A trailing ``.*`` matches every event type sharing the prefix, so
          ``tool_call.*`` matches ``tool_call.start`` and ``tool_call.end``.

    Args:
        event_type: Concrete event type such as ``tool_call.start``.
        patterns: Filter patterns; an empty sequence matches everything.

    Returns:
        True when the event type is accepted by the filter.
    """
    if not patterns:
        return True
    for pattern in patterns:
        if pattern == "*" or pattern == event_type:
            return True
        if pattern.endswith(".*") and event_type.startswith(pattern[:-1]):
            return True
    return False


class Subscriber:
    """One external subscriber: a filter, a bounded queue, and liveness state.

    The queue is bounded and drops the oldest event on overflow, matching the
    existing ``EventBuffer`` policy. Enqueueing never blocks, so a slow or dead
    subscriber can never delay the producer or another subscriber.

    Attributes:
        subscriber_id: Client-generated identity, stable across reconnects.
        event_types: Filter patterns; empty means all events.
        queue_size: Maximum number of queued events.
    """

    def __init__(
        self,
        subscriber_id: str,
        event_types: Optional[Sequence[str]] = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ):
        if not subscriber_id:
            raise ValueError("subscriber_id must be non-empty")
        if queue_size < 1:
            queue_size = 1
        self.subscriber_id = subscriber_id
        self.event_types: tuple[str, ...] = tuple(event_types or ())
        self.queue_size = queue_size
        self._queue: deque[Event] = deque(maxlen=queue_size)
        self._lock = threading.Lock()
        self._dropped = 0
        self._last_seen = time.monotonic()

    @property
    def dropped(self) -> int:
        """Return the number of events dropped because the queue was full."""
        with self._lock:
            return self._dropped

    @property
    def size(self) -> int:
        """Return the number of events currently queued."""
        with self._lock:
            return len(self._queue)

    def __len__(self) -> int:
        """Return the number of events currently queued."""
        with self._lock:
            return len(self._queue)

    def matches(self, event: Event) -> bool:
        """Return True when the event satisfies this subscriber's filter."""
        return matches_event_type(event.event_type, self.event_types)

    def enqueue(self, event: Event) -> bool:
        """Append an event to the queue without blocking.

        Args:
            event: Event to enqueue.

        Returns:
            True when an older event had to be dropped to make room.
        """
        with self._lock:
            dropped = len(self._queue) >= self.queue_size
            if dropped:
                self._dropped += 1
            self._queue.append(event)
            return dropped

    def enqueue_nonblocking(self, event: Event) -> bool:
        """Append an event without ever waiting for the queue lock.

        The fan-out path runs on the producer thread, which must never become a
        blocking point. The writer thread holds this lock only while draining a
        bounded batch, so contention is short; when it does happen the producer
        drops this event for this subscriber instead of waiting.

        The per-subscriber ``dropped`` counter is not incremented on a contended
        skip, because incrementing it would require the very lock that is busy.
        The process-wide counter still records the loss, so an operator sees the
        drop even though this subscriber's own counter undercounts.

        Args:
            event: Event to enqueue.

        Returns:
            True when the event was not queued, either because the queue was
            full or because the lock was busy.
        """
        if not self._lock.acquire(blocking=False):
            return True
        try:
            dropped = len(self._queue) >= self.queue_size
            if dropped:
                self._dropped += 1
            self._queue.append(event)
            return dropped
        finally:
            self._lock.release()

    def drain(self, count: Optional[int] = None) -> List[Event]:
        """Remove and return queued events in insertion order.

        Args:
            count: Maximum number of events to remove; None drains everything.

        Returns:
            The removed events, oldest first.
        """
        with self._lock:
            if count is None or count >= len(self._queue):
                events = list(self._queue)
                self._queue.clear()
                return events
            return [self._queue.popleft() for _ in range(count)]

    def snapshot(self) -> List[Event]:
        """Return a copy of the queued events without removing them."""
        with self._lock:
            return list(self._queue)

    def touch(self) -> None:
        """Record that the subscriber was observed alive just now."""
        with self._lock:
            self._last_seen = time.monotonic()

    def idle_seconds(self) -> float:
        """Return seconds elapsed since the last observed liveness signal."""
        with self._lock:
            return time.monotonic() - self._last_seen

    def is_stale(self, timeout_seconds: float) -> bool:
        """Return True when no liveness signal arrived within the timeout."""
        if timeout_seconds <= 0:
            return False
        return self.idle_seconds() > timeout_seconds

    def clear(self) -> None:
        """Discard all queued events without changing the drop counter."""
        with self._lock:
            self._queue.clear()
