"""
Unit tests for topsailai.events.models.
"""

import json
from datetime import datetime, timezone

from topsailai.events.models import Event


def test_event_defaults():
    event = Event(event_type="x", payload={"a": 1})
    assert event.event_type == "x"
    assert event.payload == {"a": 1}
    assert event.session_id is None
    assert event.trace_id is None
    assert event.source is None
    assert isinstance(event.timestamp, datetime)


def test_event_to_dict():
    ts = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    event = Event(
        event_type="tool_call.start",
        timestamp=ts,
        session_id="s1",
        trace_id="t1",
        source="tool.py",
        payload={"tool": "file_tool"},
    )
    data = event.to_dict()
    assert data["event_type"] == "tool_call.start"
    assert data["timestamp"] == "2026-07-11T12:00:00+00:00"
    assert data["session_id"] == "s1"
    assert data["trace_id"] == "t1"
    assert data["source"] == "tool.py"
    assert data["payload"] == {"tool": "file_tool"}


def test_event_to_json():
    event = Event(event_type="x", payload={})
    raw = event.to_json()
    parsed = json.loads(raw)
    assert parsed["event_type"] == "x"
