"""Bounded route-independent control custody. Author: DawsonLin."""
from dataclasses import dataclass, field
import logging
from threading import Lock, RLock, Thread
import time

from .request_control import REQUEST_CONTROL

_LOG = logging.getLogger(__name__)


@dataclass(eq=False)
class AttemptLease:
    """Keep exact resource and delivery facts without retaining an application."""
    target: object
    owner: object
    authority: object = None
    active: bool = True
    proposal: object = None
    signal: object = None
    consumed: bool = False
    superseded: bool = False
    timing_stat: object = None
    timing_ticket: object = None
    lock: object = field(default_factory=RLock)

    def reconcile(self):
        """Retire and settle one inactive lease outside pool/route locks."""
        with self.lock:
            if self.active:
                return False
            if self.proposal is not None and self.authority is not None:
                # Reconcile selection before retiring its only live authority.
                REQUEST_CONTROL.select(self.target, self.proposal)
            REQUEST_CONTROL.retire(self.target)
            selected = (self.authority is not None and self.proposal is not None
                        and self.authority.selected(self.proposal))
            if selected and self.owner is not None:
                self.owner.abandon(self.signal)
            if self.signal is not None and (self.consumed or self.superseded):
                self.signal.__traceback__ = None
                self.signal.__context__ = None
                self.signal.__cause__ = None
            if self.owner is not None and not self.owner.control_cleanup_settled():
                return False
            if self.timing_stat is not None and self.timing_ticket is not None:
                self.timing_stat.finish_request(self.timing_ticket)
            if not selected:
                return True
            if self.consumed:
                REQUEST_CONTROL.applied(self.proposal)
                REQUEST_CONTROL.settle(self.proposal)
            elif self.superseded:
                REQUEST_CONTROL.settle_undelivered(self.proposal)
            else:
                return False
            status = REQUEST_CONTROL.status(self.proposal.command_id)
            return status is not None and status.proposal is self.proposal and status.state in ("applied", "rejected")


class RecoveryPool:
    """Reserve before publication and maintain a finite exact custody registry."""

    def __init__(self, capacity=256, interval=0.05):
        """Inject finite capacity and maintenance cadence at construction."""
        if type(capacity) is not int or capacity < 1:
            raise ValueError("invalid recovery capacity")
        self.capacity = capacity
        self.interval = interval
        self.lock = RLock()
        self.pass_lock = Lock()
        self.leases = {}
        self.worker = None

    def reserve(self, target, owner):
        """Reserve one slot before any controlled binding or worker exists."""
        self.maintain()
        with self.lock:
            if len(self.leases) >= self.capacity:
                return None
            lease = AttemptLease(target, owner)
            self.leases[target] = lease
            return lease

    def maintain(self):
        """Bound one pass; never perform owner callbacks under the pool lock."""
        if not self.pass_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                leases = tuple(self.leases.values())
            for lease in leases:
                try:
                    settled = lease.reconcile()
                except Exception:
                    _LOG.exception("control recovery failed target=%s", lease.target)
                    continue
                if settled:
                    with self.lock:
                        if self.leases.get(lease.target) is lease:
                            del self.leases[lease.target]
        finally:
            self.pass_lock.release()

    def supersede(self, binding_id, invocation_id, primary):
        """Record host supersession without retaining its traceback or application."""
        with self.lock:
            leases = tuple(self.leases.values())
        for lease in leases:
            if (lease.target.binding_id != binding_id
                    or (invocation_id is not None and
                        lease.target.invocation_id != invocation_id)):
                continue
            with lease.lock:
                if lease.signal is not primary and not lease.consumed:
                    lease.superseded = True

    def schedule(self):
        """Keep closed-route debt reachable through one lazy maintenance worker."""
        self.maintain()
        with self.lock:
            if not self.leases or (self.worker is not None and self.worker.is_alive()):
                return
            from contextvars import Context
            worker = Thread(target=lambda: Context().run(self._run), daemon=True,
                            name="llm-control-recovery")
            self.worker = worker
            try:
                worker.start()
            except BaseException:
                _LOG.exception("control recovery worker start failed")
                raise

    def _run(self):
        """Exit only after the last reserved owner has completely settled."""
        while True:
            self.maintain()
            with self.lock:
                if not self.leases:
                    self.worker = None
                    return
            time.sleep(self.interval)


RECOVERY_POOL = RecoveryPool()


def acknowledge_control(signal):
    """Record consumption only for an exact privately journaled signal."""
    lease = getattr(signal, "_control_lease", None)
    if type(lease) is not AttemptLease:
        return False
    try:
        with lease.lock:
            if lease.signal is not signal or lease.proposal is None or lease.superseded:
                return False
            if lease.authority is None or not lease.authority.selected(lease.proposal):
                return False
            lease.consumed = True
            REQUEST_CONTROL.applied(lease.proposal)
            return True
    except BaseException:
        # AgentChat consumes after its application scope has already exited.
        # Preserve consumption if committed; otherwise journal supersession here.
        with lease.lock:
            if lease.signal is signal and not lease.consumed:
                lease.superseded = True
        raise
