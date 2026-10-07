"""Restricted recovery and execution capabilities for artifact leases."""

from __future__ import annotations

from typing import TYPE_CHECKING

from topsailai.hooks.artifact_lease_contracts import (
    ArtifactLeaseSnapshot,
    LeaseMutationResult,
    LeaseReclaimResult,
)

if TYPE_CHECKING:
    from topsailai.hooks.artifact_leases import ArtifactLeaseGroup, ArtifactLeaseManager


class ManagedArtifactRecovery:
    """Permit only bounded retry of manager-known zero-reference storage."""

    __slots__ = ("_manager",)

    def __init__(self, manager: ArtifactLeaseManager) -> None:
        """Bind one facade without exposing the physical owner."""
        self._manager = manager

    def _bind_capture_slot(self, slot: object) -> None:
        """Bind the original slot before insertion into the owner ledger."""
        self._manager._bind_capture_slot(slot)

    def snapshot(self) -> ArtifactLeaseSnapshot:
        """Return the manager's bounded state summary."""
        return self._manager.snapshot()

    def retry(self, *, deadline: float) -> LeaseReclaimResult:
        """Retry only zero-reference file deletion obligations with a new budget."""
        return self._manager.reclaim(deadline=deadline, pressure=True)


class ExecutionLeasePort:
    """Settle whole execution groups for trusted framework integration."""

    __slots__ = ("_manager", "_identity")

    def __init__(self, manager: ArtifactLeaseManager, identity: object) -> None:
        """Construct only for the issuing manager."""
        self._manager = manager
        self._identity = identity

    def retain_for_cleanup(self, group: ArtifactLeaseGroup) -> LeaseMutationResult:
        """Transfer one admitted group to execution cleanup debt."""
        return self._manager._retain_for_cleanup(self, group)

    def settle(self, group: ArtifactLeaseGroup) -> LeaseMutationResult:
        """Settle the exact whole admitted or debt group."""
        return self._manager._settle_execution(self, group)


def get_artifact_lease_recovery(error: BaseException) -> ManagedArtifactRecovery | None:
    """Return only the restricted managed recovery facade attached to an error."""
    value = getattr(error, "_topsailai_artifact_lease_recovery", None)
    return value if isinstance(value, ManagedArtifactRecovery) else None
