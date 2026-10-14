"""Public resource-free multi-owner custody composition. Author: DawsonLin."""

from dataclasses import replace
import time

import pytest

from topsailai.hooks.cleanup_budget import CleanupBudget
from topsailai.hooks.cleanup_mailbox import (
    CleanupAdmissionIntent, CleanupCommand, CleanupCommandProducerIntent,
    CleanupCommandSealIntent, CleanupDeliveryReceipt, CleanupMailbox,
)
from topsailai.hooks.cleanup_publication import (
    CleanupPublication, PublicationAction, PublicationIntent,
    RetirementEvidence, RetirementIntent,
)
from topsailai.hooks.process_state import LaunchRecord


def horizon():
    """Use a finite observation allowance without sleeps or renewed execution D."""
    return time.monotonic() + 5


def pair():
    """Prehold two independent inert associations in the same bounded journals."""
    mailbox = CleanupMailbox(2)
    journal = CleanupPublication(mailbox, 2, backend=object(),
                                 profile="custodian_v1", cleanup_owner=object())
    intents = []
    for index in range(2):
        receipt = journal.prepare(index)
        intents.append(PublicationIntent(
            receipt, CleanupAdmissionIntent(receipt.admission), LaunchRecord("inert"),
            f"synthetic-{index}", object(), object(), CleanupBudget(horizon(), horizon()+1),
        ))
    return mailbox, journal, tuple(intents)


def step(journal, intent, name, **kwargs):
    """Commit synthetic metadata using the original actor, never a resource action."""
    producer_names = ("admission_handback", "start", "resources", "transfer", "producer_handback")
    owner_names = ("owner_admit", "reader_grant", "reader_handback", "never_started")
    actor = intent.producer if name in producer_names else (
        intent.owner if name in owner_names else journal.handle.cleanup_owner
    )
    action = PublicationAction(intent, name, actor, **kwargs)
    assert journal.transition(action, deadline=horizon()).state == "committed"
    return action


def start(journal, intent):
    """Join and prehold admission handback before synthetic start."""
    assert journal.publish(intent, deadline=horizon()).state == "committed"
    for name in ("owner_admit", "admission_handback", "start"):
        step(journal, intent, name)


def owned(journal, intent):
    """Describe zero real resources and transfer only synthetic metadata."""
    start(journal, intent)
    for name in ("resources", "transfer", "producer_handback"):
        step(journal, intent, name)


def certificate(journal, intent, seal, kind, delivery=None):
    """Prehold exact synthetic retirement authority without native evidence."""
    retirement = RetirementIntent(intent, intent.producer, journal.handle.cleanup_owner, seal)
    return RetirementEvidence(retirement, kind, delivery)


def lose_once(monkeypatch, obj, name, primary):
    """Lose one public return after its real commit, retaining exact exception identity."""
    original = getattr(obj, name)
    calls = []
    armed = True

    def lost_return(*args, **kwargs):
        """Disarm before raising so reconciliation cannot repeat the interruption."""
        nonlocal armed
        calls.append((args, kwargs))
        result = original(*args, **kwargs)
        if armed:
            armed = False
            raise primary
        return result

    monkeypatch.setattr(obj, name, lost_return)
    return calls


def assert_primary(primary, call):
    """Check identity and the public injection frame without formatting exceptions."""
    with pytest.raises(KeyboardInterrupt) as caught:
        call()
    assert caught.value is primary
    frames = []
    trace = caught.value.__traceback__
    while trace is not None:
        frames.append(trace.tb_frame.f_code.co_name)
        trace = trace.tb_next
    assert "lost_return" in frames


def test_interleaved_split_admission_reconciles_without_replay(monkeypatch):
    """A second owner progresses while the first retains a lost admission return."""
    mailbox, journal, (first, second) = pair()
    primary = KeyboardInterrupt("synthetic admission return")
    calls = lose_once(monkeypatch, mailbox, "admit", primary)
    assert_primary(primary, lambda: journal.publish(first, deadline=horizon()))
    assert journal.observe(first, deadline=horizon()).state == "pending"
    assert journal.publish(second, deadline=horizon()).state == "committed"
    assert journal.reconcile(first, deadline=horizon()).state == "committed"
    assert sum(args[0] is first.admission for args, _ in calls) == 1
    for intent in (first, second):
        state = journal.snapshot(intent.owner, deadline=horizon()).entries[0]
        assert state.intent is intent and state.intent.record is intent.record
        assert state.intent.budget is intent.budget
        assert mailbox.admission_status(intent.admission, deadline=horizon()).state == "admitted"
        assert journal.observe(replace(intent), deadline=horizon()).state == "conflict"
        assert journal.observe(replace(intent, receipt=replace(intent.receipt)), deadline=horizon()).state == "foreign"
    assert journal.snapshot(object(), deadline=horizon()).entries == ()
    assert len(mailbox.snapshot(deadline=horizon()).debts) == 2


