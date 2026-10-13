"""Exact caller-preheld resource-free admission regressions. Author: DawsonLin."""

from dataclasses import FrozenInstanceError, replace
import inspect
import sys
import time
from types import SimpleNamespace

import pytest

import topsailai.hooks.cleanup_mailbox as module
from topsailai.hooks.cleanup_mailbox import (
    CleanupAdmissionIntent, CleanupMailbox, CleanupCommand, CleanupDeliveryReceipt,
)


def horizon():
    """Retain one generous absolute invocation horizon without timing sleeps."""
    return time.monotonic() + 1


def prepared(mailbox, index=0):
    """Prehold the exact intent before any mutable admission."""
    return CleanupAdmissionIntent(mailbox.prepare_admission(index))


class ForbiddenInventory:
    """Poison all protected reads after failed acquisition."""

    def __iter__(self):
        """Reject unsafe iteration."""
        pytest.fail("inventory read")

    def __len__(self):
        """Reject unsafe capacity checks."""
        pytest.fail("inventory read")


def test_catalog_is_fixed_immutable_and_resource_free():
    """Preparation reads only immutable identities, never mutable capacity."""
    mailbox = CleanupMailbox(256)
    receipts = tuple(mailbox.prepare_admission(i) for i in range(256))
    assert len({id(r) for r in receipts}) == 256
    assert mailbox.snapshot(deadline=horizon()).debts == ()
    mailbox._slots = ForbiddenInventory()
    mailbox._capacity = ForbiddenInventory()
    for index, receipt in enumerate(receipts):
        assert mailbox.prepare_admission(index) is receipt
        with pytest.raises(FrozenInstanceError):
            receipt.slot_id = "changed"
    intent = CleanupAdmissionIntent(receipts[0])
    with pytest.raises(FrozenInstanceError):
        intent.receipt = receipts[1]


