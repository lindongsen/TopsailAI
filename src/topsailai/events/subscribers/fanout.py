"""Fan-out of recorded events to active subscribers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Non-blocking event distribution for the event channel
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from topsailai.events.models import Event
from topsailai.events.subscribers.registry import SubscriptionRegistry
from topsailai.events.subscribers.stats import EventChannelStats

logger = logging.getLogger(__name__)

_registry: Optional[SubscriptionRegistry] = None
_registry_lock = threading.Lock()
_stats = EventChannelStats()
_drop_observer: Optional[Callable[[EventChannelStats], None]] = None


def get_subscription_registry() -> SubscriptionRegistry:
    """Return the process-wide subscription registry, creating it on first use."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = SubscriptionRegistry()
        return _registry


def set_subscription_registry(registry: Optional[SubscriptionRegistry]) -> None:
    """Replace the process-wide subscription registry.

    Args:
        registry: Registry to install, or None to drop the current one so the
            next accessor call creates a fresh instance.
    """
    global _registry
    with _registry_lock:
        _registry = registry


def get_event_channel_stats() -> EventChannelStats:
    """Return the process-wide delivery counters."""
    return _stats


def reset_event_channel_stats() -> None:
    """Clear the process-wide delivery counters."""
    _stats.reset()


def set_drop_observer(
    observer: Optional[Callable[[EventChannelStats], None]],
) -> None:
    """Register a callback invoked after a drop is counted.

    The subscriber layer must not import the Agent runtime, so the Runtime Data
    mirror is attached from outside through this seam instead of a direct
    dependency. The callback runs on the producer thread and must not raise.

    Args:
        observer: Callback receiving the process-wide counters, or None to
            detach the current one.
    """
    global _drop_observer
    with _registry_lock:
        _drop_observer = observer


def _notify_drop() -> None:
    """Notify the registered drop observer without affecting the producer."""
    observer = _drop_observer
    if observer is None:
        return
    try:
        observer(_stats)
    except Exception:
        logger.exception("event channel drop observer failed")


def fan_out(event: Event) -> int:
    """Enqueue an event into every matching subscriber without blocking.

    This runs on the producer thread, so it must stay cheap and must never
    raise: a subscriber problem is never allowed to affect event recording or
    the caller that produced the event.

    Args:
        event: Event to distribute.

    Returns:
        Number of subscribers that accepted the event.
    """
    registry = _registry
    if registry is None:
        return 0
    delivered = 0
    dropped_any = False
    try:
        for subscriber in registry.snapshot():
            if not subscriber.matches(event):
                continue
            dropped = subscriber.enqueue(event)
            _stats.record_delivery(dropped)
            if dropped:
                dropped_any = True
                logger.warning(
                    "event channel dropped oldest event for subscriber %s "
                    "(queue full at %s)",
                    subscriber.subscriber_id,
                    subscriber.queue_size,
                )
            delivered += 1
    except Exception:
        logger.exception("event channel fan-out failed")
    if dropped_any:
        _notify_drop()
    return delivered
