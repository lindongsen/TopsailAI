"""Resource-free bounded mailbox regressions. Author: DawsonLin."""

from dataclasses import FrozenInstanceError, replace
import time
import sys

import pytest

from topsailai.hooks.cleanup_mailbox import (
    CleanupMailbox, CleanupCommand, CleanupDeliveryReceipt, CleanupAdmissionReceipt,
)


def horizon():
    """Supply one absolute test invocation deadline."""
    return time.monotonic() + 1


def delivery_for(mailbox, value):
    """Retain exact consumer tokens for the existing resource-free test flows."""
    if type(value) is CleanupAdmissionReceipt:
        command = next((slot.command for slot in mailbox._slots
                        if slot.receipt is value and slot.command is not None), None)
        value = command or CleanupCommand(value, 1)
    receipts = getattr(mailbox, "_test_deliveries", [])
    for receipt in receipts:
        if receipt.command is value:
            return receipt
    receipt = CleanupDeliveryReceipt(value)
    mailbox._test_deliveries = receipts + [receipt]
    return receipt


class ForbiddenInventory:
    """Fail any attempted protected inventory observation."""

    def __iter__(self):
        """Detect unsafe iteration after failed acquisition."""
        raise AssertionError("inventory observed")

    def __len__(self):
        """Detect unsafe capacity inspection after failed acquisition."""
        raise AssertionError("inventory observed")


@pytest.mark.parametrize("expired", [False, True])
def test_failed_acquisition_reads_no_inventory(expired):
    """Unavailable queries use only preconstructed immutable handle data."""
    mailbox = CleanupMailbox(2)
    mailbox._slots = ForbiddenInventory()
    mailbox._lock.acquire()
    try:
        end = time.monotonic() - 1 if expired else horizon()
        snapshot = mailbox.snapshot(deadline=end)
        assert snapshot.state == "unavailable"
        assert snapshot.debts == (mailbox.handle.unavailable_debt,)
        assert snapshot.debts[0].state == "cleanup_query_unavailable"
        assert mailbox.reserve(deadline=end) is None
    finally:
        mailbox._lock.release()


def test_receipts_precede_commands_and_retain_capacity():
    """Admission is exact, immutable, bounded and never silently recycled."""
    mailbox = CleanupMailbox(1)
    assert mailbox.snapshot(deadline=horizon()).debts == ()
    receipt = mailbox.reserve(deadline=horizon())
    assert receipt is not None
    assert mailbox.reserve(deadline=horizon()) is None
    assert mailbox.snapshot(deadline=horizon()).debts == (receipt.pending_debt,)
    with pytest.raises(FrozenInstanceError):
        receipt.slot_id = "other"
    assert mailbox.submit(CleanupCommand(receipt, 1), deadline=horizon()) == "accepted"
    command = mailbox.take(receipt, delivery=delivery_for(mailbox, receipt), deadline=horizon())
    assert command.receipt is receipt
    assert mailbox.acknowledge(command, delivery=delivery_for(mailbox, command), deadline=horizon()) == "acknowledged"
    assert mailbox.reserve(deadline=horizon()) is None
    assert mailbox.snapshot(deadline=horizon()).debts == (receipt.pending_debt,)


def test_duplicate_stale_and_lost_ack():
    """A command is taken once and lost acknowledgements remain observable."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    assert mailbox.submit(command, deadline=horizon()) == "duplicate"
    assert mailbox.take(receipt, delivery=delivery_for(mailbox, receipt), deadline=horizon()) is command
    assert mailbox.take(receipt, delivery=delivery_for(mailbox, receipt), deadline=horizon()) is None
    assert mailbox.submit(CleanupCommand(receipt, 2), deadline=horizon()) == "busy"
    assert mailbox.acknowledge(replace(command), delivery=delivery_for(mailbox, replace(command)), deadline=horizon()) == "foreign"
    assert mailbox.acknowledge(command, delivery=delivery_for(mailbox, command), deadline=horizon()) == "acknowledged"
    assert mailbox.acknowledge(command, delivery=delivery_for(mailbox, command), deadline=horizon()) == "duplicate"
    assert mailbox.observe(receipt, deadline=horizon()) == 1
    assert mailbox.submit(command, deadline=horizon()) == "duplicate"
    assert mailbox.submit(CleanupCommand(receipt, 3), deadline=horizon()) == "stale"
    assert mailbox.submit(CleanupCommand(receipt, 2), deadline=horizon()) == "accepted"
    assert mailbox.submit(command, deadline=horizon()) == "duplicate"


def test_foreign_and_copied_receipts_rejected():
    """Equal metadata never substitutes for the exact admission receipt."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    foreign = CleanupMailbox(1).reserve(deadline=horizon())
    for other in (foreign, replace(receipt)):
        assert mailbox.submit(CleanupCommand(other, 1), deadline=horizon()) == "foreign"
        assert mailbox.take(other, delivery=delivery_for(mailbox, other), deadline=horizon()) is None
        assert mailbox.observe(other, deadline=horizon()) is None
    assert mailbox.acknowledge(CleanupCommand(receipt, 1), delivery=delivery_for(mailbox, CleanupCommand(receipt, 1)), deadline=horizon()) == "foreign"


