"""Resource-free custody admission and command mailbox. Author: DawsonLin.

No actor or resource mutation is enabled here. Command acknowledgement records
mailbox processing only, not resource settlement or producer ownership transfer.
Native release failure propagates and forbids using this operation as admission.
Interrupted finalizer entry carries the prearmed ticket for owner quarantine;
a held ticket is retained custody, not permission to retry an uncertain unlock.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import threading
import sys
import time
import uuid

from topsailai.hooks.cleanup_budget import finite_deadline
from topsailai.hooks.process_state import CleanupDebt


@dataclass(frozen=True, slots=True)
class CleanupMailboxHandle:
    """Retain lock-independent unavailable observation for one incarnation."""

    incarnation: str
    query_token: str
    unavailable_debt: CleanupDebt


@dataclass(frozen=True, slots=True)
class CleanupAdmissionReceipt:
    """Prepublish an exact pending slot without conveying resource authority."""

    incarnation: str
    slot_id: str
    generation: str
    pending_debt: CleanupDebt


@dataclass(frozen=True, slots=True)
class CleanupAdmissionIntent:
    """Prehold one exact logical operation before attempting admission."""

    receipt: CleanupAdmissionReceipt

    def __post_init__(self) -> None:
        """Reject receipt lookalikes before mailbox synchronization."""
        if type(self.receipt) is not CleanupAdmissionReceipt:
            raise ValueError("intent requires an exact admission receipt")


@dataclass(frozen=True, slots=True)
class CleanupAdmissionObservation:
    """Describe only one exact association, never backend resource absence."""

    state: str
    debts: tuple[CleanupDebt, ...]


@dataclass(frozen=True, slots=True)
class CleanupCommandProducerIntent:
    """Prehold one lifetime; identity is not repeat execution permission."""

    receipt: CleanupAdmissionReceipt

    def __post_init__(self) -> None:
        """Reject receipt lookalikes before synchronization."""
        if type(self.receipt) is not CleanupAdmissionReceipt:
            raise ValueError("producer requires an exact admission receipt")


@dataclass(frozen=True, slots=True)
class CleanupCommandSealIntent:
    """Prehold exact irreversible command closure before its commit."""

    receipt: CleanupAdmissionReceipt

    def __post_init__(self) -> None:
        """Reject receipt lookalikes before synchronization."""
        if type(self.receipt) is not CleanupAdmissionReceipt:
            raise ValueError("seal requires an exact admission receipt")


@dataclass(frozen=True, slots=True)
class CleanupCommandObservation:
    """Describe metadata custody, not settlement or freed capacity."""

    state: str
    intent: CleanupCommandProducerIntent | CleanupCommandSealIntent
    debts: tuple[CleanupDebt, ...]


@dataclass(frozen=True, slots=True)
class CleanupCommand:
    """Request one observation tick using exact receipt and bounded sequence."""

    receipt: CleanupAdmissionReceipt
    sequence: int

    def __post_init__(self) -> None:
        """Reject lookalikes before mailbox synchronization."""
        if type(self.receipt) is not CleanupAdmissionReceipt:
            raise ValueError("command requires an exact admission receipt")
        if type(self.sequence) is not int or not 0 < self.sequence < 2**63:
            raise ValueError("command sequence must be a positive bounded integer")


@dataclass(frozen=True, slots=True)
class CleanupDeliveryReceipt:
    """Prehold exact consumer custody; sharing it never permits replay of work."""

    command: CleanupCommand

    def __post_init__(self) -> None:
        """Reject command lookalikes before entering mailbox synchronization."""
        if type(self.command) is not CleanupCommand:
            raise ValueError("delivery requires an exact CleanupCommand")


@dataclass(slots=True)
class _AcquisitionTicket:
    """Journal this caller's lock attempt, never another caller's authority."""

    handle: CleanupMailboxHandle
    state: str = "unattempted"


@dataclass(frozen=True, slots=True)
class CleanupDebtSnapshot:
    """Distinguish verified current inventory from unavailable observation."""

    state: str
    debts: tuple[CleanupDebt, ...]


@dataclass(frozen=True, slots=True)
class _Slot:
    """Keep one bounded command and its acknowledgement in immutable state."""

    receipt: CleanupAdmissionReceipt
    acknowledged: int = 0
    command: CleanupCommand | None = None
    delivery: CleanupDeliveryReceipt | None = None
    completed_delivery: CleanupDeliveryReceipt | None = None
    intent: CleanupAdmissionIntent | None = None
    producer: CleanupCommandProducerIntent | None = None
    producer_returned: bool = False
    seal: CleanupCommandSealIntent | None = None


class CleanupMailbox:
    """Store fixed-capacity pending slots using a single bounded lock attempt.

    Slots are never recycled in this increment: acknowledgement cannot release
    capacity without a later producer/reader/resource terminal protocol. No
    callback, resource I/O, condition wait or legacy resource lock is used.
    """

    def __init__(self, capacity: int) -> None:
        """Prepare immutable observation data before any admission is possible."""
        if type(capacity) is not int or not 0 < capacity <= 256:
            raise ValueError("mailbox capacity must be an integer in 1..256")
        incarnation = uuid.uuid4().hex
        token = "cleanup-query:" + incarnation
        self._handle = CleanupMailboxHandle(
            incarnation, token,
            CleanupDebt(token, "cleanup_query_unavailable", None,
                        "cleanup inventory unavailable"),
        )
        self._unavailable = CleanupDebtSnapshot(
            "unavailable", (self._handle.unavailable_debt,)
        )
        self._admission_unavailable = CleanupAdmissionObservation(
            "unavailable", self._unavailable.debts
        )
        self._catalog = tuple(self._catalog_receipt() for _ in range(capacity))
        self._capacity = capacity
        self._slots: tuple[_Slot, ...] = ()
        self._lock = threading.Lock()

    @property
    def handle(self) -> CleanupMailboxHandle:
        """Return construction-time immutable data without protected reads."""
        return self._handle

    def _catalog_receipt(self) -> CleanupAdmissionReceipt:
        """Construct a fixed resource-free identity before publishing the mailbox."""
        generation = uuid.uuid4().hex
        slot_id = "cleanup-slot:" + generation
        return CleanupAdmissionReceipt(
            self._handle.incarnation, slot_id, generation,
            CleanupDebt(slot_id, "admission_pending", None,
                        "cleanup admission remains pending"),
        )

    def prepare_admission(self, index: int) -> CleanupAdmissionReceipt:
        """Return a stable catalog identity without admission or mutable reads."""
        if type(index) is not int or not 0 <= index < len(self._catalog):
            raise ValueError("admission index must be an exact in-range integer")
        return self._catalog[index]

    def admit(self, intent: CleanupAdmissionIntent, *,
              deadline: float) -> CleanupAdmissionObservation:
        """Bind exact preheld intent and capacity once, without resource authority."""
        return self._admission_query(intent, deadline=deadline, admit=True)

    def admission_status(self, intent: CleanupAdmissionIntent, *,
                         deadline: float) -> CleanupAdmissionObservation:
        """Reconcile exact admission; absent is only point-in-time observation."""
        return self._admission_query(intent, deadline=deadline, admit=False)

    def _admission_query(self, intent: CleanupAdmissionIntent, *, deadline: float,
                         admit: bool) -> CleanupAdmissionObservation:
        """Protect bounded association checks and one atomic metadata commit."""
        if type(intent) is not CleanupAdmissionIntent:
            raise ValueError("expected an exact CleanupAdmissionIntent")
        if type(intent.receipt) is not CleanupAdmissionReceipt:
            raise ValueError("intent requires an exact admission receipt")
        end = finite_deadline(deadline)
        receipt = intent.receipt
        candidate = _Slot(receipt, intent=intent)
        pending = (receipt.pending_debt,)
        observations = {
            state: CleanupAdmissionObservation(state, debts)
            for state, debts in (("absent", ()), ("foreign", ()), ("full", ()),
                                 ("admitted", pending), ("conflict", pending))
        }
        ticket = _AcquisitionTicket(self._handle)
        result = self._admission_unavailable
        try:
            try:
                if self._acquire(end, ticket):
                    result = self._admission_locked(
                        intent, candidate, observations, end, admit
                    )
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise
        if time.monotonic() >= end:
            return self._admission_unavailable
        return result

    def _admission_locked(self, intent, candidate, observations, end, admit):
        """Use exact identity only under proven custody, with the original horizon."""
        if time.monotonic() >= end:
            return self._admission_unavailable
        receipt = intent.receipt
        if not any(item is receipt for item in self._catalog):
            return observations["foreign"]
        index = self._index(receipt)
        if index is not None:
            state = "admitted" if self._slots[index].intent is intent else "conflict"
            return observations[state]
        if not admit:
            return observations["absent"]
        if len(self._slots) >= self._capacity:
            return observations["full"]
        if time.monotonic() >= end:
            return self._admission_unavailable
        self._slots = self._slots + (candidate,)
        return observations["admitted"]

    def admit_command_producer(self, intent: CleanupCommandProducerIntent, *,
                               deadline: float) -> CleanupCommandObservation:
        """Admit one preheld lifetime before asynchronous command-producing work."""
        return self._command_query(intent, deadline, "admit")

    def command_producer_status(self, intent: CleanupCommandProducerIntent, *,
                                deadline: float) -> CleanupCommandObservation:
        """Reconcile exact lifetime without another execution grant."""
        return self._command_query(intent, deadline, "status")

    def handback_command_producer(self, intent: CleanupCommandProducerIntent, *,
                                 deadline: float) -> CleanupCommandObservation:
        """Record trusted cessation, never force handback of uncertain work."""
        return self._command_query(intent, deadline, "handback")

    def seal_commands(self, intent: CleanupCommandSealIntent, *,
                      deadline: float) -> CleanupCommandObservation:
        """Close admission permanently without discarding existing custody."""
        return self._command_query(intent, deadline, "seal")

    def command_quiescence(self, intent: CleanupCommandSealIntent, *,
                           deadline: float) -> CleanupCommandObservation:
        """Observe irreversible quiescence for the exact committed seal only."""
        return self._command_query(intent, deadline, "quiescence")

    def _command_query(self, intent, deadline, operation):
        """Prearm custody and recheck the same horizon after finalization."""
        expected = (CleanupCommandSealIntent if operation in ("seal", "quiescence")
                    else CleanupCommandProducerIntent)
        if type(intent) is not expected or type(intent.receipt) is not CleanupAdmissionReceipt:
            raise ValueError("expected an exact command intent and receipt")
        end = finite_deadline(deadline)
        unavailable = CleanupCommandObservation("unavailable", intent, self._unavailable.debts)
        ticket = _AcquisitionTicket(self._handle)
        result = unavailable
        try:
            try:
                if self._acquire(end, ticket):
                    result = self._command_locked(intent, operation, end, unavailable)
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise
        return unavailable if time.monotonic() >= end else result

    def _command_locked(self, intent, operation, end, unavailable):
        """Arbitrate exact identities and closure under one mailbox acquisition."""
        if time.monotonic() >= end:
            return unavailable
        index = self._index(intent.receipt)
        if index is None:
            return CleanupCommandObservation("foreign", intent, ())
        slot = self._slots[index]
        if operation in ("seal", "quiescence"):
            state, candidate = self._seal_candidate(slot, intent, operation)
        else:
            state, candidate = self._producer_candidate(slot, intent, operation)
        result = CleanupCommandObservation(state, intent, (slot.receipt.pending_debt,))
        if time.monotonic() >= end:
            return unavailable
        if candidate is not slot:
            self._publish(index, candidate)
        return result

    def _seal_candidate(self, slot, intent, operation):
        """Retain one winning seal and account for current command custody."""
        if slot.seal is not None and slot.seal is not intent:
            return "conflict", slot
        if slot.seal is None:
            if operation == "quiescence":
                return "open", slot
            slot = replace(slot, seal=intent)
        active = slot.producer is not None and not slot.producer_returned
        pending = active or slot.command is not None or slot.delivery is not None
        return ("sealed_pending" if pending else "quiescent"), slot

    def _producer_candidate(self, slot, intent, operation):
        """Retain the single lifetime tombstone without clearing command custody."""
        if slot.producer is not None:
            if slot.producer is not intent:
                return "conflict", slot
            if operation == "handback" and not slot.producer_returned:
                slot = replace(slot, producer_returned=True)
            return ("returned" if slot.producer_returned else "active"), slot
        if operation != "admit":
            return "absent", slot
        if slot.seal is not None:
            return "sealed", slot
        return "active", replace(slot, producer=intent)

    def _acquire(self, deadline: float, ticket: _AcquisitionTicket) -> bool:
        """Acquire inside the caller's armed finalizer and journal uncertainty."""
        end = finite_deadline(deadline)
        if time.monotonic() >= end:
            return False
        ticket.state = "acquiring"
        acquired = self._lock.acquire(blocking=False)
        ticket.state = "held" if acquired else "not_acquired"
        if not acquired:
            return False
        return time.monotonic() < end

    def _finish(self, ticket: _AcquisitionTicket) -> None:
        """Release proven custody only; expose uncertainty on the host exception.

        An acquiring/releasing ticket is NOT permission to retry a native unlock.
        The caller must quarantine this mailbox before further use when such a
        ticket is attached (including held custody after interrupted entry).
        No shared poison flag or unlocked inventory read is
        used. Repeated interruption of finalization is outside cooperative bounds.
        """
        primary = sys.exception()
        try:
            if ticket.state == "held":
                ticket.state = "releasing"
                self._lock.release()
                ticket.state = "released"
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            if primary is None:
                raise
            primary.cleanup_mailbox_ticket = ticket
            primary.cleanup_mailbox_release_error = error
        finally:
            if primary is not None and ticket.state in ("acquiring", "releasing"):
                primary.cleanup_mailbox_ticket = ticket

    def _index(self, receipt: CleanupAdmissionReceipt) -> int | None:
        """Locate exact receipt identity only while holding the mailbox lock."""
        for index, slot in enumerate(self._slots):
            if slot.receipt is receipt:
                return index
        return None

    def _publish(self, index: int, slot: _Slot) -> None:
        """Commit one immutable slot replacement as a single table assignment."""
        self._slots = self._slots[:index] + (slot,) + self._slots[index + 1:]

    def reserve(self, *, deadline: float) -> CleanupAdmissionReceipt | None:
        """Arm a pending receipt before callers may allocate any resources."""
        end = finite_deadline(deadline)
        generation = uuid.uuid4().hex
        slot_id = "cleanup-slot:" + generation
        receipt = CleanupAdmissionReceipt(
            self._handle.incarnation, slot_id, generation,
            CleanupDebt(slot_id, "admission_pending", None,
                        "cleanup admission remains pending"),
        )
        slot = _Slot(receipt)
        ticket = _AcquisitionTicket(self._handle)
        try:
            try:
                if not self._acquire(end, ticket):
                    return None
                if len(self._slots) >= self._capacity:
                    return None
                self._slots = self._slots + (slot,)
                return receipt
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise

    def snapshot(self, *, deadline: float) -> CleanupDebtSnapshot:
        """Return immutable tuple debt or the preconstructed unavailable marker."""
        ticket = _AcquisitionTicket(self._handle)
        try:
            try:
                if not self._acquire(deadline, ticket):
                    return self._unavailable
                return CleanupDebtSnapshot(
                    "current", tuple(slot.receipt.pending_debt for slot in self._slots)
                )
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise

    def submit(self, command: CleanupCommand, *, deadline: float) -> str:
        """Publish one command; explicit sealing takes precedence over history."""
        if type(command) is not CleanupCommand:
            raise ValueError("expected an exact CleanupCommand")
        end = finite_deadline(deadline)
        ticket = _AcquisitionTicket(self._handle)
        result = "unavailable"
        try:
            try:
                if self._acquire(end, ticket):
                    result = self._submit_locked(command, end)
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise
        return "unavailable" if time.monotonic() >= end else result

    def _submit_locked(self, command, end):
        """Linearize admission and seal with a final absolute-horizon check."""
        if time.monotonic() >= end:
            return "unavailable"
        index = self._index(command.receipt)
        if index is None:
            return "foreign"
        slot = self._slots[index]
        if slot.seal is not None:
            return "sealed"
        if command.sequence < slot.acknowledged:
            return "stale"
        if command.sequence == slot.acknowledged:
            return "duplicate"
        if slot.command is not None:
            return "duplicate" if command.sequence == slot.command.sequence else "busy"
        if command.sequence != slot.acknowledged + 1:
            return "stale"
        candidate = replace(slot, command=command, delivery=None)
        if time.monotonic() >= end:
            return "unavailable"
        self._publish(index, candidate)
        return "accepted"

    def take(self, receipt: CleanupAdmissionReceipt, *,
             delivery: CleanupDeliveryReceipt, deadline: float) -> CleanupCommand | None:
        """Commit a preheld consumer receipt; interrupted return is reconcilable.

        The consumer retains delivery.command before calling and journals its own
        work-start separately. A taken receipt authorizes first delivery only,
        never repeated work after an uncertain consumer action.
        """
        if type(receipt) is not CleanupAdmissionReceipt:
            raise ValueError("expected an exact admission receipt")
        if type(delivery) is not CleanupDeliveryReceipt:
            raise ValueError("expected an exact delivery receipt")
        ticket = _AcquisitionTicket(self._handle)
        try:
            try:
                if not self._acquire(deadline, ticket):
                    return None
                index = self._index(receipt)
                if index is None:
                    return None
                slot = self._slots[index]
                if slot.command is not delivery.command or slot.delivery is not None:
                    return None
                self._publish(index, replace(slot, delivery=delivery))
                return slot.command
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise

    def acknowledge(self, command: CleanupCommand, *,
                    delivery: CleanupDeliveryReceipt, deadline: float) -> str:
        """Commit exact taken-command completion, never resource settlement."""
        if type(command) is not CleanupCommand:
            raise ValueError("expected an exact CleanupCommand")
        if type(delivery) is not CleanupDeliveryReceipt:
            raise ValueError("expected an exact delivery receipt")
        ticket = _AcquisitionTicket(self._handle)
        try:
            try:
                if not self._acquire(deadline, ticket):
                    return "unavailable"
                index = self._index(command.receipt)
                if index is None:
                    return "foreign"
                slot = self._slots[index]
                if command.sequence == slot.acknowledged:
                    return "duplicate" if (slot.completed_delivery is delivery
                                           and delivery.command is command) else "foreign"
                if slot.command is not command:
                    return "foreign"
                if slot.delivery is None:
                    return "not_started"
                if slot.delivery is not delivery or delivery.command is not command:
                    return "foreign"
                self._publish(index, replace(
                    slot, acknowledged=command.sequence, command=None, delivery=None,
                    completed_delivery=delivery,
                ))
                return "acknowledged"
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise

    def observe(self, receipt: CleanupAdmissionReceipt, *, deadline: float) -> int | None:
        """Observe committed sequence; unavailable or foreign never means absent."""
        if type(receipt) is not CleanupAdmissionReceipt:
            raise ValueError("expected an exact admission receipt")
        ticket = _AcquisitionTicket(self._handle)
        try:
            try:
                if not self._acquire(deadline, ticket):
                    return None
                index = self._index(receipt)
                return None if index is None else self._slots[index].acknowledged
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise

    def delivery_status(self, delivery: CleanupDeliveryReceipt, *, deadline: float) -> str:
        """Reconcile exact delivery/ack commits without taking or executing again.

        Only the latest completion is retained; older receipts are foreign, not
        evidence of settlement. Unavailable means STOP, not permission to replay.
        """
        if type(delivery) is not CleanupDeliveryReceipt:
            raise ValueError("expected an exact delivery receipt")
        ticket = _AcquisitionTicket(self._handle)
        try:
            try:
                if not self._acquire(deadline, ticket):
                    return "unavailable"
                index = self._index(delivery.command.receipt)
                if index is None:
                    return "foreign"
                slot = self._slots[index]
                if slot.completed_delivery is delivery:
                    return "acknowledged"
                if slot.delivery is delivery:
                    return "taken"
                if slot.command is delivery.command and slot.delivery is None:
                    return "ready"
                return "foreign"
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_mailbox_ticket = ticket
            raise
