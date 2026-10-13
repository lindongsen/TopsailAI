"""Immutable cleanup timing contracts without resource authority. Author: DawsonLin."""

from __future__ import annotations

import math
from dataclasses import dataclass

QUERY_ALLOWANCE_SECONDS = 0.050
CLEANUP_ALLOWANCE_SECONDS = 0.300


def finite_deadline(value: object) -> float:
    """Validate an exact finite numeric deadline before synchronization or I/O."""
    if type(value) not in (int, float):
        raise ValueError("deadline must be an exact finite int or float")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError("deadline must be finite") from error
    if not math.isfinite(result):
        raise ValueError("deadline must be finite")
    return result


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """Select a timing policy, never confer custody or signaling authority."""

    mode: str = "observation_only"

    def __post_init__(self) -> None:
        """Reject unknown modes without normalization or implicit escalation."""
        if type(self.mode) is not str or self.mode not in (
            "observation_only", "resume_owned_stop"
        ):
            raise ValueError("unsupported cleanup recovery policy")


@dataclass(frozen=True, slots=True)
class CleanupPhases:
    """Carry absolute work, channel and handback phase endpoints."""

    work_end: float
    channels_end: float
    handback_end: float


@dataclass(frozen=True, slots=True)
class CleanupBudget:
    """Retain original execution and initial cleanup deadlines across recovery."""

    execution_deadline: float
    cleanup_deadline: float

    def __post_init__(self) -> None:
        """Detach numeric horizons and reject cleanup before execution expiry."""
        execution = finite_deadline(self.execution_deadline)
        cleanup = finite_deadline(self.cleanup_deadline)
        if cleanup < execution:
            raise ValueError("cleanup deadline precedes execution deadline")
        object.__setattr__(self, "execution_deadline", execution)
        object.__setattr__(self, "cleanup_deadline", cleanup)

    def initial_horizon(self, first_cleanup_entry: float) -> float:
        """Compute the fixed first-entry horizon without renewing initial cleanup."""
        entry = finite_deadline(first_cleanup_entry)
        return min(self.cleanup_deadline, entry + CLEANUP_ALLOWANCE_SECONDS)

    def signal_deadline(self, recovery_deadline: float, policy: RecoveryPolicy) -> float:
        """Limit signal timing; callers must separately prove live exact custody."""
        recovery = finite_deadline(recovery_deadline)
        if type(policy) is not RecoveryPolicy:
            raise ValueError("recovery policy must be an exact RecoveryPolicy")
        if policy.mode == "resume_owned_stop":
            return recovery
        return min(recovery, self.cleanup_deadline)

    def phases(self, entry: float, deadline: float) -> CleanupPhases:
        """Reserve channel and handback time without extending the caller horizon."""
        start = finite_deadline(entry)
        end = finite_deadline(deadline)
        remaining = max(0.0, end - start)
        if not math.isfinite(remaining):
            raise ValueError("cleanup interval must be finite")
        handback = min(remaining * 0.2, QUERY_ALLOWANCE_SECONDS)
        channels_end = end - handback
        work_end = channels_end - remaining * 0.2
        return CleanupPhases(work_end, channels_end, end)