@pytest.mark.parametrize("value", [True, 0, -1, 257, "2"])
def test_invalid_capacity(value):
    """Reject malformed or excessive fixed inventories."""
    with pytest.raises(ValueError):
        CleanupMailbox(value)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "2", None])
def test_invalid_deadline_before_inventory(value):
    """Validate deadline shape before any state access."""
    mailbox = CleanupMailbox(1)
    mailbox._slots = ForbiddenInventory()
    with pytest.raises(ValueError):
        mailbox.snapshot(deadline=value)


@pytest.mark.parametrize("sequence", [True, 0, -1, "1", 2**63])
def test_invalid_command_sequence(sequence):
    """Bound immutable command sequences before publication."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    with pytest.raises(ValueError):
        CleanupCommand(receipt, sequence)


def test_busy_mutations_do_not_guess_acknowledgement():
    """A contended publication or ack leaves the same obligation pending."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    mailbox._lock.acquire()
    try:
        assert mailbox.take(receipt, delivery=delivery_for(mailbox, receipt), deadline=horizon()) is None
        assert mailbox.observe(receipt, deadline=horizon()) is None
        assert mailbox.submit(command, deadline=horizon()) == "unavailable"
        assert mailbox.acknowledge(command, delivery=delivery_for(mailbox, command), deadline=horizon()) == "unavailable"
    finally:
        mailbox._lock.release()
    assert mailbox.acknowledge(command, delivery=delivery_for(mailbox, command), deadline=horizon()) == "not_started"
    assert mailbox.take(receipt, delivery=delivery_for(mailbox, receipt), deadline=horizon()) is command
    assert mailbox.acknowledge(command, delivery=delivery_for(mailbox, command), deadline=horizon()) == "acknowledged"


def test_handles_are_disjoint_and_immutable():
    """Unavailable tokens cannot be confused with admitted resource slots."""
    mailbox = CleanupMailbox(1)
    other = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    assert mailbox.handle.query_token != other.handle.query_token
    assert receipt.slot_id != mailbox.handle.query_token
    assert mailbox.handle.unavailable_debt.pid is None
    with pytest.raises(FrozenInstanceError):
        mailbox.handle.query_token = "other"


def test_acquisition_interrupt_is_not_swallowed():
    """Preserve genuine host interruption without fallback observation."""
    mailbox = CleanupMailbox(1)
    error = KeyboardInterrupt()

    class InterruptedLock:
        """Inject a host interruption without acquiring a native lock."""

        def acquire(self, blocking):
            """Raise the exact host interruption before protected reads."""
            raise error

    mailbox._lock = InterruptedLock()
    mailbox._slots = ForbiddenInventory()
    with pytest.raises(KeyboardInterrupt) as caught:
        mailbox.snapshot(deadline=horizon())
    assert caught.value is error


