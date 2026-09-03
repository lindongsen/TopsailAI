"""Thread-safe request-volume statistics for LLM provider calls."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

from topsailai.utils.print_tool import print_info
from topsailai.utils.thread_local_tool import get_agent_object


class LLMRequestStat:
    """Track LLM provider request volume, outcomes, and content errors."""

    WINDOW_SECONDS = 60.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Initialize counters using a monotonic clock by default."""
        self._clock = clock
        self._lock = threading.RLock()
        self._request_times = deque()
        self._total_requests = 0
        self._request_successes = 0
        self._request_failures = 0
        self._response_content_errors = 0

    def _discard_expired(self, now: float) -> None:
        """Remove request timestamps outside the trailing one-minute window."""
        cutoff = now - self.WINDOW_SECONDS
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()

    def record_request(self, timestamp: Optional[float] = None) -> dict:
        """Record one request attempt and return the updated statistics snapshot."""
        now = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            self._discard_expired(now)
            self._request_times.append(now)
            self._total_requests += 1
            return self._snapshot_locked()

    def record_request_success(self) -> dict:
        """Record one request that returned a response with meaningful content."""
        with self._lock:
            self._request_successes += 1
            return self._snapshot_locked()

    def record_request_failure(self) -> dict:
        """Record one request that failed to return meaningful response content."""
        with self._lock:
            self._request_failures += 1
            return self._snapshot_locked()

    def record_response_content_error(self) -> dict:
        """Record one action response whose tool execution produced an error."""
        with self._lock:
            self._response_content_errors += 1
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict:
        """Build a snapshot while the caller holds ``_lock``."""
        return {
            "total_requests": self._total_requests,
            "requests_per_minute": len(self._request_times),
            "request_successes": self._request_successes,
            "request_failures": self._request_failures,
            "response_content_errors": self._response_content_errors,
        }

    def get_request_stat_info(self, timestamp: Optional[float] = None) -> dict:
        """Return current request-volume, outcome, and content-error counters."""
        now = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            self._discard_expired(now)
            return self._snapshot_locked()

    def print_request_stat(self, snapshot: Optional[dict] = None) -> None:
        """Print a supplied or current request-statistics snapshot."""
        request_stat_info = snapshot or self.get_request_stat_info()
        print_info(f"[LLMRequestStat] {request_stat_info}")


def record_current_agent_response_content_error() -> None:
    """Record one content error on the current agent, when available."""
    agent = get_agent_object()
    request_stat = getattr(agent, "llm_request_stat", None)
    if request_stat is not None:
        request_stat.record_response_content_error()