@pytest.mark.parametrize("index", [-1, 2, True, 1.0, "0", None])
def test_invalid_index(index):
    """Reject nonexact and out-of-range indices without synchronization."""
    with pytest.raises(ValueError):
        CleanupMailbox(2).prepare_admission(index)


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
@pytest.mark.parametrize("value", [None, True, "1", float("nan"), float("inf")])
def test_invalid_deadline(operation, value):
    """Validate the absolute horizon before any inventory read."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    mailbox._slots = ForbiddenInventory()
    with pytest.raises(ValueError):
        getattr(mailbox, operation)(intent, deadline=value)


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
def test_exact_input_types(operation):
    """Reject duck types and subclasses before synchronization."""
    mailbox = CleanupMailbox(1)
    with pytest.raises(ValueError):
        CleanupAdmissionIntent(None)
    class IntentSubclass(CleanupAdmissionIntent):
        """Supply a type lookalike with identical fields."""
    for intent in (None, SimpleNamespace(receipt=mailbox.prepare_admission(0)),
                   IntentSubclass(mailbox.prepare_admission(0))):
        with pytest.raises(ValueError):
            getattr(mailbox, operation)(intent, deadline=horizon())


def test_exact_association_conflicts_and_foreign_receipts():
    """Matching fields never replace original receipt or committed intent."""
    mailbox = CleanupMailbox(2)
    intent = prepared(mailbox)
    copied = replace(intent)
    assert mailbox.admission_status(intent, deadline=horizon()).state == "absent"
    admitted = mailbox.admit(intent, deadline=horizon())
    assert admitted.state == "admitted"
    assert admitted.debts[0] is intent.receipt.pending_debt
    for operation in (mailbox.admit, mailbox.admission_status):
        assert operation(intent, deadline=horizon()).state == "admitted"
        conflict = operation(copied, deadline=horizon())
        assert conflict.state == "conflict"
        assert conflict.debts[0] is intent.receipt.pending_debt
        for receipt in (replace(intent.receipt), CleanupMailbox(1).prepare_admission(0),
                        mailbox.reserve(deadline=horizon())):
            # The legacy reservation consumes capacity once; later calls may be None.
            if receipt is not None:
                foreign = operation(CleanupAdmissionIntent(receipt), deadline=horizon())
                assert foreign.state == "foreign" and foreign.debts == ()
    assert len(mailbox.snapshot(deadline=horizon()).debts) == 2


@pytest.mark.parametrize("legacy_first", [True, False])
def test_shared_capacity_and_idempotency(legacy_first):
    """Both APIs consume one pool; existing exact associations win over full."""
    mailbox = CleanupMailbox(2)
    first, second = prepared(mailbox), prepared(mailbox, 1)
    if legacy_first:
        assert mailbox.reserve(deadline=horizon()) is not None
    assert mailbox.admit(first, deadline=horizon()).state == "admitted"
    if not legacy_first:
        assert mailbox.reserve(deadline=horizon()) is not None
    assert mailbox.admit(first, deadline=horizon()).state == "admitted"
    assert mailbox.admit(second, deadline=horizon()).state == "full"
    assert mailbox.admission_status(second, deadline=horizon()).state == "absent"
    assert mailbox.admit(replace(first), deadline=horizon()).state == "conflict"
    assert mailbox.reserve(deadline=horizon()) is None


def test_command_cycles_preserve_intent_and_capacity():
    """Transport acknowledgements cannot erase the exact admission association."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    mailbox.admit(intent, deadline=horizon())
    for sequence in (1, 2):
        command = CleanupCommand(intent.receipt, sequence)
        delivery = CleanupDeliveryReceipt(command)
        assert mailbox.submit(command, deadline=horizon()) == "accepted"
        assert mailbox.take(intent.receipt, delivery=delivery, deadline=horizon()) is command
        assert mailbox.admission_status(intent, deadline=horizon()).state == "admitted"
        assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
        assert mailbox.delivery_status(delivery, deadline=horizon()) == "acknowledged"
        assert mailbox.observe(intent.receipt, deadline=horizon()) == sequence
        assert mailbox.admission_status(intent, deadline=horizon()).state == "admitted"
        assert mailbox.admit(replace(intent), deadline=horizon()).state == "conflict"
    assert mailbox.reserve(deadline=horizon()) is None
    assert mailbox.snapshot(deadline=horizon()).debts == (intent.receipt.pending_debt,)


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
@pytest.mark.parametrize("expired", [True, False])
def test_failed_acquisition_has_no_protected_reads(operation, expired):
    """Unavailable never becomes false absence/full/foreign under contention."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    mailbox._slots = ForbiddenInventory()
    mailbox._capacity = ForbiddenInventory()
    mailbox._catalog = ForbiddenInventory()
    mailbox._lock.acquire()
    try:
        result = getattr(mailbox, operation)(intent, deadline=time.monotonic()-1 if expired else horizon())
        assert result is mailbox._admission_unavailable
        assert result.debts is mailbox._unavailable.debts
        assert result.debts[0] is mailbox.handle.unavailable_debt
    finally:
        mailbox._lock.release()


@pytest.mark.parametrize("ticks,committed", [([10], False), ([0, 10], False),
    ([0, 0, 10], False), ([0, 0, 0, 10], False), ([0, 0, 0, 0, 10], True)])
def test_deadline_boundaries(monkeypatch, ticks, committed):
    """Entry/acquire/commit/return checks preserve the same absolute deadline."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    values = iter(ticks)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(values, 10)))
    assert mailbox.admit(intent, deadline=5).state == "unavailable"
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    assert mailbox.admission_status(intent, deadline=5).state == ("admitted" if committed else "absent")


