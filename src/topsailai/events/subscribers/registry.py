"""Registry of active event-channel subscribers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Subscriber registration and lookup for the event channel
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional, Sequence

from topsailai.events.subscribers.subscriber import DEFAULT_QUEUE_SIZE, Subscriber

logger = logging.getLogger(__name__)

DEFAULT_MAX_SUBSCRIBERS = 8


class SubscriptionRegistry:
    """Thread-safe registry mapping subscriber ids to subscribers.

    Identity is client-generated, so a reconnect reuses the same id. Registering
    an id that is already present replaces the previous entry instead of adding a
    second one; otherwise a stale entry would keep receiving events until its
    heartbeat timeout expired and the subscriber would see duplicates.

    Attributes:
        max_subscribers: Maximum number of concurrent subscribers.
        queue_size: Queue capacity assigned to each new subscriber.
    """

    def __init__(
        self,
        max_subscribers: int = DEFAULT_MAX_SUBSCRIBERS,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ):
        if max_subscribers < 1:
            max_subscribers = 1
        if queue_size < 1:
            queue_size = 1
        self.max_subscribers = max_subscribers
        self.queue_size = queue_size
        self._subscribers: Dict[str, Subscriber] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        """Return the number of registered subscribers."""
        with self._lock:
            return len(self._subscribers)

    def register(
        self,
        subscriber_id: str,
        event_types: Optional[Sequence[str]] = None,
        queue_size: Optional[int] = None,
    ) -> Optional[Subscriber]:
        """Register a subscriber, replacing any existing entry with the same id.

        Args:
            subscriber_id: Client-generated identity.
            event_types: Filter patterns; empty means all events.
            queue_size: Optional per-subscriber queue capacity override. When
                omitted, the registry default is used.

        Returns:
            The new subscriber, or None when the registry is full and the id is
            not already registered.
        """
        with self._lock:
            existing = self._subscribers.get(subscriber_id)
            if existing is None and len(self._subscribers) >= self.max_subscribers:
                logger.warning(
                    "event channel rejected subscriber %s: limit %s reached",
                    subscriber_id,
                    self.max_subscribers,
                )
                return None
            if existing is not None:
                logger.info(
                    "event channel replacing subscriber %s on reconnect", subscriber_id
                )
            subscriber = Subscriber(
                subscriber_id=subscriber_id,
                event_types=event_types,
                queue_size=queue_size if queue_size is not None else self.queue_size,
            )
            self._subscribers[subscriber_id] = subscriber
            return subscriber

    def unregister(self, subscriber_id: str) -> Optional[Subscriber]:
        """Remove and return a subscriber, or None when it is not registered."""
        with self._lock:
            return self._subscribers.pop(subscriber_id, None)

    def get(self, subscriber_id: str) -> Optional[Subscriber]:
        """Return a registered subscriber, or None when it is not registered."""
        with self._lock:
            return self._subscribers.get(subscriber_id)

    def snapshot(self) -> List[Subscriber]:
        """Return the currently registered subscribers."""
        with self._lock:
            return list(self._subscribers.values())

    def snapshot_nonblocking(self) -> List[Subscriber]:
        """Return the registered subscribers without ever waiting for the lock.

        The fan-out path runs on the producer thread, which must never become a
        blocking point. A registry mutation holds this lock only for an O(1)
        dictionary operation, so contention is rare; when it does happen the
        producer skips this event instead of waiting, because losing one event
        for one subscriber is strictly better than delaying the caller that
        produced it.

        Returns:
            The registered subscribers, or an empty list when the lock is busy.
        """
        if not self._lock.acquire(blocking=False):
            return []
        try:
            return list(self._subscribers.values())
        finally:
            self._lock.release()

    def stale_subscribers(self, timeout_seconds: float) -> List[Subscriber]:
        """Return subscribers whose last liveness signal exceeded the timeout."""
        if timeout_seconds <= 0:
            return []
        return [
            subscriber
            for subscriber in self.snapshot()
            if subscriber.is_stale(timeout_seconds)
        ]

    def clear(self) -> None:
        """Remove every subscriber."""
        with self._lock:
            self._subscribers.clear()
