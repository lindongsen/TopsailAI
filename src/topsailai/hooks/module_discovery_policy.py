"""Bounded policy and deadline accounting for module discovery."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from math import floor
from typing import Callable


@dataclass(frozen=True, slots=True)
class ModuleDiscoveryPolicy:
    """Bound one complete module discovery operation."""

    timeout_ms: int = 10_000
    max_scanned_entries: int = 4_096
    max_candidates: int = 1_024


class DiscoveryBudget:
    """Track one absolute deadline and latched cooperative cancellation."""

    __slots__ = ("_cancellation", "_cancelled", "_clock", "deadline")

    def __init__(
        self,
        timeout_ms: int,
        cancellation: threading.Event | None,
        clock: Callable[[], float],
    ) -> None:
        """Capture one absolute deadline from the supplied monotonic clock."""
        self._clock = clock
        self._cancellation = cancellation
        self._cancelled = False
        self.deadline = clock() + timeout_ms / 1_000

    def rejection(self) -> str | None:
        """Return the highest-priority current liveness rejection, if any."""
        if self._cancelled or (
            self._cancellation is not None and self._cancellation.is_set()
        ):
            self._cancelled = True
            return "module discovery cancelled"
        if self._clock() >= self.deadline:
            return "module discovery timeout"
        return None

    def remaining_ms(self) -> int:
        """Return the floor of milliseconds remaining on the absolute deadline."""
        return floor((self.deadline - self._clock()) * 1_000)


def make_discovery_budget(
    timeout_ms: int,
    cancellation: threading.Event | None,
) -> DiscoveryBudget:
    """Construct the production per-invocation budget."""
    return DiscoveryBudget(timeout_ms, cancellation, time.monotonic)


def validate_discovery_policy(policy: object) -> bool:
    """Validate the exact public policy type and all v1 bounds."""
    if type(policy) is not ModuleDiscoveryPolicy:
        return False
    values = (
        (policy.timeout_ms, 1, 600_000),
        (policy.max_scanned_entries, 1, 65_536),
        (policy.max_candidates, 1, 4_096),
    )
    if any(type(value) is not int or not lower <= value <= upper for value, lower, upper in values):
        return False
    return policy.max_candidates <= policy.max_scanned_entries
