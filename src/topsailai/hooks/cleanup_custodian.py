"""Resource-free, owner-confined custodian lifecycle. Author: DawsonLin.

This foundation does not execute cleanup commands or transfer producer resources.
Only the constructing application-owner thread may operate the controller. The
single daemon actor waits for shutdown; pending mailbox slots never settle here.
Native event/thread operations have cooperative, not hard kernel-stall bounds.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from topsailai.hooks.cleanup_budget import (
    CLEANUP_ALLOWANCE_SECONDS, CleanupBudget, finite_deadline,
)
from topsailai.hooks.cleanup_mailbox import (
    CleanupAdmissionReceipt, CleanupDebtSnapshot, CleanupMailbox,
)
from topsailai.hooks.process_state import CleanupDebt


@dataclass(frozen=True, slots=True)
class CleanupActorReceipt:
    """Prehold exact thread and control cells before attempting thread start."""

    thread: threading.Thread
    ready: threading.Event
    stop: threading.Event


@dataclass(frozen=True, slots=True)
class BackendCloseReport:
    """Keep actor absence distinct from complete resource/debt settlement."""

    state: str
    admission_closed: bool
    actor_stopped: bool
    producer_count: int | None
    retained_debts: tuple[CleanupDebt, ...]
    fully_closed: bool


def _idle_actor(ready: threading.Event, stop: threading.Event) -> None:
    """Publish readiness then wait; perform no resource work or callbacks."""
    ready.set()
    stop.wait()


class CleanupCustodian:
    """Own one resource-free actor; no cross-thread controller sharing yet.

    An unavailable mailbox observation returns only the construction-time marker.
    A retained mailbox ticket permanently quarantines this controller. Shutdown
    can still request stopping its exact idle actor, but cannot claim settlement.
    There is no producer API: producer_count is zero only for current observations
    in this resource-free model, not evidence about any backend's producers.
    """

    def __init__(self, capacity: int, budget: CleanupBudget) -> None:
        """Construct fixed inventory and owner identity without starting a thread."""
        if type(budget) is not CleanupBudget:
            raise ValueError("custodian requires an exact CleanupBudget")
        self._mailbox = CleanupMailbox(capacity)
        self._budget = budget
        self._owner = threading.current_thread()
        self._state = "NEW"
        self._actor: CleanupActorReceipt | None = None
        self._start_attempted = False
        self._quarantine_ticket = None

    @property
    def handle(self):
        """Return immutable lock-independent unavailable observation authority."""
        return self._mailbox.handle

    @property
    def actor_receipt(self) -> CleanupActorReceipt | None:
        """Expose prepublished actor identity to the exact application owner."""
        self._check_owner()
        return self._actor

    @property
    def quarantine_ticket(self):
        """Retain exact uncertain custody without granting unlock authority."""
        self._check_owner()
        return self._quarantine_ticket

    def _check_owner(self) -> None:
        """Reject concurrent or foreign lifecycle owners before mutable access."""
        if threading.current_thread() is not self._owner:
            raise ValueError("custodian lifecycle requires its application owner")

    def _deadline(self, deadline: float | None) -> float:
        """Create one caller horizon; never change the stored execution budget."""
        self._check_owner()
        if deadline is None:
            return time.monotonic() + CLEANUP_ALLOWANCE_SECONDS
        return finite_deadline(deadline)

    def quarantine(self, ticket) -> None:
        """STOP on exact retained mailbox custody; never retry native release."""
        self._check_owner()
        if (getattr(ticket, "handle", None) is not self.handle
                or getattr(ticket, "state", None) not in
                ("held", "acquiring", "releasing")):
            raise ValueError("quarantine requires exact retained mailbox custody")
        self._quarantine_ticket = ticket
        self._state = "UNAVAILABLE"

    def _observe(self, deadline: float) -> CleanupDebtSnapshot:
        """Observe bounded mailbox or retain exact interruption authority."""
        if self._quarantine_ticket is not None:
            return CleanupDebtSnapshot("unavailable", (self.handle.unavailable_debt,))
        try:
            return self._mailbox.snapshot(deadline=deadline)
        except BaseException as error:
            ticket = getattr(error, "cleanup_mailbox_ticket", None)
            if ticket is not None and ticket.state in ("held", "acquiring", "releasing"):
                self.quarantine(ticket)
            raise

    def open(self, *, deadline: float | None = None) -> bool:
        """Start at most one exact idle actor after authoritative observation."""
        end = self._deadline(deadline)
        observation = self._observe(end)
        if observation.state != "current" or time.monotonic() >= end:
            return False
        if self._state in ("CLOSING", "CLOSED", "UNAVAILABLE"):
            return False
        if self._state == "NEW":
            ready, stop = threading.Event(), threading.Event()
            actor = CleanupActorReceipt(
                threading.Thread(target=_idle_actor, args=(ready, stop), daemon=True),
                ready, stop,
            )
            self._actor = actor
            self._state = "STARTING"
            if time.monotonic() >= end:
                self._state = "CLOSING"
                return False
            try:
                self._start_attempted = True
                actor.thread.start()
            except BaseException as error:
                self._state = "UNAVAILABLE"
                error.cleanup_actor_receipt = actor
                raise
        actor = self._actor
        if actor.ready.wait(max(0.0, end - time.monotonic())):
            if time.monotonic() < end and actor.thread.is_alive():
                self._state = "RUNNING"
                return True
        return False

    def reserve(self, *, deadline: float | None = None) -> CleanupAdmissionReceipt | None:
        """Admit only while running; no resource creation or producer transfer."""
        end = self._deadline(deadline)
        if not self.open(deadline=end):
            return None
        try:
            return self._mailbox.reserve(deadline=end)
        except BaseException as error:
            ticket = getattr(error, "cleanup_mailbox_ticket", None)
            if ticket is not None and ticket.state in ("held", "acquiring", "releasing"):
                self.quarantine(ticket)
            raise

    def snapshot(self, *, deadline: float | None = None) -> CleanupDebtSnapshot:
        """Keep unavailable inventory distinct from verified empty debt."""
        return self._observe(self._deadline(deadline))

    def close(self, *, deadline: float | None = None) -> BackendCloseReport:
        """Seal admission and observe the exact actor within one caller horizon.

        Actor shutdown uses its prepublished receipt, not mailbox authority.
        Unavailable inventory retains unknown debt even after confirmed actor exit.
        No slots are retired: pending commands/receipts stay debt and capacity.
        Repeated close never starts a replacement actor or renews resource D/C.
        """
        end = self._deadline(deadline)
        self._state = "CLOSING"
        actor = self._actor
        stopped = actor is None or not self._start_attempted
        if actor is not None:
            actor.stop.set()
            # An uncertain start has no safe join authority before an identity exists.
            if actor.thread.ident is not None:
                actor.thread.join(max(0.0, end - time.monotonic()))
                stopped = not actor.thread.is_alive()
        current = self._observe(end)
        if current.state != "current":
            self._state = "UNAVAILABLE"
            return BackendCloseReport(
                self._state, True, stopped, None, current.debts, False,
            )
        complete = stopped and not current.debts
        if complete:
            self._state = "CLOSED"
        return BackendCloseReport(
            self._state, True, stopped, 0, current.debts, complete,
        )
