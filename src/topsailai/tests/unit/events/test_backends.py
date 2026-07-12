"""
Unit tests for topsailai.events.backends.
"""

import json
import os

import pytest

from topsailai.events.backends import (
    DBEventBackend,
    FileEventBackend,
    WebhookEventBackend,
)
from topsailai.events.models import Event


def test_file_backend_writes_jsonl(temp_events_file):
    backend = FileEventBackend(file_path=temp_events_file)
    events = [
        Event(event_type="a", payload={"i": 1}),
        Event(event_type="b", payload={"i": 2}),
    ]
    assert backend.write(events) is True
    backend.close()

    with open(temp_events_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "a"
    assert json.loads(lines[1])["payload"] == {"i": 2}


def test_file_backend_default_path_uses_session_and_pid(monkeypatch):
    monkeypatch.setenv("SESSION_ID", "abc-123")
    backend = FileEventBackend()
    path = backend.file_path
    assert path.endswith(".events")
    assert "abc-123" in path
    assert str(os.getpid()) in path


def test_file_backend_append_mode(temp_events_file):
    backend = FileEventBackend(file_path=temp_events_file)
    backend.write([Event(event_type="first", payload={})])
    backend.write([Event(event_type="second", payload={})])
    backend.close()

    with open(temp_events_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert [json.loads(line)["event_type"] for line in lines] == ["first", "second"]


def test_db_backend_stub():
    backend = DBEventBackend()
    with pytest.raises(NotImplementedError):
        backend.write([Event(event_type="x", payload={})])


def test_webhook_backend_stub():
    backend = WebhookEventBackend()
    with pytest.raises(NotImplementedError):
        backend.write([Event(event_type="x", payload={})])


def test_file_backend_serializes_non_json_payload(temp_events_file):
    backend = FileEventBackend(file_path=temp_events_file)
    events = [
        Event(event_type="with_set", payload={"items": {1, 2, 3}}),
        Event(event_type="with_bytes", payload={"raw": b"hello"}),
    ]
    assert backend.write(events) is True
    backend.close()

    with open(temp_events_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 2
    assert json.loads(lines[0])["payload"]["items"] == [1, 2, 3]
    assert json.loads(lines[1])["payload"]["raw"] == "hello"
