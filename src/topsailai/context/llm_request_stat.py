"""Thread-safe request statistics for LLM provider calls."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

from topsailai.utils.print_tool import print_info
from topsailai.utils.thread_local_tool import get_agent_object


class RequestTimingTicket:
    """Pair provider I/O timing segments with at most one completion."""

    def __init__(self, started_at: float) -> None:
        """Start the first provider I/O timing segment."""
        self.started_at = started_at
        self._active_started_at = started_at
        self._elapsed_sec = 0.0
        self._lock = threading.Lock()
        self._finished = False

    def pause(self, ended_at: float) -> None:
        """Pause timing after one provider I/O operation returns."""
        with self._lock:
            if self._finished or self._active_started_at is None:
                return
            self._elapsed_sec += max(0.0, ended_at - self._active_started_at)
            self._active_started_at = None

    def resume(self, started_at: float) -> None:
        """Resume timing immediately before the next provider I/O operation."""
        with self._lock:
            if self._finished or self._active_started_at is not None:
                return
            self._active_started_at = started_at

    def finish(self, ended_at: float) -> Optional[float]:
        """Return accumulated provider I/O time once, or ``None`` thereafter."""
        with self._lock:
            if self._finished:
                return None
            if self._active_started_at is not None:
                self._elapsed_sec += max(
                    0.0, ended_at - self._active_started_at
                )
                self._active_started_at = None
            self._finished = True
            return self._elapsed_sec


class LLMRequestStat:
    """Track LLM provider request volume, outcomes, errors, and durations."""

    WINDOW_SECONDS = 60.0
    DURATION_SAMPLE_LIMIT = 10000

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Initialize counters using a monotonic clock by default."""
        self._clock = clock
        self._lock = threading.RLock()
        self._request_times = deque()
        self._requests_per_minute_max = 0
        self._total_requests = 0
        self._request_successes = 0
        self._request_failures = 0
        self._response_content_errors = 0
        self._request_duration_count = 0
        self._request_duration_sum_sec = 0.0
        self._request_duration_min_sec = None
        self._request_duration_max_sec = None
        self._request_duration_samples = deque(maxlen=self.DURATION_SAMPLE_LIMIT)

    def _discard_expired(self, now: float) -> None:
        """Remove request timestamps outside the trailing one-minute window."""
        cutoff = now - self.WINDOW_SECONDS
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()

    def _record_request_locked(self, now: float) -> None:
        """Record one request while the caller holds ``_lock``."""
        self._discard_expired(now)
        self._request_times.append(now)
        self._requests_per_minute_max = max(
            self._requests_per_minute_max,
            len(self._request_times),
        )
        self._total_requests += 1

    def start_request(self) -> RequestTimingTicket:
        """Record one provider attempt and return its explicit timing ticket."""
        now = self._clock()
        with self._lock:
            self._record_request_locked(now)
        return RequestTimingTicket(now)

    def pause_request(self, ticket: RequestTimingTicket) -> None:
        """Pause one ticket immediately after provider I/O returns."""
        ticket.pause(self._clock())

    def resume_request(self, ticket: RequestTimingTicket) -> None:
        """Resume one ticket immediately before further provider I/O."""
        ticket.resume(self._clock())

    def finish_request(
        self,
        ticket: RequestTimingTicket,
        timestamp: Optional[float] = None,
    ) -> dict:
        """Record one full-response duration from a timing ticket exactly once."""
        now = self._clock() if timestamp is None else float(timestamp)
        duration = ticket.finish(now)
        with self._lock:
            if duration is not None:
                self._request_duration_count += 1
                self._request_duration_sum_sec += duration
                self._request_duration_samples.append(duration)
                if (
                    self._request_duration_min_sec is None
                    or duration < self._request_duration_min_sec
                ):
                    self._request_duration_min_sec = duration
                if (
                    self._request_duration_max_sec is None
                    or duration > self._request_duration_max_sec
                ):
                    self._request_duration_max_sec = duration
            return self._snapshot_locked()

    def record_request(self, timestamp: Optional[float] = None) -> dict:
        """Record one request attempt and return the updated statistics snapshot."""
        now = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            self._record_request_locked(now)
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

    def _request_duration_p95_locked(self) -> Optional[float]:
        """Return linear-interpolated P95 for the bounded recent sample window."""
        if not self._request_duration_samples:
            return None
        samples = sorted(self._request_duration_samples)
        rank = (len(samples) - 1) * 0.95
        lower_index = int(rank)
        upper_index = min(lower_index + 1, len(samples) - 1)
        fraction = rank - lower_index
        return samples[lower_index] + (
            samples[upper_index] - samples[lower_index]
        ) * fraction

    @staticmethod
    def _rounded_duration(value: Optional[float]) -> Optional[float]:
        """Round a duration for stable human-facing snapshots."""
        return round(value, 3) if value is not None else None

    def _snapshot_locked(self) -> dict:
        """Build a snapshot while the caller holds ``_lock``."""
        duration_avg = None
        if self._request_duration_count:
            duration_avg = (
                self._request_duration_sum_sec / self._request_duration_count
            )
        return {
            "total_requests": self._total_requests,
            "requests_per_minute": len(self._request_times),
            "requests_per_minute_max": self._requests_per_minute_max,
            "request_successes": self._request_successes,
            "request_failures": self._request_failures,
            "response_content_errors": self._response_content_errors,
            "request_duration_count": self._request_duration_count,
            "request_duration_min_sec": self._rounded_duration(
                self._request_duration_min_sec
            ),
            "request_duration_avg_sec": self._rounded_duration(duration_avg),
            "request_duration_max_sec": self._rounded_duration(
                self._request_duration_max_sec
            ),
            "request_duration_p95_sec": self._rounded_duration(
                self._request_duration_p95_locked()
            ),
        }

    def get_request_stat_info(self, timestamp: Optional[float] = None) -> dict:
        """Return current request-volume, outcome, error, and duration metrics."""
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
