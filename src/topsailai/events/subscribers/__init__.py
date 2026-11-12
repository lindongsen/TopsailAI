"""Event-channel subscriber layer.

Pure in-memory state: subscriber filters, bounded queues, and fan-out. This
package performs no I/O and knows nothing about sockets, so it can be tested
without any transport.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Subscriber registry and fan-out for the event channel
"""

from topsailai.events.subscribers.subscriber import (
    DEFAULT_QUEUE_SIZE,
    Subscriber,
    matches_event_type,
)
from topsailai.events.subscribers.registry import (
    DEFAULT_MAX_SUBSCRIBERS,
    SubscriptionRegistry,
)
from topsailai.events.subscribers.fanout import (
    fan_out,
    get_subscription_registry,
    set_subscription_registry,
)

__all__ = [
    "DEFAULT_QUEUE_SIZE",
    "DEFAULT_MAX_SUBSCRIBERS",
    "Subscriber",
    "matches_event_type",
    "SubscriptionRegistry",
    "fan_out",
    "get_subscription_registry",
    "set_subscription_registry",
]