def test_stale_sequence_after_second_ack():
    """Sequences older than the last committed acknowledgement cannot enqueue."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    first = CleanupCommand(receipt, 1)
    for sequence in (1, 2):
        command = CleanupCommand(receipt, sequence)
        assert mailbox.submit(command, deadline=horizon()) == "accepted"
        assert mailbox.take(receipt, delivery=delivery_for(mailbox, receipt), deadline=horizon()) is command
        assert mailbox.acknowledge(command, delivery=delivery_for(mailbox, command), deadline=horizon()) == "acknowledged"
    assert mailbox.submit(first, deadline=horizon()) == "stale"


def test_invalid_receipts_and_commands():
    """Public entry points reject lookalikes before protected inventory access."""
    mailbox = CleanupMailbox(1)
    mailbox._slots = ForbiddenInventory()
    with pytest.raises(ValueError):
        CleanupCommand(None, 1)
    for operation in (mailbox.submit, mailbox.take, mailbox.observe, mailbox.acknowledge):
        with pytest.raises(ValueError):
            if operation in (mailbox.take, mailbox.acknowledge):
                operation(None, delivery=None, deadline=horizon())
            else:
                operation(None, deadline=horizon())


def test_publication_interrupt_retains_receipt(monkeypatch):
    """An interrupted immutable command commit preserves prepublished debt."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    error = KeyboardInterrupt()
    original = mailbox._publish

    def interrupted(index, slot):
        """Inject interruption after commit but before caller acknowledgement."""
        original(index, slot)
        raise error

    monkeypatch.setattr(mailbox, "_publish", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        mailbox.submit(command, deadline=horizon())
    assert caught.value is error
    monkeypatch.setattr(mailbox, "_publish", original)
    assert mailbox.snapshot(deadline=horizon()).debts == (receipt.pending_debt,)
    assert mailbox.submit(command, deadline=horizon()) == "duplicate"
    assert mailbox.take(receipt, delivery=delivery_for(mailbox, receipt), deadline=horizon()) is command


def test_native_release_fault_never_returns_admission():
    """Release uncertainty propagates; no successful resource authorization exists."""
    mailbox = CleanupMailbox(1)
    error = RuntimeError("synthetic release uncertainty")

    class FaultLock:
        """Fail release after a proven acquisition without touching native locks."""

        def acquire(self, blocking):
            """Model one exact successful ticket acquisition."""
            return True

        def release(self):
            """Report uncertainty instead of silently claiming departure."""
            raise error

    mailbox._lock = FaultLock()
    with pytest.raises(RuntimeError) as caught:
        mailbox.reserve(deadline=horizon())
    assert caught.value is error
    assert len(mailbox._slots) == 1
    assert mailbox._slots[0].receipt.pending_debt.state == "admission_pending"


def test_deadline_expiring_during_acquisition(monkeypatch):
    """Release a late ticket without observing the protected inventory."""
    from types import SimpleNamespace
    from topsailai.hooks import cleanup_mailbox

    mailbox = CleanupMailbox(1)
    mailbox._slots = ForbiddenInventory()
    ticks = iter((1.0, 3.0))
    monkeypatch.setattr(cleanup_mailbox, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    assert mailbox.snapshot(deadline=2).state == "unavailable"
    assert not mailbox._lock.locked()


def test_foreign_acknowledgement():
    """A foreign slot cannot acknowledge any command in this inventory."""
    mailbox = CleanupMailbox(1)
    other = CleanupMailbox(1).reserve(deadline=horizon())
    assert mailbox.acknowledge(CleanupCommand(other, 1), delivery=delivery_for(mailbox, CleanupCommand(other, 1)), deadline=horizon()) == "foreign"


@pytest.mark.parametrize("operation", ["reserve", "snapshot", "submit", "take", "acknowledge", "observe", "delivery_status"])
@pytest.mark.parametrize("boundary", ["return", "clock"])
def test_acquisition_handoff_interruption_releases_exact_lock(monkeypatch, operation, boundary):
    """A single interrupt crosses acquisition handoff without losing finalization."""
    from types import SimpleNamespace
    from topsailai.hooks import cleanup_mailbox

    mailbox = CleanupMailbox(2)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    delivery = CleanupDeliveryReceipt(command)
    mailbox.submit(command, deadline=horizon())
    mailbox.take(receipt, delivery=delivery, deadline=horizon())
    calls = {
        "reserve": lambda: mailbox.reserve(deadline=end),
        "snapshot": lambda: mailbox.snapshot(deadline=end),
        "submit": lambda: mailbox.submit(command, deadline=end),
        "take": lambda: mailbox.take(receipt, delivery=delivery, deadline=end),
        "acknowledge": lambda: mailbox.acknowledge(command, delivery=delivery, deadline=end),
        "observe": lambda: mailbox.observe(receipt, deadline=end),
        "delivery_status": lambda: mailbox.delivery_status(delivery, deadline=end),
    }
    end = horizon()
    error = KeyboardInterrupt()
    old_trace = sys.gettrace()
    fired = False

    def trace(frame, event, arg):
        """Disarm before raising at the exact successful acquisition return."""
        nonlocal fired
        if not fired and frame.f_code is CleanupMailbox._acquire.__code__ and event == "return":
            fired = True
            raise error
        return trace

    ticks = 0
    original_clock = time.monotonic

    def clock():
        """Interrupt the first post-acquisition deadline observation once."""
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            raise error
        return original_clock()

    if boundary == "clock":
        monkeypatch.setattr(cleanup_mailbox, "time", SimpleNamespace(monotonic=clock))
    else:
        sys.settrace(trace)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            calls[operation]()
        assert caught.value is error
    finally:
        sys.settrace(old_trace)
    assert not mailbox._lock.locked()
    assert mailbox.snapshot(deadline=horizon()).state == "current"


@pytest.mark.parametrize("operation", ["take", "acknowledge"])
@pytest.mark.parametrize("after", [False, True])
def test_delivery_commit_interruption_reconciles_exact_receipt(monkeypatch, operation, after):
    """Preheld identity recovers commit facts without replaying consumer work."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    delivery = CleanupDeliveryReceipt(command)
    mailbox.submit(command, deadline=horizon())
    if operation == "acknowledge":
        mailbox.take(receipt, delivery=delivery, deadline=horizon())
    error = KeyboardInterrupt()
    original = mailbox._publish

    def interrupted(index, slot):
        """Inject once around the atomic slot commit then permit reconciliation."""
        monkeypatch.setattr(mailbox, "_publish", original)
        if after:
            original(index, slot)
        raise error

    monkeypatch.setattr(mailbox, "_publish", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        if operation == "take":
            mailbox.take(receipt, delivery=delivery, deadline=horizon())
        else:
            mailbox.acknowledge(command, delivery=delivery, deadline=horizon())
    assert caught.value is error
    expected = ("taken" if after else "ready") if operation == "take" else (
        "acknowledged" if after else "taken")
    assert mailbox.delivery_status(delivery, deadline=horizon()) == expected
    assert mailbox.delivery_status(replace(delivery), deadline=horizon()) in ("ready", "foreign")
    if expected == "ready":
        assert mailbox.take(receipt, delivery=delivery, deadline=horizon()) is command
    else:
        assert mailbox.take(receipt, delivery=delivery, deadline=horizon()) is None
    assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) in (
        "acknowledged", "duplicate")
    assert mailbox.delivery_status(delivery, deadline=horizon()) == "acknowledged"
    assert mailbox.snapshot(deadline=horizon()).debts == (receipt.pending_debt,)
    assert mailbox.reserve(deadline=horizon()) is None


def test_unknown_acquisition_retains_quarantine_ticket():
    """An unknown native outcome never authorizes unlocking a foreign lock."""
    mailbox = CleanupMailbox(1)
    error = KeyboardInterrupt()

    class UncertainLock:
        """Model acquisition whose successful native return was lost."""

        def acquire(self, blocking):
            """Lose evidence after possibly acquiring the mutex."""
            raise error

        def release(self):
            """Reject an unsafe release attempt under uncertain authority."""
            pytest.fail("unknown acquisition was released")

    mailbox._lock = UncertainLock()
    mailbox._slots = ForbiddenInventory()
    with pytest.raises(KeyboardInterrupt) as caught:
        mailbox.snapshot(deadline=horizon())
    assert caught.value is error
    assert error.cleanup_mailbox_ticket.state == "acquiring"
    assert error.cleanup_mailbox_ticket.handle is mailbox.handle
    assert error.cleanup_mailbox_ticket.handle.unavailable_debt.state == "cleanup_query_unavailable"


def test_delivery_identity_and_unavailable_boundaries():
    """Copies cannot take or complete another consumer's committed delivery."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    delivery = CleanupDeliveryReceipt(command)
    mailbox.submit(command, deadline=horizon())
    with pytest.raises(ValueError):
        CleanupDeliveryReceipt(None)
    for operation in (mailbox.take, mailbox.acknowledge):
        with pytest.raises(ValueError):
            operation(receipt if operation == mailbox.take else command,
                      delivery=None, deadline=horizon())
    with pytest.raises(ValueError):
        mailbox.delivery_status(None, deadline=horizon())
    assert mailbox.take(receipt, delivery=CleanupDeliveryReceipt(replace(command)), deadline=horizon()) is None
    mailbox.take(receipt, delivery=delivery, deadline=horizon())
    assert mailbox.acknowledge(command, delivery=replace(delivery), deadline=horizon()) == "foreign"
    foreign = CleanupDeliveryReceipt(CleanupCommand(CleanupMailbox(1).reserve(deadline=horizon()), 1))
    assert mailbox.delivery_status(foreign, deadline=horizon()) == "foreign"
    mailbox._lock.acquire()
    try:
        mailbox._slots = ForbiddenInventory()
        assert mailbox.delivery_status(delivery, deadline=horizon()) == "unavailable"
    finally:
        mailbox._lock.release()


def test_release_uncertainty_preserves_primary(monkeypatch):
    """Finalization diagnostics retain the original host interruption identity."""
    mailbox = CleanupMailbox(1)
    primary = KeyboardInterrupt()
    release_error = RuntimeError("release uncertain")

    class FaultLock:
        """Supply proven acquisition followed by uncertain release."""

        def acquire(self, blocking):
            """Prove this invocation acquired its own lock."""
            return True

        def release(self):
            """Lose release evidence without another attempted unlock."""
            raise release_error

    def interrupted(deadline, ticket):
        """Interrupt after proven acquisition while finalization is armed."""
        ticket.state = "held"
        raise primary

    mailbox._lock = FaultLock()
    monkeypatch.setattr(mailbox, "_acquire", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        mailbox.snapshot(deadline=horizon())
    assert caught.value is primary
    assert primary.cleanup_mailbox_release_error is release_error
    assert primary.cleanup_mailbox_ticket.state == "releasing"
    assert release_error.cleanup_mailbox_ticket is primary.cleanup_mailbox_ticket


def test_ambiguous_native_acquisition_never_releases(monkeypatch):
    """A lost native return retains explicit uncertainty and a real held lock."""
    mailbox = CleanupMailbox(1)
    native = mailbox._lock
    error = KeyboardInterrupt()

    class LostReturnLock:
        """Acquire a real lock then lose return evidence at the boundary."""

        def acquire(self, blocking):
            """Inject once after native mutation before ticket confirmation."""
            assert native.acquire(blocking=blocking)
            raise error

        def release(self):
            """Forbid mailbox recovery using uncertain native ownership."""
            pytest.fail("unsafe unlock")

    monkeypatch.setattr(mailbox, "_lock", LostReturnLock())
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            mailbox.snapshot(deadline=horizon())
        assert caught.value is error
        assert native.locked()
        assert error.cleanup_mailbox_ticket.state == "acquiring"
    finally:
        # The fixture, not mailbox recovery, owns this explicitly acquired lock.
        native.release()


def test_completion_rejects_copied_command():
    """Even a completed sequence cannot grant copied-command authority."""
    mailbox = CleanupMailbox(1)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    delivery = CleanupDeliveryReceipt(command)
    mailbox.submit(command, deadline=horizon())
    mailbox.take(receipt, delivery=delivery, deadline=horizon())
    mailbox.acknowledge(command, delivery=delivery, deadline=horizon())
    assert mailbox.acknowledge(replace(command), delivery=delivery, deadline=horizon()) == "foreign"


@pytest.mark.parametrize("operation", ["reserve", "snapshot", "submit", "take", "acknowledge", "observe", "delivery_status"])
@pytest.mark.parametrize("boundary", ["entry", "primary", "try", "caller_guard", "caller_finish"])
def test_first_finalizer_interrupt_retains_exact_custody(operation, boundary):
    """Carry prearmed authority across first interruption of finalizer entry."""
    import inspect

    mailbox = CleanupMailbox(2)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    delivery = CleanupDeliveryReceipt(command)
    mailbox.submit(command, deadline=horizon())
    mailbox.take(receipt, delivery=delivery, deadline=horizon())
    end = horizon()
    calls = {
        "reserve": lambda: mailbox.reserve(deadline=end),
        "snapshot": lambda: mailbox.snapshot(deadline=end),
        "submit": lambda: mailbox.submit(command, deadline=end),
        "take": lambda: mailbox.take(receipt, delivery=delivery, deadline=end),
        "acknowledge": lambda: mailbox.acknowledge(command, delivery=delivery, deadline=end),
        "observe": lambda: mailbox.observe(receipt, deadline=end),
        "delivery_status": lambda: mailbox.delivery_status(delivery, deadline=end),
    }
    lines, start = inspect.getsourcelines(CleanupMailbox._finish)
    target = None
    caller_code = getattr(CleanupMailbox, operation).__code__
    if boundary.startswith("caller_"):
        lines, start = inspect.getsourcelines(getattr(CleanupMailbox, operation))
        text = {"caller_guard": "try:",
                "caller_finish": "self._finish(ticket)"}[boundary]
        matches = [i for i, line in enumerate(lines) if line.strip() == text]
        target = start + matches[-1]
    elif boundary != "entry":
        text = "primary = sys.exception()" if boundary == "primary" else "try:"
        target = start + next(i for i, line in enumerate(lines) if line.strip() == text)
    error = KeyboardInterrupt()
    old_trace = sys.gettrace()
    tickets = []

    def trace(frame, event, arg):
        """Disarm before raising the first interruption at the target boundary."""
        expected_code = caller_code if boundary.startswith("caller_") else CleanupMailbox._finish.__code__
        if (not tickets and frame.f_code is expected_code
                and ((boundary == "entry" and event == "call")
                     or (event == "line" and frame.f_lineno == target))):
            tickets.append(frame.f_locals["ticket"])
            raise error
        return trace

    sys.settrace(trace)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            calls[operation]()
        assert caught.value is error
    finally:
        sys.settrace(old_trace)
    try:
        assert len(tickets) == 1
        assert tickets[0].handle is mailbox.handle
        if boundary == "caller_guard":
            assert tickets[0].state == "unattempted"
            assert not mailbox._lock.locked()
            assert not hasattr(error, "cleanup_mailbox_ticket")
            return
        assert error.cleanup_mailbox_ticket is tickets[0]
        assert tickets[0].state == "held"
        assert mailbox._lock.locked()
        unavailable = mailbox.snapshot(deadline=horizon())
        assert unavailable.state == "unavailable"
        assert unavailable.debts == (mailbox.handle.unavailable_debt,)
    finally:
        # This fixture owns the known single-thread acquisition, not recovery.
        if mailbox._lock.locked():
            mailbox._lock.release()
    assert mailbox.snapshot(deadline=horizon()).state == "current"


@pytest.mark.parametrize("operation", ["reserve", "snapshot", "submit", "take", "acknowledge", "observe", "delivery_status"])
def test_finalizer_entry_fault_double_retains_ticket(monkeypatch, operation):
    """Exercise caller guards without tracer interference with coverage."""
    mailbox = CleanupMailbox(2)
    receipt = mailbox.reserve(deadline=horizon())
    command = CleanupCommand(receipt, 1)
    delivery = CleanupDeliveryReceipt(command)
    mailbox.submit(command, deadline=horizon())
    mailbox.take(receipt, delivery=delivery, deadline=horizon())
    error = KeyboardInterrupt()
    tickets = []
    original = mailbox._finish

    def interrupted(ticket):
        """Disarm before interrupting the first finalizer invocation."""
        monkeypatch.setattr(mailbox, "_finish", original)
        tickets.append(ticket)
        raise error

    calls = {
        "reserve": lambda: mailbox.reserve(deadline=horizon()),
        "snapshot": lambda: mailbox.snapshot(deadline=horizon()),
        "submit": lambda: mailbox.submit(command, deadline=horizon()),
        "take": lambda: mailbox.take(receipt, delivery=delivery, deadline=horizon()),
        "acknowledge": lambda: mailbox.acknowledge(command, delivery=delivery, deadline=horizon()),
        "observe": lambda: mailbox.observe(receipt, deadline=horizon()),
        "delivery_status": lambda: mailbox.delivery_status(delivery, deadline=horizon()),
    }
    monkeypatch.setattr(mailbox, "_finish", interrupted)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            calls[operation]()
        assert caught.value is error
        assert error.cleanup_mailbox_ticket is tickets[0]
        assert tickets[0].state == "held"
        assert mailbox._lock.locked()
    finally:
        # Only this fixture may release its known single-thread acquisition.
        mailbox._lock.release()
