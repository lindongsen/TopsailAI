"""Bounded non-recursive diagnostics for the unified hooks runtime."""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)


class DiagnosticBuffer:
    """Retain bounded safe metadata and isolate an optional observer off-thread."""

    def __init__(
        self,
        *,
        capacity: int,
        observer: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        """Create a bounded diagnostic buffer and optional isolated observer worker."""
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("diagnostic capacity must be a positive integer")
        self._records: deque[dict[str, object]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._dropped = 0
        self._observer = observer
        self._observer_queue: queue.Queue[dict[str, object] | None] = queue.Queue(capacity)
        self._closed = False
        self._local = threading.local()
        self._thread: threading.Thread | None = None
        if observer is not None:
            self._thread = threading.Thread(
                target=self._observe,
                name="hook-diagnostic-observer",
                daemon=True,
            )
            self._thread.start()

    def publish(self, kind: str, **fields: object) -> None:
        """Publish bounded scalar metadata without blocking the calling flow."""
        if self._closed or getattr(self._local, "publishing", False):
            return
        self._local.publishing = True
        try:
            record = {"kind": kind}
            for key, value in fields.items():
                if type(key) is str and type(value) in (bool, int, float, str):
                    record[key] = value
            with self._lock:
                if len(self._records) == self._records.maxlen:
                    self._dropped += 1
                self._records.append(record)
            if self._observer is not None:
                try:
                    self._observer_queue.put_nowait(dict(record))
                except queue.Full:
                    with self._lock:
                        self._dropped += 1
        except BaseException:
            _LOGGER.debug("Hook diagnostic publication failed", exc_info=True)
        finally:
            self._local.publishing = False

    def drain(self, limit: int) -> tuple[dict[str, object], ...]:
        """Remove and return at most limit retained records with aggregate drops."""
        if type(limit) is not int or limit <= 0:
            return ()
        with self._lock:
            records = [self._records.popleft() for _ in range(min(limit, len(self._records)))]
            if self._dropped and len(records) < limit:
                records.append({"kind": "diagnostics_dropped", "count": self._dropped})
                self._dropped = 0
        return tuple(records)

    def in_observer(self) -> bool:
        """Return whether the current thread is executing the isolated observer."""
        return bool(getattr(self._local, "observing", False))

    def close(self, timeout_seconds: float) -> None:
        """Stop observer acceptance and boundedly request worker shutdown."""
        self._closed = True
        if self._thread is None:
            return
        try:
            self._observer_queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(max(0.0, timeout_seconds))
        if self._thread.is_alive():
            _LOGGER.warning("Hook diagnostic observer did not stop before the deadline")

    def _observe(self) -> None:
        """Consume observer callbacks without permitting recursive diagnostics."""
        while True:
            record = self._observer_queue.get()
            if record is None:
                return
            if self._closed:
                self._discard_observer_queue(record)
                return
            self._local.observing = True
            try:
                self._observer(record)
            except BaseException as exc:
                with self._lock:
                    self._dropped += 1
                _LOGGER.debug(
                    "Hook diagnostic observer failed: %s", type(exc).__name__
                )
            finally:
                self._local.observing = False
            if self._closed:
                self._discard_observer_queue()
                return

    def _discard_observer_queue(self, first: object | None = None) -> None:
        """Discard queued callbacks after closure and account for every record."""
        dropped = 1 if isinstance(first, dict) else 0
        while True:
            try:
                record = self._observer_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(record, dict):
                dropped += 1
        if dropped:
            with self._lock:
                self._dropped += dropped
