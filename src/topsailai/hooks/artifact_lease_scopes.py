"""Interruption-safe scoped acquisition helpers for artifact leases."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from topsailai.hooks.artifact_lease_contracts import LeaseAcquireResult, LeaseGroupResult

if TYPE_CHECKING:
    from topsailai.hooks.artifact_leases import ArtifactLease, ArtifactLeaseGroup


class ArtifactLeaseScopeMixin:
    """Release only authority acquired by one protected scope."""

    @contextmanager
    def _lease_scope(
        self, group: ArtifactLeaseGroup, source: ArtifactLease
    ) -> Iterator[LeaseAcquireResult]:
        """Release only the exact token acquired by this scope."""
        recovery: list[ArtifactLease] = []
        try:
            result = self._acquire(group, source, recovery)
            yield result
        finally:
            if recovery:
                self.release(recovery[0])

    @contextmanager
    def _group_scope(
        self, groups: tuple[ArtifactLeaseGroup, ...]
    ) -> Iterator[LeaseGroupResult]:
        """Settle only the exact admitted group acquired by this scope."""
        recovery: list[ArtifactLeaseGroup] = []
        try:
            result = self.admit(groups, recovery)
            yield result
        finally:
            if recovery:
                self._execution_port().settle(recovery[0])
