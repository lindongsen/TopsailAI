"""Inert first-record arbitration contracts. Author: DawsonLin."""
from dataclasses import dataclass
import math
from threading import RLock
import time


def identifier(value):
    """Reject unbounded or non-scalar external identifiers before lookup."""
    if type(value) is not str or not value or len(value) > 128:
        raise ValueError("invalid control identifier")
    return value


@dataclass(frozen=True, slots=True)
class AttemptTarget:
    """Detach route generation and request identity from application objects."""
    binding_id: str
    generation: int
    invocation_id: str
    attempt_id: str

    def __post_init__(self):
        """Validate exact scalar identities without invoking arbitrary properties."""
        for value in (self.binding_id, self.invocation_id, self.attempt_id):
            identifier(value)
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("invalid binding generation")


@dataclass(frozen=True, slots=True)
class ControlProposal:
    """Carry a registry-retained reference, not a self-authorizing command."""
    target: AttemptTarget
    command_id: str
    operation: str

    def __post_init__(self):
        """Reject malformed references before they reach a command ledger."""
        if type(self.target) is not AttemptTarget:
            raise ValueError("invalid proposal target")
        identifier(self.command_id)
        if type(self.operation) is not str or self.operation not in ("hard_interrupt", "force_retry"):
            raise ValueError("invalid control operation")


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    """Expose detached state without delivering owner or synchronization handles."""
    target: AttemptTarget
    phase: str
    outcome: str | None


class AttemptControl:
    """Serialize publication and control on one lock; never perform cleanup here."""

    def __init__(self, target, *, deadline=None, raise_timeout=True,
                 retry_available=True, interrupt_supported=True, clock=time.monotonic,
                 lock=None):
        """Create an unbound authority with explicit policy and absolute deadline."""
        if type(target) is not AttemptTarget:
            raise ValueError("invalid attempt target")
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise ValueError("invalid deadline")
        if any(type(flag) is not bool for flag in (raise_timeout, retry_available, interrupt_supported)):
            raise ValueError("invalid attempt policy")
        self.target = target
        self._deadline = deadline
        self._raise_timeout = raise_timeout
        self._retry_available = retry_available
        self._interrupt_supported = interrupt_supported
        self._clock = clock
        self._lock = lock if lock is not None else RLock()
        self._phase = "creating"
        self._decision = (None, None)

    def selected(self, proposal):
        """Identify an exact selected command across interrupted publication."""
        with self._lock:
            return self._decision[1] is proposal

    def snapshot(self):
        """Read state under the same lock used by publication and selection."""
        with self._lock:
            return AttemptSnapshot(self.target, self._phase, self._decision[0])

    def _expire(self):
        """Give raising deadline equality precedence at the publication boundary."""
        if self._decision[0] is None and self._raise_timeout and self._deadline is not None and self._clock() >= self._deadline:
            self._decision = ("timeout", None)

    def created(self, *, streaming=True):
        """Keep streaming creation open; nonstream acceptance closes the window."""
        if type(streaming) is not bool:
            raise ValueError("invalid streaming flag")
        with self._lock:
            self._expire()
            if self._decision[0] is not None:
                return False
            self._phase = "first_record"
            if not streaming:
                self._decision = ("value", None)
            return True

    def publish(self, outcome):
        """Commit any decoded value, EOF or error independently of content."""
        if type(outcome) is not str or outcome not in ("value", "eof", "error"):
            raise ValueError("invalid publication outcome")
        with self._lock:
            self._expire()
            if self._decision[0] is not None:
                return False
            self._decision = (outcome, None)
            return True

    def select(self, operation, *, cleanup_pending=False, proposal=None):
        """Select at most one command after policy and deadline revalidation."""
        if type(operation) is not str or operation not in ("hard_interrupt", "force_retry"):
            raise ValueError("invalid control operation")
        if type(cleanup_pending) is not bool:
            raise ValueError("invalid cleanup state")
        with self._lock:
            self._expire()
            if self._decision[0] is not None:
                return "already_decided"
            if operation == "hard_interrupt" and not self._interrupt_supported:
                return "unsupported_exit_scope"
            if operation == "force_retry" and not self._retry_available:
                return "retry_budget_exhausted"
            if operation == "force_retry" and cleanup_pending:
                return "cleanup_pending"
            self._decision = (operation, proposal)
            return "accepted"
