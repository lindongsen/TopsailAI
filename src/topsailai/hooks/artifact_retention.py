"""Bounded validation and ordering helpers for artifact retention."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Protocol, TypeVar

_MAX_RECLAIM_PASSES = 16
_T = TypeVar("_T", bound="RetirableVersion")


class RetirableVersion(Protocol):
    """Describe the metadata required for deterministic reclamation order."""

    retired_at: float | None
    sequence: int


def valid_deadline(value: object) -> bool:
    """Accept only finite absolute monotonic float deadlines."""
    return type(value) is float and math.isfinite(value)


def valid_reclaim_limit(value: object) -> bool:
    """Accept the fixed bounded number of physical passes."""
    return type(value) is int and 1 <= value <= _MAX_RECLAIM_PASSES


def reclamation_order(values: Iterable[_T]) -> tuple[_T, ...]:
    """Order retired versions deterministically without retaining history."""
    return tuple(sorted(values, key=lambda item: (item.retired_at or 0.0, item.sequence)))
