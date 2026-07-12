"""
Webhook event storage backend (stub).

Reserved for future implementations that push events to an external HTTP
endpoint. The interface matches EventBackend.
"""

from __future__ import annotations

from typing import List

from topsailai.events.backends.base import EventBackend
from topsailai.events.models import Event


class WebhookEventBackend(EventBackend):
    """
    Stub webhook backend for event persistence.

    Raises NotImplementedError on write to signal that concrete configuration
    (endpoint URL, authentication, retry policy, etc.) is required before use.
    """

    def __init__(self, endpoint_url: str | None = None):
        self._endpoint_url = endpoint_url or ""

    def write(self, events: List[Event]) -> bool:
        raise NotImplementedError(
            "WebhookEventBackend is not implemented yet; configure an endpoint URL and retry policy."
        )

    def close(self) -> None:
        pass
