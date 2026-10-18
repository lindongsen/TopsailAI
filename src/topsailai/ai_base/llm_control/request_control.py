"""Canonical inert request authority, independent of workspace. Author: DawsonLin."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
import time

from topsailai.ai_base.llm_control.attempt_control import (
    AttemptControl, AttemptTarget, ControlProposal, identifier,
)
from topsailai.ai_base.llm_control.control_command_store import CommandStore, CommandStatus

_CURRENT_TARGET = ContextVar("topsailai_control_target", default=None)


class RequestControl:
    """Own exact bindings, command provenance and cleanup custody.

    Lock order: registry RLock is also each attempt's arbitration lock. No Hook,
    cleanup, logger or application callback may execute while it is held. Trusted
    binding callers must mint fresh invocation/attempt identities on every new
    request and advance generation when replacing route ownership; bind() is
    an authority operation, never an untrusted command endpoint. The
    injected monotonic clock must be a nonblocking trusted scalar clock.
    """

    def __init__(self, *, capacity=256, retention=600.0, clock=time.monotonic):
        """Construct an empty service; imports never bind or activate requests."""
        self._lock = RLock()
        self._store = CommandStore(capacity=capacity, retention=retention, clock=clock)
        self._clock = clock
        self._capacity = capacity
        self._active = {}
        self._debts = {}

    def bind(self, target, **policy):
        """Explicitly admit a unique live route, refusing implicit replacements."""
        if type(target) is not AttemptTarget:
            raise ValueError("invalid binding target")
        with self._lock:
            if target.binding_id in self._active or len(self._active) >= self._capacity:
                raise ValueError("binding busy or capacity exhausted")
            authority = AttemptControl(target, clock=self._clock, lock=self._lock, **policy)
            self._active[target.binding_id] = authority
            return authority

    def _authority(self, target):
        """Resolve exact full target only; no current-Agent or fuzzy fallback."""
        if type(target) is not AttemptTarget:
            return None
        authority = self._active.get(target.binding_id)
        return authority if authority is not None and authority.target == target else None

    def snapshot(self, target):
        """Return detached status for an exact live target."""
        with self._lock:
            authority = self._authority(target)
            return authority.snapshot() if authority is not None else None

    def submit(self, target, command_id, operation):
        """Lookup retransmissions before target validity, then queue, never accept."""
        proposal = ControlProposal(target, command_id, operation)
        with self._lock:
            self._store.prune()
            previous = self._store.lookup(command_id)
            if previous is not None:
                return previous if previous.proposal == proposal else CommandStatus(proposal, "rejected", "conflict")
            authority = self._authority(target)
            if authority is None:
                return CommandStatus(proposal, "rejected", "stale_target")
            if authority.snapshot().outcome is not None:
                return CommandStatus(proposal, "rejected", "already_decided")
            return self._store.issue(proposal)

    def submit_current(self, binding_id, generation, target, command_id, operation,
                       *, capacity_unavailable=False):
        """Replay route-owned history before submitting a frozen current target.

        The application holds its route lock throughout this call. This service
        never discovers routes or retargets an existing command to a new attempt.
        """
        identifier(binding_id)
        identifier(command_id)
        if type(generation) is not int or generation < 1:
            raise ValueError("invalid binding generation")
        if type(operation) is not str or operation not in ("hard_interrupt", "force_retry"):
            raise ValueError("invalid control operation")
        with self._lock:
            self._store.prune()
            previous = self._store.lookup(command_id)
            if previous is not None:
                original = previous.proposal.target
                if original.binding_id != binding_id or original.generation != generation:
                    raise ValueError("conflict")
                if previous.proposal.operation == operation:
                    return previous
                proposal = ControlProposal(original, command_id, operation)
                return CommandStatus(proposal, "rejected", "conflict")
            if capacity_unavailable:
                raise ValueError("unavailable/control_capacity")
            if target is None:
                raise ValueError("no_active_target")
            if (type(target) is not AttemptTarget or target.binding_id != binding_id
                    or target.generation != generation):
                raise ValueError("stale_target")
            return self.submit(target, command_id, operation)

    def probe(self, target, phase):
        """Observe a pending reference without consuming or selecting commands."""
        with self._lock:
            authority = self._authority(target)
            if authority is None:
                return None
            snapshot = authority.snapshot()
            if type(phase) is not str or phase != snapshot.phase or snapshot.outcome is not None:
                return None
            return self._store.pending(target)

    def validates(self, target, proposal):
        """Recheck live route and retained identity after an opaque Hook return."""
        with self._lock:
            authority = self._authority(target)
            return (authority is not None and authority.snapshot().outcome is None
                    and type(proposal) is ControlProposal and proposal.target == target
                    and self._store.owns(proposal))

    def _debt_key(self, proposal):
        """Group exact attempt custody by invocation without retaining an owner."""
        target = proposal.target
        return (target.binding_id, target.generation, target.invocation_id)

    def _remove_debt(self, proposal):
        """Reconcile exact removal, including interruption after the last entry."""
        key = self._debt_key(proposal)
        debts = self._debts.get(key)
        if debts is None:
            return
        if debts.get(proposal.command_id) is proposal:
            del debts[proposal.command_id]
        if not debts:
            del self._debts[key]

    def select(self, target, proposal):
        """Arm custody before selection and reconcile interrupted exact winners."""
        with self._lock:
            if type(proposal) is not ControlProposal or proposal.target != target:
                return None
            authority = self._authority(target)
            status = self._store.lookup(proposal.command_id)
            if authority is None or status is None or status.proposal is not proposal:
                return None
            key = self._debt_key(proposal)
            debts = self._debts.get(key, {})
            armed = debts.get(proposal.command_id) is proposal
            if status.state not in ("queued", "accepted", "recovery"):
                if armed and not authority.selected(proposal):
                    self._remove_debt(proposal)
                return None
            outcome = authority.snapshot().outcome
            if outcome is not None and not armed:
                return None
            cleanup_pending = any(value is not proposal for value in debts.values())
            # One dictionary publication arms the exact recovery owner first.
            self._debts[key] = {**debts, proposal.command_id: proposal}
            reason = ("accepted" if authority.selected(proposal) else
                      authority.select(proposal.operation, cleanup_pending=cleanup_pending, proposal=proposal))
            if reason == "accepted":
                if status.state == "queued":
                    status = self._store.transition(proposal, "accepted")
                self._store.reject_pending(target, "already_decided")
            else:
                # No selected control means no resource cleanup obligation exists.
                self._remove_debt(proposal)
                status = self._store.transition(proposal, "rejected", reason)
            return status

    def applied(self, proposal):
        """Report delivery only; accepted cleanup custody remains independently held."""
        with self._lock:
            if not self._store.owns(proposal, "accepted"):
                return False
            # Recovery-owned records remain non-evictable until settle().
            self._store.transition(proposal, "recovery")
            return True

    def settle(self, proposal):
        """Confirm cleanup, reconcile custody, then publish evictable success."""
        with self._lock:
            if not self._store.owns(proposal, "recovery"):
                return False
            # The non-evictable exact ledger reference journals partial removal.
            self._remove_debt(proposal)
            self._store.transition(proposal, "applied")
            return True

    def settle_undelivered(self, proposal):
        """Settle exact selected custody superseded before consumer delivery."""
        with self._lock:
            status = self._store.lookup(getattr(proposal, "command_id", None))
            if status is None or status.proposal is not proposal:
                return False
            if status.state == "rejected":
                return status.reason == "interrupted_before_delivery"
            if status.state != "accepted":
                return False
            self._remove_debt(proposal)
            self._store.transition(proposal, "rejected", "interrupted_before_delivery")
            return True

    def retire(self, target):
        """Revoke an exact binding, retaining unresolved recovery responsibility."""
        with self._lock:
            if self._authority(target) is None:
                return False
            for proposal in tuple(self._debts.get(
                    (target.binding_id, target.generation, target.invocation_id), {}).values()):
                if proposal.target != target:
                    continue
                if self._authority(target).selected(proposal):
                    self.select(target, proposal)
                else:
                    self._remove_debt(proposal)
            key = (target.binding_id, target.generation, target.invocation_id)
            if self._debts.get(key) == {}:
                del self._debts[key]
            self._store.reject_pending(target, "stale_target")
            # Revoke only after all dependent ledger/custody work is complete.
            del self._active[target.binding_id]
            return True

    def status(self, command_id):
        """Read bounded command history without returning live owners or errors."""
        from topsailai.ai_base.llm_control.attempt_control import identifier
        identifier(command_id)
        with self._lock:
            self._store.prune()
            return self._store.lookup(command_id)


REQUEST_CONTROL = RequestControl()


@contextmanager
def request_control_scope(target):
    """Scope explicit target identity; no registry binding or worker inheritance."""
    if type(target) is not AttemptTarget:
        raise ValueError("invalid scoped target")
    token = _CURRENT_TARGET.set(target)
    try:
        yield target
    finally:
        _CURRENT_TARGET.reset(token)


def current_control_target():
    """Return the explicit context-local identity without discovering an Agent."""
    return _CURRENT_TARGET.get()
