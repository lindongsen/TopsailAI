"""Event collector and background flush orchestration."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from topsailai.events.backends.base import EventBackend
from topsailai.events.backends.file import FileEventBackend
from topsailai.events.buffer import EventBuffer
from topsailai.events.config import EventConfig, get_event_config
from topsailai.events.models import Event

logger = logging.getLogger(__name__)


class BackgroundFlusher:
    """Periodically flushes a collector's buffer to its backend."""

    def __init__(self, collector: "EventCollector"):
        self._collector = collector
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def start(self) -> None:
        """Start the background flush thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="topsailai-events-flush",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Signal the flush thread to stop and wait for it to finish."""
        with self._lock:
            thread = self._thread
            self._thread = None
        self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def _run(self) -> None:
        interval = self._collector.config.flush_interval_seconds
        while not self._stop_event.is_set():
            try:
                self._collector.flush()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Background event flush failed: %s", exc)
            self._stop_event.wait(interval)


class EventCollector:
    """Collects events in a bounded buffer and periodically flushes them."""

    def __init__(self, config: Optional[EventConfig] = None):
        self.config = config or get_event_config()
        self._buffer = EventBuffer(max_size=self.config.buffer_size)
        # When disabled, avoid creating the backend or starting the flusher
        # so that record_event() is a cheap no-op.
        if self.config.enabled:
            self._backend = self._create_backend()
            self._flusher = BackgroundFlusher(self)
        else:
            self._backend = _NoOpBackend()
            self._flusher = _NoOpFlusher()
        self._lock = threading.Lock()
        self._closed = False

    def _create_backend(self) -> EventBackend:
        backend = self.config.backend
        if backend == "file":
            return FileEventBackend(file_path=self.config.file_path)
        if backend == "db":
            from topsailai.events.backends.db import DBEventBackend

            return DBEventBackend()
        if backend == "webhook":
            from topsailai.events.backends.webhook import WebhookEventBackend

            return WebhookEventBackend()
        logger.warning(
            "Unsupported event backend '%s'; falling back to file backend", backend
        )
        return FileEventBackend(file_path=self.config.file_path)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def backend(self) -> EventBackend:
        return self._backend

    @property
    def buffer(self) -> EventBuffer:
        return self._buffer

    def record(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Record an event if the collector is enabled."""
        if not self.enabled:
            return
        event = Event(
            event_type=event_type,
            session_id=session_id,
            payload=payload or {},
            **kwargs,
        )
        self._buffer.append(event)

    def flush(self) -> bool:
        """Synchronously flush buffered events to the backend."""
        if not self.enabled:
            return True
        events = self._buffer.drain()
        if not events:
            return True
        try:
            success = self._backend.write(events)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Event backend write failed: %s", exc)
            success = False
        if not success:
            self._buffer.extend(events)
        return success

    def start(self) -> None:
        """Start the background flush thread."""
        if not self.enabled or self._closed:
            return
        self._flusher.start()

    def close(self, timeout: float = 1.0) -> None:
        """Stop the background flusher and perform a final flush."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._flusher.stop(timeout=timeout)
        self.flush()
        try:
            self._backend.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Event backend close failed: %s", exc)

    def __del__(self) -> None:
        # Avoid joining a thread during interpreter shutdown, which can raise
        # exceptions or hang. A manual close() is the supported cleanup path.
        if threading is None:
            return
        try:
            self.close()
        except Exception:  # pragma: no cover - best effort
            pass


class _NoOpBackend(EventBackend):
    """Backend used when the collector is disabled."""

    def write(self, events: List[Event]) -> bool:
        return True

    def close(self) -> None:
        pass


class _NoOpFlusher:
    """Flusher placeholder used when the collector is disabled."""

    def start(self) -> None:
        pass

    def stop(self, timeout: float = 1.0) -> None:
        pass


# Module-level singleton. Lazy-initialized on first use so that importing the
# module does not spawn threads or read environment variables.
_COLLECTOR: Optional[EventCollector] = None
_collector_lock = threading.Lock()


def get_event_collector() -> EventCollector:
    """Return the module-level event collector, starting it on first use."""
    global _COLLECTOR
    if _COLLECTOR is not None:
        return _COLLECTOR
    with _collector_lock:
        if _COLLECTOR is not None:
            return _COLLECTOR
        _COLLECTOR = EventCollector()
        _COLLECTOR.start()
    return _COLLECTOR


def reset_event_collector() -> None:
    """Stop and reset the module-level collector. Intended for tests."""
    global _COLLECTOR
    with _collector_lock:
        if _COLLECTOR is not None:
            _COLLECTOR.close()
            _COLLECTOR = None


def record_event(
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    **kwargs,
) -> None:
    """Record an event using the module-level collector.

    This is a cheap no-op when events are disabled: it reads the configuration
    once and returns without creating the backend, buffer, or background thread.
    """
    config = get_event_config()
    if not config.enabled:
        return
    collector = get_event_collector()
    collector.record(event_type, payload=payload, session_id=session_id, **kwargs)
