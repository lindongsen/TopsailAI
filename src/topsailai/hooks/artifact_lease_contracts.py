"""Immutable contracts for bounded artifact leases and retention."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from topsailai.hooks.artifact_leases import ArtifactLease, ArtifactLeaseGroup, CaptureReceipt


@dataclass(frozen=True, slots=True)
class LeaseGroupResult:
    """Return one newly reserved lease group or a stable rejection."""

    accepted: bool
    group: ArtifactLeaseGroup | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LeaseAcquireResult:
    """Return one independently charged exact lease or a stable rejection."""

    accepted: bool
    lease: ArtifactLease | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptureReceiptResult:
    """Return one manager-owned pending capture receipt."""

    accepted: bool
    receipt: CaptureReceipt | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LeaseMutationResult:
    """Report an exact metadata mutation without exposing authority internals."""

    accepted: bool
    already_settled: bool = False
    errors: tuple[str, ...] = ()


class ArtifactLeaseDebt:
    """Identify one exact bounded file-deletion obligation."""

    __slots__ = ("debt_id", "category", "_manager", "_settled")

    def __init__(self, debt_id: str, category: str = "artifact_cleanup_pending") -> None:
        """Create an untrusted debt value; managers bind their own exact instances."""
        self.debt_id = debt_id
        self.category = category
        self._manager = None
        self._settled = False


@dataclass(frozen=True, slots=True)
class LeaseReclaimResult:
    """Report bounded physical cleanup scheduling and remaining obligations."""

    accepted: bool
    examined: int = 0
    removed: int = 0
    cleanup_pending: bool = False
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactLeaseSnapshot:
    """Expose bounded scalar lease-manager state without sensitive locators."""

    manager_state: Literal["open", "closing", "closed"]
    candidate_groups: int
    active_groups: int
    admitted_groups: int
    execution_debt_groups: int
    live_tokens: int
    reserved_tokens: int
    capture_slots: int
    reserved_entries: int
    reserved_bytes: int
    stored_versions: int
    reserved_versions: int
    stored_bytes: int
    retired_versions: int
    pending_captures: int
    publication_stages: int
    cleanup_debts: tuple[ArtifactLeaseDebt, ...]