def test_empty_lost_retirement_keeps_foreign_owner_and_capacity(monkeypatch):
    """Terminal metadata is not absence, full cleanup or recyclable admission."""
    mailbox, journal, (first, second) = pair()
    for intent in (first, second):
        start(journal, intent)
    seal = CleanupCommandSealIntent(first.receipt.admission)
    evidence = certificate(journal, first, seal, "empty_failure")
    assert mailbox.seal_commands(seal, deadline=horizon()).state == "quiescent"
    primary = KeyboardInterrupt("retire return")
    calls = lose_once(monkeypatch, journal, "retire_without_reader", primary)
    assert_primary(primary, lambda: journal.retire_without_reader(evidence, deadline=horizon()))
    state = journal.observe(first, deadline=horizon()).entries[0]
    assert state.stage == "terminal" and state.retirement is evidence
    assert len(calls) == 1
    assert journal.observe(second, deadline=horizon()).state == "start_pending"
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "duplicate"
    assert journal.retire_without_reader(replace(evidence), deadline=horizon()).state == "conflict"
    for intent in (first, second):
        snapshot = journal.snapshot(intent.owner, deadline=horizon())
        assert len(snapshot.entries) == 1 and snapshot.entries[0].intent is intent
        assert snapshot.debts == (intent.receipt.admission.pending_debt,)
    assert mailbox.reserve(deadline=horizon()) is None
    assert len(mailbox.snapshot(deadline=horizon()).debts) == 2


@pytest.mark.parametrize("boundary", ["take", "acknowledge"])
def test_lost_delivery_return_and_foreign_pending_owner(monkeypatch, boundary):
    """Exact status recovers delivery without replay or executing any command work."""
    mailbox, journal, (first, second) = pair()
    for intent in (first, second):
        owned(journal, intent)
    command = CleanupCommand(first.receipt.admission, 1)
    delivery = CleanupDeliveryReceipt(command)
    foreign = CleanupCommand(second.receipt.admission, 1)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    assert mailbox.submit(foreign, deadline=horizon()) == "accepted"
    primary = KeyboardInterrupt(boundary)
    calls = lose_once(monkeypatch, mailbox, boundary, primary)
    if boundary == "take":
        assert_primary(primary, lambda: mailbox.take(command.receipt, delivery=delivery, deadline=horizon()))
        assert mailbox.delivery_status(delivery, deadline=horizon()) == "taken"
        assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
    else:
        assert mailbox.take(command.receipt, delivery=delivery, deadline=horizon()) is command
        assert_primary(primary, lambda: mailbox.acknowledge(command, delivery=delivery, deadline=horizon()))
    assert mailbox.delivery_status(delivery, deadline=horizon()) == "acknowledged"
    assert len(calls) == 1
    assert mailbox.delivery_status(replace(delivery), deadline=horizon()) == "foreign"
    assert journal.observe(first, deadline=horizon()).state == "owned"
    step(journal, first, "settle")
    seal = CleanupCommandSealIntent(first.receipt.admission)
    assert mailbox.seal_commands(seal, deadline=horizon()).state == "quiescent"
    evidence = certificate(journal, first, seal, "settled_no_reader", delivery)
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "committed"
    other_seal = CleanupCommandSealIntent(second.receipt.admission)
    assert mailbox.seal_commands(other_seal, deadline=horizon()).state == "sealed_pending"
    assert journal.observe(second, deadline=horizon()).state == "owned"
    assert mailbox.delivery_status(CleanupDeliveryReceipt(foreign), deadline=horizon()) == "ready"


