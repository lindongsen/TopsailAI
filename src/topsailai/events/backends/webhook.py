"""
Webhook event storage backend (stub).

Future implementations can push events to an HTTP endpoint and implement
:meth:`cleanup` to retry or discard undelivered events.
"""

from __future__ import annotations

from typing import List

from topsailai.events.backends.base import EventBackend
from topsailai.events.models import Event


class WebhookEventBackend(EventBackend):
    """Placeholder webhook backend."""

    def write(self, events: List[Event]) -> bool:
        raise NotImplementedError("WebhookEventBackend.write() is not implemented")

    def close(self) -> None:
        pass

    def cleanup(self) -> None:
        """Retry or discard undelivered webhook events."""
        pass