def test_deadline_after_finalization_preserves_commit(monkeypatch):
    """Late release completion cannot authorize admission within an expired call."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    finish = mailbox._finish
    def late(ticket):
        """Finalize normally then consume the caller horizon."""
        finish(ticket)
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 10))
    monkeypatch.setattr(mailbox, "_finish", late)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    assert mailbox.admit(intent, deadline=5).state == "unavailable"
    monkeypatch.setattr(mailbox, "_finish", finish)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    assert mailbox.admission_status(intent, deadline=5).state == "admitted"


@pytest.mark.parametrize("boundary", ["before_commit", "after_commit", "returned"])
def test_lost_admission_return_reconciles(boundary):
    """One-shot target-frame interruption leaves exact intent with both owners."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    primary = KeyboardInterrupt("lost admission return")
    target = CleanupMailbox._admission_locked.__code__
    lines, start = inspect.getsourcelines(CleanupMailbox._admission_locked)
    commit = start + next(i for i, line in enumerate(lines) if "self._slots =" in line)
    old = sys.gettrace()
    fired = False
    def trace(frame, event, arg):
        """Interrupt exactly once without affecting reconciliation."""
        nonlocal fired
        match = ((boundary == "before_commit" and event == "line" and frame.f_lineno == commit)
                 or (boundary == "after_commit" and event == "return" and frame.f_code is target)
                 or (boundary == "returned" and event == "return" and frame.f_code is CleanupMailbox._admission_query.__code__))
        if not fired and match and frame.f_code in (target, CleanupMailbox._admission_query.__code__):
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            mailbox.admit(intent, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired and not mailbox._lock.locked()
    assert mailbox.admission_status(intent, deadline=horizon()).state == ("absent" if boundary == "before_commit" else "admitted")
    assert mailbox.admit(intent, deadline=horizon()).state == "admitted"
    assert len(mailbox.snapshot(deadline=horizon()).debts) == 1


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
@pytest.mark.parametrize("boundary", ["caller_guard", "caller_finish", "entry", "primary", "try"])
def test_finalizer_entry_interrupts_retain_custody(operation, boundary):
    """Interrupted finalizer entry retains held ticket for application quarantine."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    primary = KeyboardInterrupt("finalizer boundary")
    caller = CleanupMailbox._admission_query.__code__
    target = caller if boundary.startswith("caller_") else CleanupMailbox._finish.__code__
    function = CleanupMailbox._admission_query if target is caller else CleanupMailbox._finish
    lines, start = inspect.getsourcelines(function)
    if boundary == "entry":
        line = None
    else:
        pattern = {"caller_guard": "self._finish(ticket)", "caller_finish": "self._finish(ticket)",
                   "primary": "primary = sys.exception()", "try": "try:"}[boundary]
        line = start + next(i for i, text in enumerate(lines) if pattern in text)
    old = sys.gettrace()
    fired = False
    def trace(frame, event, arg):
        """Target one finalizer instruction with a single injected interruption."""
        nonlocal fired
        if not fired and frame.f_code is target and ((line is None and event == "call") or (event == "line" and frame.f_lineno == line)):
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            getattr(mailbox, operation)(intent, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired
    assert primary.cleanup_mailbox_ticket.handle is mailbox.handle
    assert primary.cleanup_mailbox_ticket.state == "held"
    assert mailbox._lock.locked()
    # Only fixture ownership permits release; production must quarantine.
    mailbox._lock.release()


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
@pytest.mark.parametrize("acquire_fault", [True, False])
def test_native_uncertainty_never_retries(operation, acquire_fault):
    """Ambiguous acquire/release preserves ticket with no second native action."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    primary = KeyboardInterrupt("native uncertainty")
    class Lock:
        """Model ambiguous native completion without owning any resource."""
        releases = 0
        def acquire(self, blocking=False):
            """Either lose acquire evidence or prove one acquisition."""
            assert blocking is False
            if acquire_fault:
                raise primary
            return True
        def release(self):
            """Lose release evidence exactly once."""
            self.releases += 1
            raise primary
    lock = Lock()
    mailbox._lock = lock
    with pytest.raises(KeyboardInterrupt) as caught:
        getattr(mailbox, operation)(intent, deadline=horizon())
    assert caught.value is primary
    assert primary.cleanup_mailbox_ticket.state == ("acquiring" if acquire_fault else "releasing")
    assert lock.releases == (0 if acquire_fault else 1)


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
def test_primary_wins_over_release_error(monkeypatch, operation):
    """Retain the original interruption plus independent release diagnostics."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    primary = KeyboardInterrupt("primary")
    release_error = RuntimeError("release ambiguous")
    class Lock:
        """Provide acquisition but fail release without retry."""
        def acquire(self, blocking=False):
            """Prove native custody."""
            return True
        def release(self):
            """Preserve independent finalization uncertainty."""
            raise release_error
    def interrupted(*args):
        """Interrupt inside proven custody."""
        raise primary
    mailbox._lock = Lock()
    monkeypatch.setattr(mailbox, "_admission_locked", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        getattr(mailbox, operation)(intent, deadline=horizon())
    assert caught.value is primary
    assert primary.cleanup_mailbox_release_error is release_error
    assert primary.cleanup_mailbox_ticket is release_error.cleanup_mailbox_ticket
    assert primary.cleanup_mailbox_ticket.state == "releasing"


def test_deterministic_competing_admission(monkeypatch):
    """A contending caller is unavailable, then conflicts with the exact winner."""
    mailbox = CleanupMailbox(1)
    winner, loser = prepared(mailbox), prepared(mailbox)
    original = mailbox._admission_locked
    contention = []
    def interleaved(*args):
        """Attempt the other operation while the winner owns metadata custody."""
        contention.append(mailbox.admit(loser, deadline=horizon()).state)
        return original(*args)
    monkeypatch.setattr(mailbox, "_admission_locked", interleaved)
    assert mailbox.admit(winner, deadline=horizon()).state == "admitted"
    monkeypatch.setattr(mailbox, "_admission_locked", original)
    assert contention == ["unavailable"]
    assert mailbox.admit(loser, deadline=horizon()).state == "conflict"
    assert len(mailbox.snapshot(deadline=horizon()).debts) == 1


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
@pytest.mark.parametrize("boundary,expected", [
    ("acquiring", "acquiring"), ("held", "released"),
    ("releasing", "releasing"), ("released", "released"),
])
def test_ticket_transition_interruptions(operation, boundary, expected):
    """Interrupt native handoff facts without inventing release authority."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    primary = KeyboardInterrupt("ticket transition")
    function = CleanupMailbox._acquire if boundary in ("acquiring", "held") else CleanupMailbox._finish
    lines, start = inspect.getsourcelines(function)
    pattern = {"acquiring": 'ticket.state = "held" if acquired',
               "held": "if not acquired:", "releasing": "self._lock.release()",
               "released": 'ticket.state = "released"'}[boundary]
    line = start + next(i for i, text in enumerate(lines) if pattern in text)
    old = sys.gettrace()
    fired = False
    def trace(frame, event, arg):
        """Inject once at the precise acquisition/finalization boundary."""
        nonlocal fired
        if not fired and frame.f_code is function.__code__ and event == "line" and frame.f_lineno == line:
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            getattr(mailbox, operation)(intent, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired
    # Interruption before the released assignment retains uncertainty, not proof.
    observed = "releasing" if boundary == "released" else expected
    assert primary.cleanup_mailbox_ticket.state == observed
    if mailbox._lock.locked():
        mailbox._lock.release()


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
def test_finish_return_interruption_is_proven_released(operation):
    """A lost finalizer return retains released evidence without another unlock."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    primary = KeyboardInterrupt("finish return")
    old = sys.gettrace()
    fired = False
    def trace(frame, event, arg):
        """Interrupt once after native release and its journal commit."""
        nonlocal fired
        if not fired and frame.f_code is CleanupMailbox._finish.__code__ and event == "return":
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            getattr(mailbox, operation)(intent, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired and primary.cleanup_mailbox_ticket.state == "released"
    assert not mailbox._lock.locked()


@pytest.mark.parametrize("operation", ["admit", "admission_status"])
def test_tampered_exact_intent_rejected(operation):
    """Defensive validation rejects a corrupted frozen record before lock entry."""
    mailbox = CleanupMailbox(1)
    intent = prepared(mailbox)
    object.__setattr__(intent, "receipt", None)
    mailbox._slots = ForbiddenInventory()
    with pytest.raises(ValueError):
        getattr(mailbox, operation)(intent, deadline=horizon())


@pytest.mark.parametrize("operation", ["prepare_admission", "admission_status"])
def test_read_only_lost_return(operation):
    """Preparation/status interruption neither admits nor creates a new identity."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.prepare_admission(0)
    intent = CleanupAdmissionIntent(receipt)
    function = CleanupMailbox.prepare_admission if operation == "prepare_admission" else CleanupMailbox._admission_query
    primary = KeyboardInterrupt("read-only return")
    old = sys.gettrace()
    fired = False
    def trace(frame, event, arg):
        """Discard exactly one return without mutating publication state."""
        nonlocal fired
        if not fired and frame.f_code is function.__code__ and event == "return":
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            if operation == "prepare_admission":
                mailbox.prepare_admission(0)
            else:
                mailbox.admission_status(intent, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired and mailbox.prepare_admission(0) is receipt
    assert mailbox.admission_status(intent, deadline=horizon()).state == "absent"
    assert mailbox.snapshot(deadline=horizon()).debts == ()
