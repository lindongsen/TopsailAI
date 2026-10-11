"""Bounded Runtime-local publication recovery. Author: DawsonLin."""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from topsailai.hooks.artifact_contracts import ArtifactDisposeResult
from topsailai.hooks.process_state import CleanupDebt
from topsailai.hooks.hook_point_plan_ownership import HookPointCandidate


@dataclass(frozen=True, slots=True)
class PublicationReservation:
    """Identify one exact reserved recovery slot without transferable authority."""
    debt_id: str


class PublicationRecovery:
    """Retain unresolved owners under the existing Runtime lock until safe disposal."""
    def __init__(self, lock, capacity=128):
        """Create a finite journal before any candidate resource mutation."""
        if type(capacity) is not int or not 0 < capacity <= 128:
            raise ValueError("invalid publication recovery capacity")
        self._lock = lock
        self._capacity = capacity
        self._entries = {}
        self._busy = set()

    @property
    def capacity(self):
        """Expose the fixed bound without granting journal mutation authority."""
        return self._capacity

    def reserve(self, receiver=None):
        """Prearm caller recovery before publishing an empty journal reservation."""
        with self._lock:
            if len(self._entries) >= self._capacity:
                return None
            ticket = PublicationReservation("publication-" + uuid.uuid4().hex)
            if receiver is not None:
                receiver.append(ticket)
            self._entries[id(ticket)] = (ticket, None)
            return ticket

    def reserve_deferred(self, owner, registry):
        """Arm exact owner custody in one journal mutation before returning authority."""
        with self._lock:
            for ticket, current in self._entries.values():
                if current is owner:
                    return ticket
            if len(self._entries) >= self._capacity:
                return None
            ticket = PublicationReservation("publication-" + uuid.uuid4().hex)
            self._entries[id(ticket)] = (ticket, owner)
            return ticket

    def bind(self, ticket, owner):
        """Attach exactly one owner while retaining the original reservation."""
        with self._lock:
            entry = self._entries.get(id(ticket))
            if entry is None or entry[0] is not ticket or entry[1] is not None:
                return False
            if owner is None:
                return False
            self._entries[id(ticket)] = (ticket, owner)
            return True

    def release(self, ticket):
        """Withdraw only an exact empty reservation, never unresolved ownership."""
        with self._lock:
            entry = self._entries.get(id(ticket))
            if entry is None or entry[0] is not ticket or entry[1] is not None:
                return False
            del self._entries[id(ticket)]
            return True

    def handoff(self, ticket):
        """Withdraw candidate recovery after exact Registry ownership is committed."""
        with self._lock:
            entry = self._entries.get(id(ticket))
            if entry is None or entry[0] is not ticket or id(ticket) in self._busy:
                return False
            del self._entries[id(ticket)]
            return True

    def _claim(self, ticket):
        """Check deferred authority without reversing Registry/journal lock order."""
        with self._lock:
            entry = self._entries.get(id(ticket))
            if entry is None or entry[0] is not ticket or entry[1] is None:
                return None
            owner = entry[1]
        registry = getattr(owner, "_registry", None)
        if registry is not None and (registry.owns_deferred_owner(owner)
                                     or registry.owns_hook_point_owner(owner)):
            return None
        with self._lock:
            current = self._entries.get(id(ticket))
            if current is not entry or id(ticket) in self._busy:
                return None
            self._busy.add(id(ticket))
            return owner

    def _dispose(self, ticket, owner, debt_id=None):
        """Preserve custody through interruption and remove only confirmed settlement."""
        try:
            resource = owner
            if type(owner) is HookPointCandidate and owner._publication_owner is not None:
                resource = owner._publication_owner
                if resource._registry.owns_hook_point_owner(resource):
                    with self._lock:
                        entry = self._entries.get(id(ticket))
                        if entry is not None and entry[0] is ticket and entry[1] is owner:
                            del self._entries[id(ticket)]
                    return True
            if debt_id is not None and debt_id != ticket.debt_id:
                if not resource.retry_cleanup(debt_id):
                    return False
            operation = getattr(resource, "retire", None)
            result = resource.close() if operation is None else operation()
            settled = result.accepted and not result.cleanup_pending
            if settled:
                with self._lock:
                    entry = self._entries.get(id(ticket))
                    if entry is not None and entry[0] is ticket and entry[1] is owner:
                        del self._entries[id(ticket)]
            return settled
        finally:
            with self._lock:
                self._busy.discard(id(ticket))

    def settle(self, ticket):
        """Attempt disposal outside Runtime locks and retain any failure for retry."""
        owner = self._claim(ticket)
        return False if owner is None else self._dispose(ticket, owner)

    def cleanup_debts(self):
        """Inspect a bounded detached journal outside the Runtime lock."""
        with self._lock:
            entries = tuple(self._entries.values())
        debts = []
        for ticket, owner in entries:
            if owner is None:
                continue
            if getattr(owner, "settled", False):
                with self._lock:
                    entry = self._entries.get(id(ticket))
                    if entry is not None and entry[0] is ticket and entry[1] is owner:
                        del self._entries[id(ticket)]
                continue
            observed = owner.cleanup_debts()
            debts.extend(observed or (CleanupDebt(ticket.debt_id,
                "publication_pending", None, "publication ownership retained"),))
        return tuple(debts)

    def owns_debt(self, debt_id):
        """Check bounded exact custody before a shared backend handles the same debt."""
        with self._lock:
            entries = tuple(self._entries.values())
        return any(owner is not None and (
            ticket.debt_id == debt_id or any(
                debt.debt_id == debt_id for debt in owner.cleanup_debts()))
            for ticket, owner in entries)

    def retry_cleanup(self, debt_id):
        """Retry one exact selected debt, never sweep unrelated owners."""
        if type(debt_id) is not str:
            return False
        with self._lock:
            entries = tuple(self._entries.values())
        for ticket, owner in entries:
            if owner is None:
                continue
            matches = debt_id == ticket.debt_id or any(
                debt.debt_id == debt_id for debt in owner.cleanup_debts())
            if matches:
                claimed = self._claim(ticket)
                return False if claimed is None else self._dispose(ticket, claimed, debt_id)
        return False


class ExecutionCleanupCustody:
    """Keep a captured plan alive independently of a completed dispatch reader."""
    def __init__(self, registry, token):
        """Arm the exact cleanup token before constructing or invoking a runner."""
        self.registry = registry
        self.token = token
        self.runner = None
        self.completed = False
        self.settled = False

    def cleanup_debts(self):
        """Observe only this execution's runner obligations after execution stops."""
        if not self.completed or self.runner is None:
            return ()
        return self.runner.cleanup_debts()

    def retry_cleanup(self, debt_id):
        """Retry the selected exact runner debt without touching other executions."""
        if not self.completed or self.runner is None:
            return False
        if not any(debt.debt_id == debt_id for debt in self.runner.cleanup_debts()):
            return False
        return self.runner.retry_cleanup(debt_id)

    def close(self):
        """Release captured-byte custody only after every execution obligation settles."""
        if self.settled:
            return ArtifactDisposeResult(True, True)
        if not self.completed or self.cleanup_debts():
            return ArtifactDisposeResult(False, False, True, ("execution_cleanup_pending",))
        self.registry.release_hook_point_cleanup(self.token)
        self.settled = True
        return ArtifactDisposeResult(True)
