"""
TopsailAI Event Module

A lightweight, independent event recording subsystem for the TopsailAI agent.
Events are buffered in memory and periodically flushed to a configurable backend
(file, database, webhook, etc.).

Public API:
    record_event(event_type, payload=None, session_id=None, **kwargs)
    get_event_collector()
    reset_event_collector()
    Event
    EventCollector
    EventConfig
    EventBackend
    FileEventBackend
    DBEventBackend
    WebhookEventBackend
    record_tool_call_events
    record_approval_events
    record_llm_chat_events
"""

from topsailai.events.models import Event
from topsailai.events.config import EventConfig
from topsailai.events.collector import (
    EventCollector,
    get_event_collector,
    record_event,
    reset_event_collector,
)
from topsailai.events.backends.base import EventBackend
from topsailai.events.backends.file import FileEventBackend
from topsailai.events.backends.db import DBEventBackend
from topsailai.events.backends.webhook import WebhookEventBackend
from topsailai.events.decorators import (
    record_tool_call_events,
    record_approval_events,
    record_llm_chat_events,
)


__all__ = [
    "Event",
    "EventConfig",
    "EventCollector",
    "get_event_collector",
    "record_event",
    "reset_event_collector",
    "EventBackend",
    "FileEventBackend",
    "DBEventBackend",
    "WebhookEventBackend",
    "record_tool_call_events",
    "record_approval_events",
    "record_llm_chat_events",
]
