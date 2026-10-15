"""Shared absolute deadline state for first-byte monitoring."""

from __future__ import annotations

import contextvars
import threading
import time as _stdlib_time
from dataclasses import dataclass
from types import SimpleNamespace


# Keep a writable module-local seam for existing deadline tests.
_AUTHORITY_MONOTONIC = _stdlib_time.monotonic
time = SimpleNamespace(monotonic=_AUTHORITY_MONOTONIC)


_CURRENT_BUDGET = contextvars.ContextVar("topsailai_first_byte_budget", default=None)


@dataclass
class FirstByteBudget:
    """Carry one attempt's absolute first-byte deadline."""

    deadline: float
    timeout: float
    warning_emitted: bool = False
    clock: object = None

    def __post_init__(self):
        """Initialize the attempt-local warning reservation lock."""
        self._warning_lock = threading.Lock()
        if self.clock is None:
            self.clock = time.monotonic

    @classmethod
    def create(cls, timeout: float, *, clock=None) -> "FirstByteBudget":
        """Create a budget from the selected monotonic clock."""
        authority_clock = time.monotonic if clock is None else clock
        return cls(authority_clock() + timeout, timeout, clock=authority_clock)

    def remaining(self) -> float:
        """Return non-negative remaining seconds."""
        return max(0.0, self.deadline - self.clock())

    def expired(self) -> bool:
        """Return whether the absolute deadline has passed."""
        return self.clock() >= self.deadline

    def warn_once(self, callback, elapsed: float) -> None:
        """Reserve one warning under a lock, then invoke the callback outside it."""
        with self._warning_lock:
            if self.warning_emitted:
                return
            self.warning_emitted = True
        callback(elapsed, self.timeout)

    def warning_required_for(self, phase: "FirstBytePhase") -> bool:
        """Return whether a committed phase crossed the deadline at publication."""
        return phase.published_at is not None and phase.published_at >= self.deadline


class FirstBytePhase:
    """Serialize publication and expiry decisions for one monitored phase."""

    def __init__(self, budget: FirstByteBudget) -> None:
        """Initialize an open phase."""
        self.budget = budget
        self._lock = threading.Lock()
        self.state = "OPEN"
        self.completed_at = None
        self.published_at = None

    def completed(self) -> float:
        """Capture provider operation completion time."""
        self.completed_at = self.budget.clock()
        return self.completed_at

    def publish(self, *, allow_late=False) -> bool:
        """Commit at the publication boundary."""
        with self._lock:
            if self.state != "OPEN":
                return self.state == "COMMITTED"
            published_at = self.budget.clock()
            self.published_at = published_at
            if published_at >= self.budget.deadline and not allow_late:
                self.state = "EXPIRED"
                return False
            self.state = "COMMITTED"
            return True

    def expire(self) -> bool:
        """Permanently expire an uncommitted phase."""
        with self._lock:
            if self.state != "OPEN":
                return self.state == "EXPIRED"
            self.state = "EXPIRED"
            self.published_at = self.budget.clock()
            return True

    def committed(self) -> bool:
        """Return whether publication committed an eligible result."""
        with self._lock:
            return self.state == "COMMITTED"


class first_byte_budget_scope:
    """Install an attempt budget in the current execution context."""

    def __init__(self, budget):
        """Store the budget to install."""
        self._budget = budget
        self._token = None

    def __enter__(self):
        """Install and return the budget."""
        self._token = _CURRENT_BUDGET.set(self._budget)
        return self._budget

    def __exit__(self, exc_type, exc_value, traceback):
        """Restore the prior budget."""
        _CURRENT_BUDGET.reset(self._token)
        return False


def resolve_first_byte_budget(timeout, explicit=None):
    """Resolve an explicit, scoped, or newly-created compatible budget."""
    scoped = _CURRENT_BUDGET.get()
    candidate = explicit if explicit is not None else scoped
    if candidate is None:
        if timeout is None or timeout <= 0:
            return None
        return FirstByteBudget.create(timeout)
    if timeout is None or timeout <= 0:
        raise ValueError("a first-byte budget requires a positive timeout")
    if candidate.timeout != timeout:
        raise ValueError("first-byte timeout is incompatible with the supplied budget")
    return candidate


def current_first_byte_budget():
    """Return the current context-local budget, if any."""
    return _CURRENT_BUDGET.get()
