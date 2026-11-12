"""Fan-out of recorded events to active subscribers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Non-blocking event distribution for the event channel
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from topsailai.events.models import Event
from topsailai.events.subscribers.registry import SubscriptionRegistry

logger = logging.getLogger(__name__)

_registry: Optional[SubscriptionRegistry] = None
_registry_lock = threading.Lock()


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
    try:
        for subscriber in registry.snapshot():
            if not subscriber.matches(event):
                continue
            if subscriber.enqueue(event):
                logger.warning(
                    "event channel dropped oldest event for subscriber %s "
                    "(queue full at %s)",
                    subscriber.subscriber_id,
                    subscriber.queue_size,
                )
            delivered += 1
    except Exception:
        logger.exception("event channel fan-out failed")
    return delivered
