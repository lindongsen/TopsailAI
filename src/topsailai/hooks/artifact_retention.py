"""Bounded validation, candidate indexing, and artifact retention ordering."""

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


class CandidateRegistryMixin:
    """Maintain the bounded candidate-only index used by expiry maintenance."""

    def _register_candidate(self, group) -> None:
        """Publish one candidate in both bounded registries."""
        self._groups[group._group_id] = group
        self._candidate_groups[group._group_id] = group

    def _unregister_candidate(self, group) -> None:
        """Remove exact primary custody before its bounded recovery index."""
        if self._groups.get(group._group_id) is group:
            self._groups.pop(group._group_id, None)
        if self._candidate_groups.get(group._group_id) is group:
            if group._mutation is not None and group._mutation[0] == "settle":
                group._mutation = None
            self._candidate_groups.pop(group._group_id, None)
        return

    def _expire_candidates(self) -> None:
        """Terminalize the bounded candidate index without scanning other groups."""
        with self._lock:
            for group in tuple(self._candidate_groups.values()):
                self._reconcile_group_mutation(group)
                if self._candidate_groups.get(group._group_id) is not group:
                    continue
                if group._terminal and not group._tokens and not group._pending_capture:
                    self._unregister_candidate(group)
                    continue
                if not self._valid_group(group):
                    continue
                if (
                    group._state == "candidate" and not group._pending_capture
                    and self._clock() >= group._expiry
                ):
                    self._settle_group_tokens(group, state="settled")


def valid_deadline(value: object) -> bool:
    """Accept only finite absolute monotonic float deadlines."""
    return type(value) is float and math.isfinite(value)


def valid_reclaim_limit(value: object) -> bool:
    """Accept the fixed bounded number of physical passes."""
    return type(value) is int and 1 <= value <= _MAX_RECLAIM_PASSES


def reclamation_order(values: Iterable[_T]) -> tuple[_T, ...]:
    """Order retired versions deterministically without retaining history."""
    return tuple(sorted(values, key=lambda item: (item.retired_at or 0.0, item.sequence)))
