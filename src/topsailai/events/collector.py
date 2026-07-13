"""Event collector: buffers events and flushes them to a backend."""

from __future__ import annotations

import atexit
import logging
import threading
from typing import Optional

from topsailai.events.backends import create_backend
from topsailai.events.buffer import EventBuffer
from topsailai.events.config import EventConfig, get_session_id
from topsailai.events.models import Event

logger = logging.getLogger(__name__)


class NoOpFlusher:
    """Flusher placeholder used when events are disabled."""

    _stop_event = threading.Event()
    _stop_event.set()

    def start(self) -> None:
        pass

    def join(self, timeout: Optional[float] = None) -> None:
        pass


class BackgroundFlusher(threading.Thread):
    """Background thread that periodically flushes the event buffer."""

    def __init__(self, collector: "EventCollector", interval_ms: float):
        super().__init__(name="EventFlusher", daemon=True)
        self._collector = collector
        self._interval_ms = interval_ms
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._interval_ms / 1000.0)
            if not self._stop_event.is_set():
                try:
                    self._collector.flush()
                except Exception:
                    logger.exception("Event flush failed")

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None) -> None:
        super().join(timeout)


class EventCollector:
    """Thread-safe event collector with a bounded buffer and periodic flush."""

    def __init__(self, config: Optional[EventConfig] = None):
        self.config = config or EventConfig.from_env()
        self._buffer = EventBuffer(self.config.buffer_size)
        self._backend = None
        self._flusher = None
        self._flush_lock = threading.Lock()
        self._closed = False

        if self.config.enabled:
            self._backend = create_backend(self.config)
            if self._backend is not None:
                try:
                    self._backend.cleanup()
                except Exception:
                    logger.exception("Backend cleanup failed")
            self._flusher = BackgroundFlusher(self, self.config.flush_interval_ms)
        else:
            self._flusher = NoOpFlusher()

    def start(self) -> "EventCollector":
        """Start the background flusher if enabled. Idempotent."""
        if self._closed:
            return self
        if self.config.enabled and not isinstance(self._flusher, BackgroundFlusher):
            self._flusher = BackgroundFlusher(self, self.config.flush_interval_ms)
        if isinstance(self._flusher, BackgroundFlusher) and not self._flusher.is_alive():
            self._flusher.start()
        return self

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def backend(self):
        """Public alias for the configured backend."""
        return self._backend

    @property
    def events(self):
        """Return a snapshot of buffered events as dictionaries."""
        return [event.to_dict() for event in self._buffer.snapshot()]

    def record(
        self,
        event_or_type,
        payload=None,
        session_id=None,
        flush: bool = False,
        **kwargs,
    ):
        """Append an event or create one from the given arguments.

        When ``session_id`` is not provided (``None``), the collector resolves
        it from environment variables (``TOPSAILAI_SESSION_ID`` / ``SESSION_ID``)
        so that JSONL records stay consistent with the file backend's filename.
        Explicitly passed values, including empty strings, are preserved.

        Args:
            flush: If True, immediately flush the buffer to the backend after
                recording. This makes the event durable synchronously but adds
                a small I/O cost on the caller thread.
        """
        if not self.config.enabled or self._closed:
            return
        if isinstance(event_or_type, Event):
            event = event_or_type
        else:
            if session_id is None:
                session_id = get_session_id()
            event = Event.create(
                event_type=event_or_type,
                payload=payload or {},
                session_id=session_id,
                **kwargs,
            )
        self._buffer.append(event)
        if flush:
            self.flush()

    def flush(self) -> bool:
        """Flush buffered events to the backend. Re-queue on failure."""
        if not self.config.enabled or self._backend is None or self._closed:
            return False
        with self._flush_lock:
            events = self._buffer.drain()
            if not events:
                return True
            try:
                ok = self._backend.write(events)
            except Exception:
                logger.exception("Event backend write failed")
                ok = False
            if not ok:
                self._buffer.prepend(events)
                return False
            return True

    def close(self) -> None:
        """Stop the flusher, flush remaining events, and close the backend."""
        if self._closed:
            return
        if isinstance(self._flusher, BackgroundFlusher):
            self._flusher.stop()
            if self._flusher.is_alive():
                self._flusher.join(timeout=2.0)
        try:
            self.flush()
        except Exception:
            logger.exception("Final event flush failed")
        self._closed = True
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception:
                logger.exception("Backend close failed")


# Module-level singleton.
_collector_instance: Optional[EventCollector] = None
_collector_lock = threading.Lock()


def get_event_collector(config: Optional[EventConfig] = None) -> EventCollector:
    """Return the global event collector, creating and starting it if necessary."""
    global _collector_instance
    with _collector_lock:
        if _collector_instance is None:
            _collector_instance = EventCollector(config).start()
        return _collector_instance


def reset_event_collector() -> None:
    """Flush, close, and reset the global event collector."""
    global _collector_instance
    with _collector_lock:
        if _collector_instance is not None:
            try:
                _collector_instance.flush()
                _collector_instance.close()
            except Exception:
                pass
            _collector_instance = None


def record_event(
    event_type: str,
    payload: dict,
    session_id: Optional[str] = None,
    flush: bool = False,
    **kwargs,
) -> None:
    """Record an event through the global collector if enabled.

    Args:
        flush: If True, immediately flush the buffer to the backend after
            recording. This makes the event durable synchronously.
    """
    collector = get_event_collector()
    if not collector.enabled:
        return
    collector.record(event_type, payload=payload, session_id=session_id, flush=flush, **kwargs)


def _atexit_flush() -> None:
    """Flush remaining events before process exit."""
    global _collector_instance
    with _collector_lock:
        if _collector_instance is not None:
            try:
                _collector_instance.flush()
                _collector_instance.close()
            except Exception:
                logger.exception("Final event flush on exit failed")


atexit.register(_atexit_flush)