def test_reader_handback_after_seal_uses_genuine_terminal_route():
    """Global seal stops new starts but does not mint no-reader retirement evidence."""
    mailbox, journal, (first, second) = pair()
    owned(journal, first)
    assert journal.publish(second, deadline=horizon()).state == "committed"
    step(journal, first, "reader_grant")
    seal = CleanupCommandSealIntent(first.receipt.admission)
    command = CleanupCommand(first.receipt.admission, 1)
    delivery = CleanupDeliveryReceipt(command)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    assert mailbox.take(command.receipt, delivery=delivery, deadline=horizon()) is command
    assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
    assert mailbox.seal_commands(seal, deadline=horizon()).state == "quiescent"
    evidence = certificate(journal, first, seal, "settled_no_reader", delivery)
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "blocked"
    assert journal.seal(deadline=horizon()).state == "sealed"
    for name in ("owner_admit", "admission_handback"):
        step(journal, second, name)
    assert journal.transition(PublicationAction(second, "start", second.producer), deadline=horizon()).state == "blocked"
    step(journal, first, "reader_handback")
    step(journal, first, "settle")
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "blocked"
    step(journal, first, "terminal", delivery=delivery, command_seal=seal)
    assert journal.observe(first, deadline=horizon()).entries[0].retirement is None
    assert journal.observe(second, deadline=horizon()).state == "joined"


def test_newer_command_and_active_producer_block_composed_retirement():
    """Old delivery and command quiescence never substitute for current settlement."""
    mailbox, journal, (first, second) = pair()
    owned(journal, first)
    start(journal, second)
    step(journal, first, "settle")
    producer = CleanupCommandProducerIntent(first.receipt.admission)
    assert mailbox.admit_command_producer(producer, deadline=horizon()).state == "active"
    deliveries = []
    for sequence in (1, 2):
        command = CleanupCommand(first.receipt.admission, sequence)
        delivery = CleanupDeliveryReceipt(command)
        assert mailbox.submit(command, deadline=horizon()) == "accepted"
        assert mailbox.take(command.receipt, delivery=delivery, deadline=horizon()) is command
        if sequence == 1:
            assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
        deliveries.append(delivery)
    seal = CleanupCommandSealIntent(first.receipt.admission)
    evidence = certificate(journal, first, seal, "settled_no_reader", deliveries[0])
    assert mailbox.seal_commands(seal, deadline=horizon()).state == "sealed_pending"
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "settled"
    latest = deliveries[1]
    assert mailbox.acknowledge(latest.command, delivery=latest, deadline=horizon()) == "acknowledged"
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "settled"
    assert mailbox.handback_command_producer(producer, deadline=horizon()).state == "returned"
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "settled"
    assert journal.retire_without_reader(replace(evidence, delivery=latest), deadline=horizon()).state == "committed"
    assert journal.observe(second, deadline=horizon()).state == "start_pending"


@pytest.mark.parametrize("boundary", ["publish", "admit"])
def test_expired_original_execution_cannot_be_renewed_after_lost_return(monkeypatch, boundary):
    """Fresh observation horizons do not revive expired D or erase foreign debt."""
    mailbox, journal, (original, second) = pair()
    expired = time.monotonic() - 1
    first = replace(original, budget=CleanupBudget(expired, horizon()))
    target = journal if boundary == "publish" else mailbox
    primary = KeyboardInterrupt(boundary)
    calls = lose_once(monkeypatch, target, boundary, primary)
    assert_primary(primary, lambda: journal.publish(first, deadline=horizon()))
    assert journal.publish(second, deadline=horizon()).state == "committed"
    assert journal.reconcile(first, deadline=horizon()).state in ("committed", "joined")
    for name in ("owner_admit", "admission_handback"):
        step(journal, first, name)
    assert journal.transition(PublicationAction(first, "start", first.producer), deadline=horizon()).state == "unavailable"
    assert first.budget.execution_deadline == expired
    assert journal.observe(first, deadline=expired).state == "unavailable"
    assert journal.snapshot(first.owner, deadline=expired).debts == (journal.handle.unavailable_debt,)
    assert journal.observe(first, deadline=horizon()).state == "joined"
    assert journal.snapshot(second.owner, deadline=horizon()).entries[0].intent is second
    assert sum(args[0] is (first if boundary == "publish" else first.admission) for args, _ in calls) == 1
    _, other, (unpublished, _) = pair()
    assert other.observe(unpublished, deadline=horizon()).state == "absent"
    assert mailbox.reserve(deadline=horizon()) is None
