"""Process-wide delivery statistics for the event channel.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Cumulative drop and delivery counters for the event channel
"""

from __future__ import annotations

import threading
from typing import Tuple


class EventChannelStats:
    """Cumulative, process-wide delivery counters for the event channel.

    The counters are process-wide rather than per-subscriber because a
    subscriber's own drop counter disappears together with the subscriber.
    That is exactly the moment an operator wants to know whether events were
    lost, so the cumulative number must outlive subscriber churn.

    Counting is cheap and lock-scoped to two integers, so it can run on the
    producer thread inside the fan-out loop without affecting event recording.
    """

    def __init__(self) -> None:
        """Create zeroed counters."""
        self._lock = threading.Lock()
        self._delivered_total = 0
        self._dropped_total = 0

    def record_delivery(self, dropped: bool) -> None:
        """Count one accepted event and, when applicable, one drop.

        Args:
            dropped: True when the subscriber had to discard its oldest queued
                event to accept this one.
        """
        with self._lock:
            self._delivered_total += 1
            if dropped:
                self._dropped_total += 1

    @property
    def delivered_total(self) -> int:
        """Return the number of events accepted by a subscriber queue."""
        with self._lock:
            return self._delivered_total

    @property
    def dropped_total(self) -> int:
        """Return the number of events discarded because a queue was full."""
        with self._lock:
            return self._dropped_total

    def snapshot(self) -> Tuple[int, int]:
        """Return the delivered and dropped totals as one consistent pair."""
        with self._lock:
            return self._delivered_total, self._dropped_total

    def reset(self) -> None:
        """Clear both counters, used by tests and explicit re-initialization."""
        with self._lock:
            self._delivered_total = 0
            self._dropped_total = 0


__all__ = ["EventChannelStats"]
