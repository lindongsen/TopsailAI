"""
Unit tests for topsailai.events public API.
"""

import json
import os

from topsailai import events


def test_record_event_and_flush(monkeypatch, tmp_path):
    path = str(tmp_path / "api.events")
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_PATH", path)
    events.reset_event_collector()

    events.record_event("custom.event", {"key": "value"}, session_id="s1")
    events.reset_event_collector()

    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event_type"] == "custom.event"
    assert data["payload"] == {"key": "value"}
    assert data["session_id"] == "s1"


def test_get_event_collector_returns_same_instance(monkeypatch, tmp_path):
    path = str(tmp_path / "singleton.events")
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_PATH", path)
    events.reset_event_collector()

    c1 = events.get_event_collector()
    c2 = events.get_event_collector()
    assert c1 is c2
    events.reset_event_collector()


def test_record_event_disabled_is_no_op(monkeypatch, tmp_path):
    """When disabled, record_event must not create the events directory or start a thread."""
    monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", "0")
    events.reset_event_collector()

    events.record_event("custom.event", {"key": "value"})
    collector = events.get_event_collector()

    assert collector.enabled is False
    assert isinstance(collector.backend, events.FileEventBackend) is False
    assert collector._flusher is not None
    events.reset_event_collector()


def test_record_event_disabled_does_not_create_directory(monkeypatch, tmp_path):
    """Disabled mode must not create TOPSAILAI_HOME/workspace/task directory."""
    fake_home = str(tmp_path / "no_such_home")
    monkeypatch.setenv("TOPSAILAI_HOME", fake_home)
    monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", "0")
    events.reset_event_collector()

    events.record_event("x", {})

    assert not os.path.exists(fake_home)
    events.reset_event_collector()
