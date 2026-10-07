"""Exact bounded leases over immutable framework-owned artifacts."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from topsailai.hooks.artifact_contracts import (
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
)
from topsailai.hooks.artifact_lease_authority import (
    ExecutionLeasePort,
    ManagedArtifactRecovery,
    get_artifact_lease_recovery,
)
from topsailai.hooks.artifact_lease_contracts import (
    ArtifactLeaseDebt,
    ArtifactLeaseSnapshot,
    LeaseAcquireResult,
    LeaseGroupResult,
    LeaseMutationResult,
    LeaseReclaimResult,
)
from topsailai.hooks.artifact_lease_receipts import ArtifactLeaseReceiptMixin
from topsailai.hooks.artifact_lease_scopes import ArtifactLeaseScopeMixin
from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin
from topsailai.hooks.artifact_physical_lock import ExactPhysicalLock
from topsailai.hooks.artifact_publication import ArtifactPublicationMixin
from topsailai.hooks.artifact_retention import (
    reclamation_order,
    valid_deadline,
    valid_reclaim_limit,
)
from topsailai.hooks.artifact_store import ArtifactCaptureOwner, CapturedArtifact

_MAX_CANDIDATES = 16
_MAX_VERSIONS = 128
_MAX_GROUPS = 4096
_MAX_TOKENS = 4096
_CANDIDATE_TTL_SECONDS = 60.0
_RETIRED_RETENTION_SECONDS = 60.0
_ISSUER = object()


@dataclass(slots=True)
class _Version:
    """Retain one physical owner artifact and exact lease references."""

    artifact: CapturedArtifact
    sequence: int
    tokens: set[int] = field(default_factory=set)
    retired_at: float | None = None
    cleanup_pending: bool = False


class ArtifactLease:
    """Represent one independently charged immutable version reference."""

    __slots__ = ("_issuer", "_manager", "_token_id", "_group", "_version", "_released")

    def __init__(self, issuer: object) -> None:
        """Reject caller construction of lease authority."""
        if issuer is not _ISSUER:
            raise TypeError("ArtifactLease has no public constructor")

    @property
    def identity(self) -> str:
        """Return the captured content identity without a host locator."""
        return self._version.artifact.identity

    @property
    def entries(self):
        """Return the immutable captured inventory."""
        return self._version.artifact.entries

    @property
    def total_bytes(self) -> int:
        """Return the captured payload bytes."""
        return self._version.artifact.total_bytes

    @property
    def directory(self):
        """Return the locator only while this exact token remains live."""
        if self._released:
            raise RuntimeError("artifact lease is released")
        return self._version.artifact.directory

    @property
    def released(self) -> bool:
        """Return whether this exact token is settled."""
        return self._released

    def __reduce__(self):
        """Reject serialization of lease authority."""
        raise TypeError("ArtifactLease is not serializable")


class ArtifactLeaseGroup:
    """Hold one bounded lifecycle reference class."""

    __slots__ = (
        "_issuer", "_manager", "_group_id", "_state", "_birth", "_expiry",
        "_tokens", "_pending_capture", "_mutation", "_terminal",
    )

    def __init__(self, issuer: object) -> None:
        """Reject caller construction of group authority."""
        if issuer is not _ISSUER:
            raise TypeError("ArtifactLeaseGroup has no public constructor")

    @property
    def state(self) -> str:
        """Return the bounded lifecycle state."""
        return self._state

    @property
    def expires_at(self) -> float:
        """Return the fixed candidate expiry."""
        return self._expiry

    def __reduce__(self):
        """Reject serialization of group authority."""
        raise TypeError("ArtifactLeaseGroup is not serializable")


class CaptureReceipt:
    """Bind one candidate reservation to the original U07 capture slot."""

    __slots__ = (
        "_issuer", "_manager", "_receipt_id", "_group", "_state", "_slot",
        "_artifact", "_reserved_entries", "_reserved_bytes", "_reserved_token",
        "_reserved_version", "_deadline",
    )

    def __init__(self, issuer: object) -> None:
        """Reject caller construction of receipt authority."""
        if issuer is not _ISSUER:
            raise TypeError("CaptureReceipt has no public constructor")

    @property
    def state(self) -> str:
        """Return the bounded receipt state."""
        return self._state




class ArtifactLeaseManager(
    ArtifactLeaseReceiptMixin, ArtifactLeaseScopeMixin,
    ArtifactLeaseTransactionMixin, ArtifactPublicationMixin,
):
    """Own one U07 owner and bound all lease, debt, and cleanup metadata."""

    _max_tokens = _MAX_TOKENS
    _max_versions = _MAX_VERSIONS

    def __init__(
        self, *, artifact_root: str, trust: ArtifactCaptureTrust, _clock=time.monotonic
    ) -> None:
        """Create one manager with immutable managed recovery routing."""
        self._clock = _clock
        self._lock = threading.RLock()
        self._physical = ExactPhysicalLock(self._lock)
        self._state: Literal["open", "closing", "closed"] = "open"
        self._groups: dict[int, ArtifactLeaseGroup] = {}
        self._tokens: dict[int, ArtifactLease] = {}
        self._versions: dict[int, _Version] = {}
        self._next_group = 1
        self._next_token = 1
        self._next_version = 1
        self._receipt: CaptureReceipt | None = None
        self._publication_cell = None
        self._publication_stage = None
        self._cleanup_debt_views: dict[str, ArtifactLeaseDebt] = {}
        self._close_deadline: float | None = None
        self._execution_identity = object()
        self._recovery = ManagedArtifactRecovery(self)
        self._execution = ExecutionLeasePort(self, self._execution_identity)
        self._owner = ArtifactCaptureOwner._new_managed(
            artifact_root=artifact_root, trust=trust, recovery=self._recovery
        )

    def begin_candidate(self, *, deadline: float | None = None) -> LeaseGroupResult:
        """Reserve one candidate position with a non-sliding lifetime."""
        if deadline is not None and not valid_deadline(deadline):
            return LeaseGroupResult(False, errors=("invalid_lease_argument",))
        with self._lock:
            now = self._clock()
            if self._state != "open":
                return LeaseGroupResult(False, errors=("artifact_lease_manager_closed",))
            candidates = sum(group._state in ("candidate", "staged") for group in self._groups.values())
            if candidates >= _MAX_CANDIDATES or len(self._groups) >= _MAX_GROUPS:
                return LeaseGroupResult(False, errors=("artifact_lease_capacity_exceeded",))
            group = ArtifactLeaseGroup(_ISSUER)
            group._issuer = self._execution_identity
            group._manager = self
            group._group_id = self._next_group
            group._state = "candidate"
            group._birth = now
            group._expiry = now + _CANDIDATE_TTL_SECONDS
            if deadline is not None:
                group._expiry = min(group._expiry, deadline)
            group._tokens = set()
            group._pending_capture = False
            group._mutation = None
            group._terminal = False
            self._next_group += 1
            self._groups[group._group_id] = group
            return LeaseGroupResult(True, group)

    def capture(
        self,
        group: ArtifactLeaseGroup,
        requests: tuple[ArtifactCaptureRequest, ...],
        *,
        policy: ArtifactCapturePolicy = ArtifactCapturePolicy(),
        cancellation: threading.Event | None = None,
        deadline: float | None = None,
    ) -> LeaseAcquireResult:
        """Reserve before one physical capture and adopt only into a live candidate."""
        recovery: list[CaptureReceipt] = []
        receipt: CaptureReceipt | None = None
        physical_owner = object()
        try:
            reserved = self._reserve_capture(
                group, requests, policy, deadline, recovery=recovery
            )
            if not reserved.accepted or reserved.receipt is None:
                return LeaseAcquireResult(False, errors=reserved.errors)
            receipt = reserved.receipt
            if not self._acquire_physical(physical_owner):
                self._rollback_receipt(receipt)
                recovery.clear()
                return LeaseAcquireResult(False, errors=("artifact_lease_busy",))
            recovery.clear()
            manager_deadline = (
                group._expiry
                if deadline is None
                else min(group._expiry, deadline)
            )
            remaining = max(0.0, manager_deadline - self._clock())
            result = self._owner.capture(
                requests,
                policy=policy,
                cancellation=cancellation,
                deadline=time.monotonic() + remaining,
            )
            receipt._state = "issued" if result.accepted else "failed"
            receipt._artifact = result.artifact
            self._release_physical(physical_owner)
            if not result.accepted:
                self._finish_failed_receipt(receipt)
                return LeaseAcquireResult(False, errors=result.errors)
            return self._finish_capture(receipt, cancellation)
        except BaseException as primary:
            self._release_physical(physical_owner)
            if receipt is not None:
                self._reconcile_interrupted_adoption(receipt, primary)
            elif recovery:
                self._rollback_receipt_after_interruption(recovery[0], primary)
            self._attach_recovery(primary)
            raise

    def acquire(
        self, group: ArtifactLeaseGroup, source: ArtifactLease
    ) -> LeaseAcquireResult:
        """Create a new exact token for an already-live stored version."""
        return self._acquire(group, source)

    def _acquire(
        self,
        group: ArtifactLeaseGroup,
        source: ArtifactLease,
        recovery: list[ArtifactLease] | None = None,
    ) -> LeaseAcquireResult:
        """Acquire with an optional pre-armed exact-token recovery holder."""
        with self._lock:
            self._reconcile_group_mutation(group)
            error = self._validate_candidate(group)
            if error is not None:
                return LeaseAcquireResult(False, errors=(error,))
            if not self._valid_lease(source) or source._released:
                return LeaseAcquireResult(False, errors=("invalid_artifact_lease",))
            if self._charged_token_count() >= _MAX_TOKENS:
                return LeaseAcquireResult(False, errors=("artifact_lease_capacity_exceeded",))
            lease = self._new_token(group, source._version)
            if recovery is not None:
                recovery.append(lease)
            self._publish_token(lease)
            return LeaseAcquireResult(True, lease)

    def renew(
        self, group: ArtifactLeaseGroup, *, expires_at: float
    ) -> LeaseMutationResult:
        """Change a live candidate expiry without extending its birth cap."""
        if not valid_deadline(expires_at):
            return LeaseMutationResult(False, errors=("invalid_lease_argument",))
        with self._lock:
            error = self._validate_candidate(group)
            if error is not None:
                return LeaseMutationResult(False, errors=(error,))
            now = self._clock()
            if expires_at <= now or expires_at > group._birth + _CANDIDATE_TTL_SECONDS:
                return LeaseMutationResult(False, errors=("invalid_lease_argument",))
            group._expiry = expires_at
            return LeaseMutationResult(True)

    def release(self, lease: ArtifactLease) -> LeaseMutationResult:
        """Release one exact candidate token idempotently."""
        with self._lock:
            if not self._owned_lease(lease):
                return LeaseMutationResult(False, errors=("invalid_artifact_lease",))
            self._reconcile_group_mutation(lease._group)
            if not self._valid_lease(lease):
                return LeaseMutationResult(False, errors=("invalid_artifact_lease",))
            if lease._released:
                return LeaseMutationResult(True, already_settled=True)
            if lease._group._state not in ("candidate", "settled"):
                return LeaseMutationResult(False, errors=("invalid_execution_state",))
            lease._group._mutation = ("release", lease)
            self._reconcile_group_mutation(lease._group)
            return LeaseMutationResult(True)

    def release_group(self, group: ArtifactLeaseGroup) -> LeaseMutationResult:
        """Terminalize one candidate group without partial execution release."""
        with self._lock:
            if not self._owned_group(group):
                return LeaseMutationResult(False, errors=("invalid_lease_group",))
            self._reconcile_group_mutation(group)
            if group._terminal:
                return LeaseMutationResult(True, already_settled=True)
            if not self._valid_group(group):
                return LeaseMutationResult(False, errors=("invalid_lease_group",))
            if group._state == "staged":
                return LeaseMutationResult(False, errors=("artifact_lease_busy",))
            if group._state in ("admitted", "execution_debt", "active"):
                return LeaseMutationResult(False, errors=("invalid_execution_state",))
            self._settle_group_tokens(group, state="settled")
            return LeaseMutationResult(True)

    def admit(
        self,
        groups: tuple[ArtifactLeaseGroup, ...],
        recovery: list[ArtifactLeaseGroup] | None = None,
    ) -> LeaseGroupResult:
        """Create one admitted group with one token per distinct version union."""
        if type(groups) is not tuple:
            return LeaseGroupResult(False, errors=("invalid_lease_argument",))
        with self._lock:
            if self._state != "open":
                return LeaseGroupResult(False, errors=("artifact_lease_manager_closed",))
            if self._publication_stage is not None:
                return LeaseGroupResult(False, errors=("artifact_lease_busy",))
            if not groups or any(
                not self._valid_group(item) or item._state != "active"
                for item in groups
            ):
                return LeaseGroupResult(False, errors=("invalid_lease_group",))
            if any(item._mutation is not None for item in groups):
                return LeaseGroupResult(False, errors=("artifact_lease_busy",))
            by_sequence = {
                self._tokens[token]._version.sequence: self._tokens[token]._version
                for item in groups
                for token in item._tokens
            }
            versions = tuple(by_sequence[key] for key in sorted(by_sequence))
            if len(self._groups) >= _MAX_GROUPS or self._charged_token_count() + len(versions) > _MAX_TOKENS:
                return LeaseGroupResult(False, errors=("artifact_lease_capacity_exceeded",))
            result = self._new_group(
                "admitted", float("inf"), recovery=recovery
            )
            for version in versions:
                self._publish_token(self._new_token(result, version))
            return LeaseGroupResult(True, result)

    def retire(self, group: ArtifactLeaseGroup) -> LeaseMutationResult:
        """Remove one active root while preserving already admitted groups."""
        with self._lock:
            if not self._owned_group(group):
                return LeaseMutationResult(False, errors=("invalid_lease_group",))
            self._reconcile_group_mutation(group)
            if group._state == "retired" and group._terminal:
                return LeaseMutationResult(True, already_settled=True)
            if not self._valid_group(group):
                return LeaseMutationResult(False, errors=("invalid_lease_group",))
            stage = self._publication_stage
            if stage is not None and any(
                root is group
                for image in (stage._expected, stage._replacement)
                for root in image.lease_roots
            ):
                return LeaseMutationResult(False, errors=("artifact_lease_busy",))
            if group._state != "active":
                return LeaseMutationResult(False, errors=("invalid_execution_state",))
            self._settle_group_tokens(group, state="retired")
            return LeaseMutationResult(True)

    def reclaim(
        self, *, deadline: float, max_versions: int = 16, pressure: bool = False
    ) -> LeaseReclaimResult:
        """Attempt bounded zero-reference slot passes between deadline checks."""
        if not valid_deadline(deadline) or not valid_reclaim_limit(max_versions) or type(pressure) is not bool:
            return LeaseReclaimResult(False, errors=("invalid_lease_argument",))
        if self._clock() >= deadline:
            return LeaseReclaimResult(False, cleanup_pending=self._cleanup_pending(), errors=("artifact_lease_timeout",))
        physical_owner = object()
        try:
            if not self._physical.acquire(blocking=False, owner=physical_owner):
                return LeaseReclaimResult(False, cleanup_pending=True, errors=("artifact_lease_busy",))
            examined = removed = 0
            timeout = False
            for version in self._eligible_versions(pressure)[:max_versions]:
                if self._clock() >= deadline:
                    timeout = True
                    break
                examined += 1
                result = self._owner.dispose(version.artifact)
                if not result.cleanup_pending:
                    with self._lock:
                        self._versions.pop(id(version.artifact), None)
                    removed += 1
                else:
                    version.cleanup_pending = True
                if self._clock() >= deadline:
                    timeout = bool(self._eligible_versions(pressure))
                    break
            if not timeout:
                for debt in self._owner.cleanup_debts()[: max_versions - examined]:
                    if self._clock() >= deadline:
                        timeout = True
                        break
                    examined += 1
                    if self._owner.retry_cleanup(debt.debt_id):
                        removed += 1
                    if self._clock() >= deadline:
                        timeout = bool(self._owner.cleanup_debts())
                        break
        finally:
            self._physical.release_if_owned(physical_owner)
        pending = self._cleanup_pending()
        if self._state == "closing" and not pending and not self._groups and self._receipt is None:
            self._state = "closed"
        if timeout:
            return LeaseReclaimResult(False, examined, removed, pending, ("artifact_lease_timeout",))
        errors = ("artifact_cleanup_pending",) if pending else ()
        return LeaseReclaimResult(True, examined, removed, pending, errors)

    def retry_cleanup(
        self, debt: ArtifactLeaseDebt, *, deadline: float
    ) -> LeaseReclaimResult:
        """Retry one exact manager-issued debt idempotently."""
        if type(debt) is not ArtifactLeaseDebt or debt._manager is not self:
            return LeaseReclaimResult(False, errors=("invalid_cleanup_debt",))
        if debt._settled:
            return LeaseReclaimResult(True)
        with self._lock:
            if self._cleanup_debt_views.get(debt.debt_id) is not debt:
                return LeaseReclaimResult(False, errors=("invalid_cleanup_debt",))
        result = self.reclaim(deadline=deadline, max_versions=16, pressure=True)
        current_ids = {item.debt_id for item in self._owner.cleanup_debts()}
        if debt.debt_id not in current_ids:
            debt._settled = True
            with self._lock:
                self._cleanup_debt_views.pop(debt.debt_id, None)
        return result

    def close(self, *, deadline: float) -> LeaseReclaimResult:
        """Logically close once and schedule bounded physical cleanup."""
        if not valid_deadline(deadline):
            return LeaseReclaimResult(False, errors=("invalid_lease_argument",))
        with self._lock:
            if self._publication_stage is not None:
                return LeaseReclaimResult(
                    False, cleanup_pending=True, errors=("artifact_lease_busy",)
                )
            self._close_deadline = deadline if self._close_deadline is None else min(self._close_deadline, deadline)
            self._state = "closing" if self._state != "closed" else "closed"
            for group in tuple(self._groups.values()):
                self._reconcile_group_mutation(group)
                if self._valid_group(group) and group._state in ("candidate", "active"):
                    self._settle_group_tokens(group, state="retired")
            budget = self._close_deadline
        return self.reclaim(deadline=budget, pressure=True)

    def snapshot(self) -> ArtifactLeaseSnapshot:
        """Return bounded counts without reversing owner-to-manager lock order."""
        with self._owner._lock:
            owner_debts = self._owner.cleanup_debts()
            slots = tuple(self._owner._slots.values())
            capture_slots = len(slots)
            reserved_entries = sum(slot.reserved_entries for slot in slots)
            reserved_bytes = sum(slot.reserved_bytes for slot in slots)
        with self._lock:
            current_ids = {item.debt_id for item in owner_debts}
            for debt_id, debt in tuple(self._cleanup_debt_views.items()):
                if debt_id not in current_ids:
                    debt._settled = True
                    self._cleanup_debt_views.pop(debt_id, None)
            debts = []
            for item in owner_debts:
                debt = self._cleanup_debt_views.get(item.debt_id)
                if debt is None:
                    debt = ArtifactLeaseDebt(item.debt_id, item.category)
                    debt._manager = self
                    self._cleanup_debt_views[item.debt_id] = debt
                debts.append(debt)
            states = tuple(group._state for group in self._groups.values())
            versions = tuple(self._versions.values())
            return ArtifactLeaseSnapshot(
                self._state,
                sum(item in ("candidate", "staged") for item in states),
                states.count("active"), states.count("admitted"),
                states.count("execution_debt"), len(self._tokens),
                int(self._receipt is not None and self._receipt._reserved_token),
                capture_slots, reserved_entries, reserved_bytes,
                len(versions), int(self._receipt is not None and self._receipt._reserved_version),
                sum(item.artifact.total_bytes for item in versions),
                sum(item.retired_at is not None for item in versions),
                int(self._receipt is not None), int(self._publication_stage is not None),
                tuple(debts),
            )

    def recovery(self) -> ManagedArtifactRecovery:
        """Return the stable restricted recovery facade."""
        return self._recovery

    def _execution_port(self) -> ExecutionLeasePort:
        """Return the stable trusted framework settlement capability."""
        return self._execution

    def _attach_recovery(self, error: BaseException) -> None:
        """Attach only the restricted facade without changing error identity."""
        try:
            setattr(error, "_topsailai_artifact_lease_recovery", self._recovery)
        except BaseException:
            pass


    def _new_capture_receipt(self) -> CaptureReceipt:
        """Create one private receipt for the receipt transition mixin."""
        return CaptureReceipt(_ISSUER)

    def _new_version(self, artifact: CapturedArtifact) -> _Version:
        """Create one sequenced version for an adopted receipt artifact."""
        version = _Version(artifact, self._next_version)
        self._next_version += 1
        return version

    def _new_token(
        self, group: ArtifactLeaseGroup, version: _Version
    ) -> ArtifactLease:
        """Create and pre-arm one exact token before registry publication."""
        lease = ArtifactLease(_ISSUER)
        lease._issuer = self._execution_identity
        lease._manager = self
        lease._token_id = self._next_token
        lease._group = group
        lease._version = version
        lease._released = False
        self._next_token += 1
        return lease


    def _retain_for_cleanup(self, port, group) -> LeaseMutationResult:
        """Transfer the exact whole admitted union into execution debt."""
        with self._lock:
            if not self._valid_port(port) or not self._valid_group(group):
                return LeaseMutationResult(False, errors=("invalid_execution_state",))
            self._reconcile_group_mutation(group)
            if group._state == "execution_debt":
                return LeaseMutationResult(True, already_settled=True)
            if group._state != "admitted":
                return LeaseMutationResult(False, errors=("invalid_execution_state",))
            group._state = "execution_debt"
            return LeaseMutationResult(True)

    def _settle_execution(self, port, group) -> LeaseMutationResult:
        """Settle one whole admitted/debt group idempotently and recoverably."""
        with self._lock:
            if not self._valid_port(port) or not self._owned_group(group):
                return LeaseMutationResult(False, errors=("invalid_execution_state",))
            self._reconcile_group_mutation(group)
            if group._terminal:
                return LeaseMutationResult(True, already_settled=True)
            if not self._valid_group(group) or group._state not in (
                "admitted", "execution_debt"
            ):
                return LeaseMutationResult(False, errors=("invalid_execution_state",))
            self._settle_group_tokens(group, state="settled")
            return LeaseMutationResult(True)


    def _new_group(
        self,
        state: str,
        expiry: float,
        *,
        recovery: list[ArtifactLeaseGroup] | None = None,
    ) -> ArtifactLeaseGroup:
        """Create a charged group after optionally arming exact recovery."""
        group = ArtifactLeaseGroup(_ISSUER)
        group._issuer = self._execution_identity
        group._manager = self
        group._group_id = self._next_group
        group._state = state
        group._birth = self._clock()
        group._expiry = expiry
        group._tokens = set()
        group._pending_capture = False
        group._mutation = None
        group._terminal = False
        if recovery is not None:
            recovery.append(group)
        self._next_group += 1
        self._groups[group._group_id] = group
        return group

    def _validate_candidate(self, group) -> str | None:
        """Validate exact candidate liveness before mutation."""
        if not self._valid_group(group):
            return "invalid_lease_group"
        if self._state != "open":
            return "artifact_lease_manager_closed"
        if group._state != "candidate" or group._terminal:
            return "invalid_lease_group"
        if self._clock() >= group._expiry:
            return "artifact_candidate_expired"
        if group._pending_capture or group._mutation is not None:
            return "artifact_lease_busy"
        return None

    def _owned_group(self, group) -> bool:
        """Require exact issuer and manager without retaining terminal history."""
        return (
            isinstance(group, ArtifactLeaseGroup)
            and group._issuer is self._execution_identity
            and group._manager is self
        )

    def _valid_group(self, group) -> bool:
        """Require exact owner and the current live registry object."""
        return self._owned_group(group) and self._groups.get(group._group_id) is group

    def _owned_lease(self, lease) -> bool:
        """Require exact issuer and manager without trusting token membership."""
        return (
            isinstance(lease, ArtifactLease)
            and lease._issuer is self._execution_identity
            and lease._manager is self
        )

    def _valid_lease(self, lease) -> bool:
        """Require exact token object identity without numeric authority reuse."""
        return self._owned_lease(lease) and (
            lease._released or self._tokens.get(lease._token_id) is lease
        )

    def _valid_port(self, port) -> bool:
        """Require the one stable manager-bound execution capability."""
        return port is self._execution and port._identity is self._execution_identity


    def _eligible_versions(self, pressure: bool) -> tuple[_Version, ...]:
        """Select only zero-reference retained versions in deterministic order."""
        with self._lock:
            now = self._clock()
            values = tuple(
                item for item in self._versions.values()
                if not item.tokens and item.retired_at is not None
                and (pressure or now - item.retired_at >= _RETIRED_RETENTION_SECONDS)
            )
            return reclamation_order(values)

    def _cleanup_pending(self) -> bool:
        """Return whether physical, metadata, or execution obligations remain."""
        owner_pending = bool(self._owner.cleanup_debts())
        with self._lock:
            return bool(
                owner_pending
                or self._versions
                or self._receipt
                or any(
                    group._mutation is not None
                    or group._state in ("admitted", "execution_debt")
                    for group in self._groups.values()
                )
            )
