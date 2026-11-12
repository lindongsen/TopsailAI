"""Mirror event-channel delivery totals into Agent Runtime Data.

The event channel is process-wide while Runtime Data is Agent-scoped, so the
cumulative totals are published into the Runtime Data Store of the Agent that
happens to be executing when a drop is counted. Publishing the cumulative total
rather than an increment makes the mirror self-healing: a drop counted on a
thread without a bound Agent is not lost, because the next publication carries
the complete total.

Publication is triggered only by a drop, never by an ordinary delivery. A drop
is already an abnormal, logged condition, so the healthy path keeps zero Runtime
Data work and the producer thread stays as cheap as before.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Expose event-channel drop counts through Runtime Data
"""

from __future__ import annotations

import logging
import threading
import weakref
from typing import Optional

from topsailai.ai_base.runtime_data import RuntimeDataLease, RuntimeDataStore
from topsailai.events.subscribers.fanout import set_drop_observer
from topsailai.events.subscribers.stats import EventChannelStats
from topsailai.utils.thread_local_tool import get_agent_object

logger = logging.getLogger(__name__)

RUNTIME_STATE_KEY = "event.channel.dropped"
OWNER_ID = "event_channel"

_leases: "weakref.WeakKeyDictionary[RuntimeDataStore, RuntimeDataLease]" = (
    weakref.WeakKeyDictionary()
)
_published_dropped: "weakref.WeakKeyDictionary[RuntimeDataStore, int]" = (
    weakref.WeakKeyDictionary()
)
_lock = threading.Lock()


def _state_value(delivered_total: int, dropped_total: int) -> dict:
    """Build the bounded public value for the delivery counters."""
    return {
        "phase": "dropping" if dropped_total else "delivering",
        "dropped_total": dropped_total,
        "delivered_total": delivered_total,
    }


def _resolve_store() -> Optional[RuntimeDataStore]:
    """Return the current Agent's Runtime Data Store when one is available."""
    agent = get_agent_object()
    if agent is None:
        return None
    runtime = getattr(agent, "runtime", None)
    store = getattr(runtime, "runtime_data", None) if runtime is not None else None
    return store if isinstance(store, RuntimeDataStore) else None


def publish_event_channel_stats(stats: EventChannelStats) -> bool:
    """Publish the cumulative delivery totals into the current Agent's store.

    Runs on the producer thread, so it must stay cheap and must never raise: a
    publication problem is never allowed to affect event recording.

    Args:
        stats: Process-wide delivery counters to mirror.

    Returns:
        True when the current Agent's state was created or updated.
    """
    store = _resolve_store()
    if store is None:
        return False

    delivered_total, dropped_total = stats.snapshot()
    try:
        with _lock:
            if _published_dropped.get(store) == dropped_total:
                return False
            value = _state_value(delivered_total, dropped_total)
            lease = _leases.get(store)
            if lease is not None and store.update(lease, value):
                _published_dropped[store] = dropped_total
                return True
            lease = store.activate(
                RUNTIME_STATE_KEY,
                owner_id=OWNER_ID,
                value=value,
                public=True,
            )
            _leases[store] = lease
            _published_dropped[store] = dropped_total
            return True
    except Exception as error:
        logger.warning(
            "event channel Runtime Data publication failed category=%s",
            type(error).__name__,
            exc_info=False,
        )
        return False


def clear_event_channel_runtime_state() -> None:
    """Settle and drop cached leases so a fresh Agent starts clean.

    Clearing the cache alone would leave the state active in the store, and the
    next publication would fail forever because the key is still owned by a
    lease nobody holds any more. Every cached lease is therefore settled first.
    """
    with _lock:
        leases = list(_leases.items())
        _leases.clear()
        _published_dropped.clear()
    for store, lease in leases:
        try:
            store.deactivate(lease, outcome="cleared")
        except Exception as error:
            logger.warning(
                "event channel Runtime Data settlement failed category=%s",
                type(error).__name__,
                exc_info=False,
            )


def install_event_channel_runtime_observer() -> None:
    """Attach the Runtime Data mirror to the fan-out drop notification.

    The subscriber layer must not import the Agent runtime, so the mirror is
    attached from this side through the observer seam. Installing twice is
    harmless because the seam stores a single callback.
    """
    set_drop_observer(publish_event_channel_stats)


def uninstall_event_channel_runtime_observer() -> None:
    """Detach the Runtime Data mirror from the fan-out drop notification."""
    set_drop_observer(None)


__all__ = [
    "OWNER_ID",
    "RUNTIME_STATE_KEY",
    "clear_event_channel_runtime_state",
    "install_event_channel_runtime_observer",
    "publish_event_channel_stats",
    "uninstall_event_channel_runtime_observer",
]
