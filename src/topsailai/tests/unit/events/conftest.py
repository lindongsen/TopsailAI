"""
Fixtures for events unit tests.
"""

import uuid

import pytest

from topsailai.events.buffer import EventBuffer
from topsailai.events.collector import EventCollector
from topsailai.events.config import EventConfig
from topsailai.events.models import Event


@pytest.fixture
def temp_events_file(tmp_path):
    """Provide a unique temporary file path for a test's events file."""
    return str(tmp_path / f"test-{uuid.uuid4().hex}.events")


@pytest.fixture
def file_config(temp_events_file):
    """Provide an EventConfig that writes to a temp file."""
    return EventConfig(
        enabled=True,
        buffer_size=100,
        flush_interval_ms=50,
        backend="file",
        file_path=temp_events_file,
    )


@pytest.fixture
def disabled_config():
    return EventConfig(enabled=False)


class MockBackend:
    """In-memory backend for testing collector behavior."""

    def __init__(self):
        self.events = []
        self.fail_next = False

    def write(self, events):
        if self.fail_next:
            return False
        self.events.extend(events)
        return True

    def close(self):
        pass


class MockCollector:
    """Collector-like object that records events into a list."""

    def __init__(self):
        self.events = []
        self.enabled = True

    def record(self, event_type, payload=None, session_id=None, **kwargs):
        if not self.enabled:
            return
        self.events.append(
            Event(
                event_type=event_type,
                payload=payload or {},
                session_id=session_id,
                **kwargs,
            )
        )

    def flush(self):
        events = self.events[:]
        self.events.clear()
        return events


@pytest.fixture
def mock_collector(monkeypatch):
    """Replace the global event collector with a mock for decorator tests."""
    from topsailai.events import collector as collector_module

    mock = MockCollector()
    original = getattr(collector_module, "_collector_instance", None)
    collector_module._collector_instance = mock
    yield mock
    collector_module._collector_instance = original
