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

# Drop notification runs on its own daemon thread instead of the producer
# thread. The observer mirrors cumulative totals into Agent Runtime Data, which
# takes a store lock; running it inline made the producer wait for that lock,
# which violates the "never a blocking point" invariant. A single pending flag
# coalesces bursts because the observer publishes cumulative totals, so the
# newest totals supersede any skipped notification.
_drop_pending = threading.Event()
_drop_notifier: Optional[threading.Thread] = None
_drop_notifier_lock = threading.Lock()


def get_subscription_registry() -> SubscriptionRegistry:
    """Return the process-wide subscription registry, creating it on first use."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = SubscriptionRegistry()
        return _registry


def get_subscription_registry_or_none() -> Optional[SubscriptionRegistry]:
    """Return the installed registry without creating one.

    Callers that must restore a previous registry need to distinguish "no
    registry installed" from "an empty registry", so this accessor never
    creates an instance as a side effect.
    """
    with _registry_lock:
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
    """Signal the drop notifier without ever waiting on the producer thread.

    The producer only sets an event flag, which is a lock-free operation, so a
    slow observer can never delay event recording. The observer itself runs on
    the notifier thread started by ``_ensure_drop_notifier``.
    """
    if _drop_observer is None:
        return
    _ensure_drop_notifier()
    _drop_pending.set()


def _ensure_drop_notifier() -> None:
    """Start the drop notifier thread once, tolerating a failure to start it."""
    global _drop_notifier
    if _drop_notifier is not None and _drop_notifier.is_alive():
        return
    if not _drop_notifier_lock.acquire(blocking=False):
        return
    try:
        if _drop_notifier is not None and _drop_notifier.is_alive():
            return
        thread = threading.Thread(
            target=_drop_notifier_loop, name="EventChannelDropNotifier", daemon=True
        )
        thread.start()
        _drop_notifier = thread
    except Exception:
        logger.warning("event channel drop notifier could not start", exc_info=True)
    finally:
        _drop_notifier_lock.release()


def _drop_notifier_loop() -> None:
    """Publish drop totals off the producer thread until the process exits."""
    while True:
        _drop_pending.wait()
        _drop_pending.clear()
        observer = _drop_observer
        if observer is None:
            continue
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
        Number of matching subscribers the event was offered to. A subscriber
        whose queue lock was busy is counted here even though the event was
        skipped for it, because the producer cannot distinguish the two cases
        without waiting on that lock.
    """
    registry = _registry
    if registry is None:
        return 0
    delivered = 0
    dropped_any = False
    try:
        for subscriber in registry.snapshot_nonblocking():
            if not subscriber.matches(event):
                continue
            dropped = subscriber.enqueue_nonblocking(event)
            _stats.record_delivery(dropped)
            if dropped:
                dropped_any = True
                logger.warning(
                    "event channel skipped an event for subscriber %s "
                    "(queue full at %s, or the queue lock was busy)",
                    subscriber.subscriber_id,
                    subscriber.queue_size,
                )
            delivered += 1
    except Exception:
        logger.exception("event channel fan-out failed")
    if dropped_any:
        _notify_drop()
    return delivered
