"""Bounded lifecycle records and deterministic request-release handles."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestHandle:
    """Own one request's delay release, lifecycle record, and worker thread."""

    request_number: int
    thread: threading.Thread | None = None
    connection: Any = None
    record: dict[str, Any] = field(default_factory=dict)
    _capture: LifecycleCapture | None = field(default=None, repr=False)
    release: threading.Event = field(default_factory=threading.Event, repr=False)
    response_finished: threading.Event = field(default_factory=threading.Event, repr=False)
    connection_closed: threading.Event = field(default_factory=threading.Event, repr=False)

    def release_delay(self) -> None:
        """Release both configured transport delays for this request."""
        self.release.set()
        if self._capture is not None:
            self._capture.notify()

    def wait_for_phase(self, phase: str, timeout: float = 5.0) -> bool:
        """Wait until the request is blocked in a named delay phase."""
        if self._capture is None:
            return False
        return self._capture._wait_for_handle_phase(self, phase, timeout)

    def wait_for_thread_exit(self, timeout: float = 5.0) -> bool:
        """Join this exact handler thread and report its observed exit."""
        thread = self.thread
        if thread is None or thread is threading.current_thread():
            return False
        thread.join(timeout)
        if thread.is_alive():
            return False
        if self._capture is not None:
            self._capture.mark(self, "thread_exited")
        return True


class LifecycleCapture:
    """Thread-safe bounded observation of completion request lifecycles."""

    def __init__(self, capacity: int):
        """Initialize bounded records and condition-based waiters."""
        self.capacity = capacity
        self._records: deque[RequestHandle] = deque(maxlen=capacity)
        self._total_records = 0
        self._dropped_records = 0
        self._last_accepted = 0
        self._condition = threading.Condition(threading.Lock())

    def start(self, request_number: int, thread: threading.Thread | None = None, connection: Any = None) -> RequestHandle:
        """Publish one request handle before its response processing begins."""
        with self._condition:
            self._total_records += 1
            if len(self._records) == self.capacity:
                self._dropped_records += 1
            handle = RequestHandle(request_number, thread, connection, {
                "request_number": request_number,
                "accepted": True,
                "headers_sent": False,
                "first_item_sent": False,
                "handler_exit": False,
                "response_finished": False,
                "connection_closed": False,
                "thread_exited": False,
                "disconnected": False,
                "waiting_phase": None,
            }, self)
            self._records.append(handle)
            self._last_accepted = request_number
            self._condition.notify_all()
            return handle

    def notify(self) -> None:
        """Wake observers after an externally changed sticky release event."""
        with self._condition:
            self._condition.notify_all()

    def _find(self, request_number: int) -> RequestHandle | None:
        return next((item for item in self._records if item.request_number == request_number), None)

    def request_handle(self, request_number: int) -> RequestHandle:
        """Return the retained request handle or raise when it was evicted."""
        with self._condition:
            handle = self._find(request_number)
            if handle is None:
                raise KeyError(request_number)
            return handle

    def wait_for_request(self, request_number: int, timeout: float = 5.0) -> bool:
        """Wait until the numbered completion has been accepted."""
        with self._condition:
            return self._condition.wait_for(lambda: self._last_accepted >= request_number, timeout)

    def wait_for_phase(self, request_number: int, phase: str, timeout: float = 5.0) -> bool:
        """Wait for an exact active delay phase, or finalized completion."""
        try:
            handle = self.request_handle(request_number)
        except KeyError:
            return False
        return self._wait_for_handle_phase(handle, phase, timeout)

    def _wait_for_handle_phase(self, handle: RequestHandle, phase: str, timeout: float) -> bool:
        """Wait on an already-owned handle independent of bounded history."""
        with self._condition:
            ready = lambda: (handle.record["waiting_phase"] == phase
                             or handle.response_finished.is_set())
            if not self._condition.wait_for(ready, timeout):
                return False
            return handle.record["waiting_phase"] == phase

    def wait_for_thread_exit(self, request_number: int, timeout: float = 5.0) -> bool:
        """Join the retained request's exact worker thread."""
        try:
            return self.request_handle(request_number).wait_for_thread_exit(timeout)
        except KeyError:
            return False

    def mark(self, handle: RequestHandle, field: str, value: Any = True) -> None:
        """Update the authoritative record and notify all condition waiters."""
        with self._condition:
            handle.record[field] = value
            if field == "response_finished" and value:
                handle.response_finished.set()
            elif field == "connection_closed" and value:
                handle.connection_closed.set()
            self._condition.notify_all()

    def state(self) -> dict[str, Any]:
        """Return bounded JSON-safe lifecycle snapshots."""
        with self._condition:
            records = []
            for handle in self._records:
                record = dict(handle.record)
                thread = handle.thread
                record["thread_exited"] = bool(thread is not None and not thread.is_alive())
                records.append(record)
            return {"lifecycle_capacity": self.capacity, "lifecycle_records": records,
                    "dropped_lifecycle_count": self._dropped_records}

    def clear(self) -> None:
        """Clear observation history without changing retained handle ownership."""
        with self._condition:
            self._records.clear()
            self._total_records = self._dropped_records = 0
            self._last_accepted = 0
            self._condition.notify_all()
