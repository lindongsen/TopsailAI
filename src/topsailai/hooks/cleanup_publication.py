"""Resource-free exact custody publication journal. Author: DawsonLin.

No backend, actor, resource callback or mutable LaunchRecord field is used.
Receipts describe synthetic metadata authority only until reviewed integration.
Capacity and terminal tombstones are retained; ambiguous lock custody requires
caller quarantine, never a guessed unlock or another mutation owner.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import sys
import threading
import time
import uuid

from topsailai.hooks.cleanup_budget import CleanupBudget, finite_deadline
from topsailai.hooks.cleanup_mailbox import (
    CleanupAdmissionIntent, CleanupAdmissionReceipt, CleanupDeliveryReceipt,
    CleanupMailbox, CleanupCommandSealIntent,
)
from topsailai.hooks.process_state import CleanupDebt, LaunchRecord

ACTIONS = (
    "owner_admit", "admission_handback", "start", "resources", "transfer", "producer_handback",
    "reader_grant", "reader_handback", "settle", "terminal", "never_started",
)


@dataclass(frozen=True, slots=True)
class PublicationHandle:
    """Bind one immutable backend incarnation/profile and unavailable debt."""

    incarnation: str
    backend: object
    profile: str
    cleanup_owner: object
    unavailable_debt: CleanupDebt


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """Prehold an original fixed slot and its exact mailbox identity."""

    handle: PublicationHandle
    generation: str
    admission: CleanupAdmissionReceipt


@dataclass(frozen=True, slots=True)
class PublicationIntent:
    """Retain exact record and caller identities before both publication commits."""

    receipt: PublicationReceipt
    admission: CleanupAdmissionIntent
    record: LaunchRecord
    debt_id: str
    owner: object
    producer: object
    budget: CleanupBudget

    def __post_init__(self):
        """Validate shapes without inspecting mutable record fields."""
        if (type(self.receipt) is not PublicationReceipt
                or type(self.admission) is not CleanupAdmissionIntent
                or self.admission.receipt is not self.receipt.admission
                or type(self.record) is not LaunchRecord
                or type(self.budget) is not CleanupBudget):
            raise ValueError("publication requires exact typed identities")
        if type(self.debt_id) is not str or not 0 < len(self.debt_id) <= 128:
            raise ValueError("publication debt ID must be a bounded nonempty string")
        if type(self.owner) is not object or type(self.producer) is not object:
            raise ValueError("owner and producer must be exact opaque object tokens")
        if self.owner is self.producer:
            raise ValueError("owner and producer must be distinct tokens")


@dataclass(frozen=True, slots=True)
class PublicationAction:
    """Prehold one exact transition; duplicate receipt is not a fresh work grant."""

    intent: PublicationIntent
    name: str
    actor: object
    delivery: CleanupDeliveryReceipt | None = None
    command_seal: CleanupCommandSealIntent | None = None

    def __post_init__(self):
        """Reject lookalikes and unknown actions before synchronization."""
        if type(self.intent) is not PublicationIntent:
            raise ValueError("action requires exact publication intent")
        if type(self.name) is not str or self.name not in ACTIONS:
            raise ValueError("unknown publication action")
        if type(self.actor) is not object:
            raise ValueError("action requires exact opaque actor token")
        if self.delivery is not None and type(self.delivery) is not CleanupDeliveryReceipt:
            raise ValueError("action requires exact delivery evidence")
        if self.delivery is not None and self.name != "terminal":
            raise ValueError("delivery evidence belongs only to terminal action")
        if self.command_seal is not None:
            if (type(self.command_seal) is not CleanupCommandSealIntent
                    or self.name not in ("terminal", "never_started")):
                raise ValueError("command seal belongs only to retirement actions")


@dataclass(frozen=True, slots=True)
class RetirementIntent:
    """Prehold original synthetic authority before acquisition can start."""

    publication: PublicationIntent
    producer: object
    cleanup_owner: object
    command_seal: CleanupCommandSealIntent

    def __post_init__(self):
        """Reject malformed certificates before any synchronization."""
        if (type(self.publication) is not PublicationIntent
                or type(self.producer) is not object
                or type(self.cleanup_owner) is not object
                or type(self.command_seal) is not CleanupCommandSealIntent):
            raise ValueError("retirement requires exact typed identities")


@dataclass(frozen=True, slots=True)
class RetirementEvidence:
    """Certify synthetic cessation/zero obligations, never native settlement."""

    intent: RetirementIntent
    kind: str
    delivery: CleanupDeliveryReceipt | None = None

    def __post_init__(self):
        """Validate shape; identity and lifecycle are checked against the journal."""
        if type(self.intent) is not RetirementIntent:
            raise ValueError("retirement requires an exact intent")
        if type(self.kind) is not str or self.kind not in ("empty_failure", "settled_no_reader"):
            raise ValueError("unknown retirement kind")
        if self.delivery is not None and type(self.delivery) is not CleanupDeliveryReceipt:
            raise ValueError("retirement requires exact delivery evidence")
        if self.kind == "empty_failure" and self.delivery is not None:
            raise ValueError("empty failure must not fabricate a delivery")


@dataclass(frozen=True, slots=True)
class PublicationState:
    """Detach lifecycle facts; never expose mutable record fields as authority."""

    intent: PublicationIntent
    stage: str = "pending"
    admission_producers: int = 1
    producers: int = 1
    readers: int = 0
    owner_admitted: bool = False
    mutation_owner: object | None = None
    actions: tuple[PublicationAction, ...] = ()
    retirement: RetirementEvidence | None = None


@dataclass(frozen=True, slots=True)
class PublicationObservation:
    """Keep unavailable and owner-scoped pending obligations distinct from absence."""

    state: str
    entries: tuple[PublicationState, ...]
    debts: tuple[CleanupDebt, ...]


@dataclass(slots=True)
class _Ticket:
    """Retain this exact metadata acquisition attempt across interruption."""

    handle: PublicationHandle
    state: str = "unattempted"


class CleanupPublication:
    """Bound association and transition metadata with one nonblocking acquisition.

    Public mailbox operations run only outside this journal's lock. Joining is
    monotonic, not a pretend two-lock transaction. Reconciliation never retries
    an ambiguous admission or grants resources from an absent mailbox result.
    """

    def __init__(self, mailbox: CleanupMailbox, capacity: int, *, backend: object,
                 profile: str, cleanup_owner: object):
        """Build fixed identities without mutable preparation or resource issuance."""
        if type(mailbox) is not CleanupMailbox:
            raise ValueError("journal requires an exact CleanupMailbox")
        if type(capacity) is not int or not 0 < capacity <= 256:
            raise ValueError("journal capacity must be in 1..256")
        if type(profile) is not str or profile != "custodian_v1":
            raise ValueError("journal supports only isolated custodian_v1 metadata")
        if type(backend) is not object or type(cleanup_owner) is not object:
            raise ValueError("backend and cleanup owner require opaque tokens")
        incarnation = uuid.uuid4().hex
        self._handle = PublicationHandle(
            incarnation, backend, profile, cleanup_owner,
            CleanupDebt("cleanup-query:" + incarnation, "cleanup_query_unavailable",
                        None, "publication inventory unavailable"),
        )
        self._catalog = tuple(PublicationReceipt(
            self._handle, uuid.uuid4().hex, mailbox.prepare_admission(index)
        ) for index in range(capacity))
        self._mailbox = mailbox
        self._slots: tuple[PublicationState, ...] = ()
        self._sealed = False
        self._lock = threading.Lock()
        self._unavailable = PublicationObservation(
            "unavailable", (), (self._handle.unavailable_debt,)
        )

    @property
    def handle(self):
        """Return immutable unavailable authority without protected inventory."""
        return self._handle

    def prepare(self, index: int) -> PublicationReceipt:
        """Return the same fixed identity without issuance or capacity mutation."""
        if type(index) is not int or not 0 <= index < len(self._catalog):
            raise ValueError("publication index must be exact and in range")
        return self._catalog[index]

    def publish(self, intent: PublicationIntent, *, deadline: float):
        """Prepublish custody then attempt mailbox admission once, without nesting."""
        result = self._query("publish", intent, None, deadline)
        if result.state != "published":
            return result
        end = finite_deadline(deadline)
        if time.monotonic() >= end:
            return self._unavailable
        admitted = self._mailbox.admit(intent.admission, deadline=end)
        if admitted.state != "admitted":
            return self._query("observe", intent, None, end)
        return self._query("join", intent, None, end)

    def reconcile(self, intent: PublicationIntent, *, deadline: float):
        """Observe the exact admission; never repeat an ambiguous admission call."""
        result = self._query("observe", intent, None, deadline)
        if result.state != "pending":
            return result
        end = finite_deadline(deadline)
        if time.monotonic() >= end:
            return self._unavailable
        status = self._mailbox.admission_status(intent.admission, deadline=end)
        if status.state == "unavailable":
            return self._unavailable
        if status.state != "admitted":
            return result if time.monotonic() < end else self._unavailable
        return self._query("join", intent, None, end)

    def observe(self, intent: PublicationIntent, *, deadline: float):
        """Inspect current exact association without claiming backend emptiness."""
        return self._query("observe", intent, None, deadline)

    def snapshot(self, owner: object, *, deadline: float):
        """Return only the exact owner's entries, including partial joins."""
        if type(owner) is not object:
            raise ValueError("snapshot requires an exact owner token")
        return self._query("snapshot", None, owner, deadline)

    def seal(self, *, deadline: float):
        """Reject new publication/start while retaining late handback authority."""
        return self._query("seal", None, None, deadline)

    def transition(self, action: PublicationAction, *, deadline: float):
        """Commit explicit synthetic lifecycle evidence, never resource execution."""
        if type(action) is not PublicationAction:
            raise ValueError("transition requires an exact PublicationAction")
        end = finite_deadline(deadline)
        if action.name == "start":
            end = min(end, action.intent.budget.execution_deadline)
        if action.name in ("terminal", "never_started") and action.command_seal is not None:
            if action.command_seal.receipt is not action.intent.receipt.admission:
                return self._query("observe", action.intent, None, end)
            status = self._mailbox.command_quiescence(action.command_seal, deadline=end)
            if status.state != "quiescent":
                return self._unavailable if status.state == "unavailable" else self._query(
                    "observe", action.intent, None, end
                )
        if action.name == "terminal" and action.delivery is not None:
            if action.delivery.command.receipt is not action.intent.receipt.admission:
                return self._query("observe", action.intent, None, end)
            status = self._mailbox.delivery_status(action.delivery, deadline=end)
            if status != "acknowledged":
                return self._unavailable if status == "unavailable" else self._query(
                    "observe", action.intent, None, end
                )
        return self._query("transition", action.intent, action, end)

    def retire_without_reader(self, evidence: RetirementEvidence, *, deadline: float):
        """Retire synthetic no-reader obligations under exact durable quiescence."""
        if type(evidence) is not RetirementEvidence:
            raise ValueError("retirement requires exact evidence")
        end = finite_deadline(deadline)
        intent = evidence.intent.publication
        result = self._query("retirement_check", intent, evidence, end)
        if result.state != "eligible":
            return result
        status = self._mailbox.command_quiescence(evidence.intent.command_seal, deadline=end)
        if status.state != "quiescent":
            return self._unavailable if status.state == "unavailable" else self._query(
                "observe", intent, None, end
            )
        if evidence.kind == "settled_no_reader":
            status = self._mailbox.delivery_status(evidence.delivery, deadline=end)
            if status != "acknowledged":
                return self._unavailable if status == "unavailable" else self._query(
                    "observe", intent, None, end
                )
        result = self._query("retire", intent, evidence, end)
        return result if time.monotonic() < end else self._unavailable

    def _retirement_candidate(self, slot, evidence):
        """Revalidate exact identities and all lifecycle predicates under custody."""
        intent, certificate = slot.intent, evidence.intent
        if (certificate.producer is not intent.producer
                or certificate.cleanup_owner is not self._handle.cleanup_owner
                or certificate.command_seal.receipt is not intent.receipt.admission):
            return None, "foreign"
        if slot.retirement is not None:
            return None, "duplicate" if slot.retirement is evidence else "conflict"
        names = tuple(action.name for action in slot.actions)
        ready = slot.owner_admitted and slot.admission_producers == 0 and slot.readers == 0
        if evidence.kind == "empty_failure":
            legal = (ready and slot.stage == "start_pending" and slot.producers == 1
                     and slot.mutation_owner is intent.producer
                     and set(names) == {"owner_admit", "admission_handback", "start"})
        else:
            if (evidence.delivery is None
                    or evidence.delivery.command.receipt is not intent.receipt.admission):
                return None, "foreign" if evidence.delivery is not None else "blocked"
            legal = (ready and slot.stage == "settled" and slot.producers == 0
                     and slot.mutation_owner is self._handle.cleanup_owner
                     and set(names) == {"owner_admit", "admission_handback", "start",
                                        "resources", "transfer", "producer_handback", "settle"})
        if not legal:
            return None, "blocked"
        return replace(slot, stage="terminal", producers=0, readers=0,
                       mutation_owner=None, retirement=evidence), "eligible"

    def _acquire(self, end, ticket):
        """Journal native acquisition uncertainty and never wait for a lock."""
        if time.monotonic() >= end:
            return False
        ticket.state = "acquiring"
        acquired = self._lock.acquire(blocking=False)
        ticket.state = "held" if acquired else "not_acquired"
        return acquired and time.monotonic() < end

    def _finish(self, ticket):
        """Release only proven custody and preserve primary interruption identity."""
        primary = sys.exception()
        try:
            if ticket.state == "held":
                ticket.state = "releasing"
                self._lock.release()
                ticket.state = "released"
        except BaseException as error:
            error.cleanup_publication_ticket = ticket
            if primary is None:
                raise
            primary.cleanup_publication_ticket = ticket
            primary.cleanup_publication_release_error = error
        finally:
            if primary is not None and ticket.state in ("acquiring", "releasing"):
                primary.cleanup_publication_ticket = ticket

    def _query(self, operation, intent, argument, deadline):
        """Arm finalization before acquisition and recheck the original horizon."""
        end = finite_deadline(deadline)
        if operation not in ("snapshot", "seal") and type(intent) is not PublicationIntent:
            raise ValueError("query requires exact publication intent")
        candidate = PublicationState(intent) if operation == "publish" else None
        ticket = _Ticket(self._handle)
        result = self._unavailable
        try:
            try:
                if self._acquire(end, ticket):
                    result = self._locked(operation, intent, argument, candidate, end)
            finally:
                self._finish(ticket)
        except BaseException as error:
            error.cleanup_publication_ticket = ticket
            raise
        return result if time.monotonic() < end else self._unavailable

    def _observation(self, state, entries):
        """Build bounded immutable metadata without formatting caller objects."""
        return PublicationObservation(state, entries, tuple(
            entry.intent.receipt.admission.pending_debt for entry in entries
        ))

    def _locked(self, operation, intent, argument, candidate, end):
        """Check exact identity and commit one immutable bounded table replacement."""
        if time.monotonic() >= end:
            return self._unavailable
        if operation == "snapshot":
            return self._observation("current", tuple(
                entry for entry in self._slots if entry.intent.owner is argument
            ))
        if operation == "seal":
            self._sealed = True
            return self._observation("sealed", self._slots)
        if not any(receipt is intent.receipt for receipt in self._catalog):
            return self._observation("foreign", ())
        index = next((i for i, entry in enumerate(self._slots)
                      if entry.intent.receipt is intent.receipt), None)
        if index is None:
            return self._insert(operation, intent, candidate, end)
        slot = self._slots[index]
        if slot.intent is not intent:
            return self._observation("conflict", (slot,))
        if operation in ("observe", "publish"):
            return self._observation(slot.stage, (slot,))
        if operation in ("retirement_check", "retire"):
            updated, state = self._retirement_candidate(slot, argument)
            if updated is None or operation == "retirement_check":
                return self._observation(state, (slot,))
        elif operation == "join":
            if slot.stage != "pending":
                return self._observation(slot.stage, (slot,))
            updated = replace(slot, stage="joined", mutation_owner=intent.producer)
        else:
            if (argument.name == "start"
                    and time.monotonic() >= intent.budget.execution_deadline):
                return self._observation("blocked", (slot,))
            updated, state = self._advance(slot, argument)
            if updated is None:
                return self._observation(state, (slot,))
        if time.monotonic() >= end:
            return self._unavailable
        self._slots = self._slots[:index] + (updated,) + self._slots[index + 1:]
        return self._observation("committed", (updated,))

    def _insert(self, operation, intent, candidate, end):
        """Retain pending admission producer before the second public commit."""
        if operation != "publish":
            return self._observation("absent", ())
        if self._sealed:
            return self._observation("sealed", ())
        if any(entry.intent.record is intent.record or entry.intent.producer is intent.producer
               or entry.intent.admission is intent.admission for entry in self._slots):
            return self._observation("conflict", ())
        if len(self._slots) >= len(self._catalog):
            return self._observation("full", ())
        if time.monotonic() >= end:
            return self._unavailable
        self._slots = self._slots + (candidate,)
        return self._observation("published", (candidate,))

    def _advance(self, slot, action):
        """Enforce one producer, exclusive transfer and exact reader handback."""
        prior = next((item for item in slot.actions if item.name == action.name), None)
        if prior is not None:
            return None, "duplicate" if prior is action else "conflict"
        intent, name = slot.intent, action.name
        actor = intent.producer if name in (
            "admission_handback", "start", "resources", "transfer", "producer_handback"
        ) else intent.owner if name in ("owner_admit", "reader_grant", "reader_handback", "never_started") else self._handle.cleanup_owner
        if action.actor is not actor:
            return None, "foreign"
        if name in ("terminal", "never_started") and action.command_seal is None:
            return None, "blocked"
        if name == "terminal" and action.delivery is None:
            return None, "blocked"
        changes = self._changes(slot, name)
        if changes is None:
            return None, "blocked"
        return replace(slot, actions=slot.actions + (action,), **changes), "committed"

    def _changes(self, slot, name):
        """Select bounded legal metadata transitions without resource inference."""
        if name == "owner_admit" and slot.stage == "joined":
            return {"owner_admitted": True}
        if name == "admission_handback" and slot.stage == "joined":
            return {"admission_producers": 0}
        ready = slot.admission_producers == 0
        if name == "start" and slot.stage == "joined" and ready and slot.owner_admitted and not self._sealed:
            return {"stage": "start_pending"}
        if name == "resources" and slot.stage == "start_pending":
            return {"stage": "resources"}
        if name == "transfer" and slot.stage == "resources":
            return {"stage": "transferred", "mutation_owner": self._handle.cleanup_owner}
        if name == "producer_handback" and slot.stage == "transferred":
            return {"stage": "owned", "producers": 0}
        if name == "reader_grant" and slot.stage == "owned":
            return {"stage": "reading", "readers": 1}
        if name == "reader_handback" and slot.stage == "reading":
            return {"stage": "owned", "readers": 0}
        if name == "settle" and slot.stage == "owned" and slot.producers == 0:
            return {"stage": "settled"}
        if name == "terminal" and slot.stage == "settled" and slot.readers == 0:
            if not any(item.name == "reader_handback" for item in slot.actions):
                return None
            return {"stage": "terminal", "mutation_owner": None}
        if name == "never_started" and slot.stage == "joined" and ready:
            return {"stage": "terminal", "producers": 0, "mutation_owner": None}
        return None
