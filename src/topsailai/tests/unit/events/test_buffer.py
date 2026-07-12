"""
Unit tests for topsailai.events.buffer.
"""

import threading

from topsailai.events.buffer import EventBuffer
from topsailai.events.models import Event


def test_buffer_append_and_drain():
    buffer = EventBuffer(max_size=10)
    e1 = Event(event_type="a", payload={})
    e2 = Event(event_type="b", payload={})
    buffer.append(e1)
    buffer.append(e2)

    assert len(buffer) == 2
    drained = buffer.drain()
    assert len(drained) == 2
    assert drained[0] is e1
    assert len(buffer) == 0


def test_buffer_drops_oldest_when_full():
    buffer = EventBuffer(max_size=3)
    events = [Event(event_type=f"e{i}", payload={}) for i in range(5)]
    for e in events:
        buffer.append(e)

    drained = buffer.drain()
    assert len(drained) == 3
    assert [e.event_type for e in drained] == ["e2", "e3", "e4"]


def test_buffer_thread_safety():
    buffer = EventBuffer(max_size=10000)
    errors = []

    def worker(start):
        try:
            for i in range(1000):
                buffer.append(Event(event_type=f"t{start}-{i}", payload={}))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(buffer) == 10000
