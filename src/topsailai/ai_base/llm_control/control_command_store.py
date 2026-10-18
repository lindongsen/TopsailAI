"""Bounded command observations used under the registry lock. Author: DawsonLin."""
from collections import OrderedDict
from dataclasses import dataclass
import math
import time

from topsailai.ai_base.llm_control.attempt_control import ControlProposal


@dataclass(frozen=True, slots=True)
class CommandStatus:
    """Report receipt separately from arbitration and final application."""
    proposal: ControlProposal
    state: str
    reason: str | None = None


@dataclass(slots=True)
class _Record:
    """Retain exact proposal identity and monotonic settlement time."""
    status: CommandStatus
    settled_at: float | None = None


class CommandStore:
    """Bound all records; never evict queued, accepted or recovery-owned work.

    The request-control service owns synchronization. No callbacks or cleanup
    run here. Expiry is maintenance, not permission to discard pending work.
    """

    def __init__(self, *, capacity=256, retention=600.0, clock=time.monotonic):
        """Configure finite retention without environment or test-only switches."""
        if type(capacity) is not int or capacity < 1:
            raise ValueError("invalid command capacity")
        if type(retention) not in (int, float) or not math.isfinite(retention) or retention <= 0:
            raise ValueError("invalid command retention")
        self._capacity = capacity
        self._retention = retention
        self._clock = clock
        self._records = OrderedDict()

    def prune(self):
        """Remove only settled records whose monotonic retention expired."""
        now = self._clock()
        for key, record in tuple(self._records.items()):
            if record.settled_at is not None and now - record.settled_at >= self._retention:
                del self._records[key]

    def lookup(self, command_id):
        """Return a detached immutable observation, including retained terminals."""
        record = self._records.get(command_id)
        return record.status if record is not None else None

    def issue(self, proposal):
        """Queue a reference or reject capacity without evicting unresolved work."""
        self.prune()
        if len(self._records) >= self._capacity:
            return CommandStatus(proposal, "rejected", "capacity")
        status = CommandStatus(proposal, "queued")
        self._records[proposal.command_id] = _Record(status)
        return status

    def pending(self, target):
        """Probe the oldest exact-target reference without consuming it."""
        return next((record.status.proposal for record in self._records.values()
                     if record.status.state == "queued" and record.status.proposal.target == target), None)

    def owns(self, proposal, state="queued"):
        """Require original retained object identity, not equality or claimed origin."""
        if type(proposal) is not ControlProposal:
            return False
        record = self._records.get(proposal.command_id)
        return record is not None and record.status.proposal is proposal and record.status.state == state

    def transition(self, proposal, state, reason=None):
        """Update a retained exact reference; callers enforce lifecycle ordering."""
        status = CommandStatus(proposal, state, reason)
        settled_at = self._clock() if state in ("applied", "rejected") else None
        self._records[proposal.command_id] = _Record(status, settled_at)
        return status

    def reject_pending(self, target, reason):
        """Settle only one target's losing proposals, preserving unrelated work."""
        for record in self._records.values():
            proposal = record.status.proposal
            if proposal.target == target and record.status.state == "queued":
                self.transition(proposal, "rejected", reason)
