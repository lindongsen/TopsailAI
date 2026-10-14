"""Synthetic no-reader retirement regressions. Author: DawsonLin."""

from dataclasses import replace
import inspect
import sys
import time
from types import SimpleNamespace

import pytest

import topsailai.hooks.cleanup_publication as module
from topsailai.hooks.cleanup_budget import CleanupBudget
from topsailai.hooks.cleanup_mailbox import (
    CleanupAdmissionIntent, CleanupMailbox, CleanupCommand, CleanupDeliveryReceipt,
    CleanupCommandSealIntent, CleanupCommandProducerIntent,
)
from topsailai.hooks.cleanup_publication import (
    CleanupPublication, PublicationIntent, PublicationAction,
    RetirementIntent, RetirementEvidence,
)
from topsailai.hooks.process_state import LaunchRecord


def horizon():
    """Use one finite observation allowance without sleeps."""
    return time.monotonic() + 5


def fixture(kind="empty_failure", stage=None):
    """Prehold certificates before synthetic start; acquire no native resources."""
    mailbox = CleanupMailbox(1)
    journal = CleanupPublication(mailbox, 1, backend=object(), profile="custodian_v1",
                                 cleanup_owner=object())
    receipt = journal.prepare(0)
    intent = PublicationIntent(receipt, CleanupAdmissionIntent(receipt.admission),
                               LaunchRecord("inert"), "debt", object(), object(),
                               CleanupBudget(horizon(), horizon()+1))
    seal = CleanupCommandSealIntent(receipt.admission)
    retirement = RetirementIntent(intent, intent.producer, journal.handle.cleanup_owner, seal)
    if stage == "absent":
        return mailbox, journal, intent, RetirementEvidence(retirement, kind)
    assert journal.publish(intent, deadline=horizon()).state == "committed"
    steps = ["owner_admit", "admission_handback", "start"]
    if kind == "settled_no_reader":
        steps += ["resources", "transfer", "producer_handback", "settle"]
    if stage == "joined":
        steps = steps[:2]
    for name in steps:
        step(journal, intent, name)
        if name == stage:
            break
    delivery = complete(mailbox, intent, 1) if kind == "settled_no_reader" else None
    assert mailbox.seal_commands(seal, deadline=horizon()).state == "quiescent"
    return mailbox, journal, intent, RetirementEvidence(retirement, kind, delivery)


def step(journal, intent, name):
    """Commit one original action with its exact actor."""
    actor = intent.producer if name in (
        "admission_handback", "start", "resources", "transfer", "producer_handback"
    ) else intent.owner if name in ("owner_admit", "reader_grant", "reader_handback") else journal.handle.cleanup_owner
    action = PublicationAction(intent, name, actor)
    assert journal.transition(action, deadline=horizon()).state == "committed"
    return action


def complete(mailbox, intent, sequence):
    """Acknowledge a command without pretending to settle resource obligations."""
    command = CleanupCommand(intent.receipt.admission, sequence)
    delivery = CleanupDeliveryReceipt(command)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    assert mailbox.take(command.receipt, delivery=delivery, deadline=horizon()) is command
    assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
    return delivery


@pytest.mark.parametrize("kind", ["empty_failure", "settled_no_reader"])
def test_legal_retirement_duplicate_conflict_and_capacity(kind):
    """Retain exact evidence and all tombstones without dummy actions/recycling."""
    mailbox, journal, intent, evidence = fixture(kind)
    before = journal.observe(intent, deadline=horizon()).entries[0]
    result = journal.retire_without_reader(evidence, deadline=horizon())
    assert result.state == "committed"
    state = result.entries[0]
    assert state.stage == "terminal" and state.retirement is evidence
    assert state.actions is before.actions
    assert state.producers == state.readers == 0 and state.mutation_owner is None
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "duplicate"
    assert journal.retire_without_reader(replace(evidence), deadline=horizon()).state == "conflict"
    assert journal.retire_without_reader(replace(evidence, intent=replace(evidence.intent)), deadline=horizon()).state == "conflict"
    assert mailbox.reserve(deadline=horizon()) is None
    assert journal.snapshot(intent.owner, deadline=horizon()).debts
    assert journal.snapshot(object(), deadline=horizon()).entries == ()
    assert journal.observe(intent, deadline=horizon()).entries[0].retirement is evidence


@pytest.mark.parametrize("field,value", [("publication", None), ("producer", None),
    ("cleanup_owner", None), ("command_seal", None)])
def test_intent_shape(field, value):
    """Malformed shapes fail before locking."""
    _, _, _, evidence = fixture()
    with pytest.raises(ValueError):
        replace(evidence.intent, **{field: value})


@pytest.mark.parametrize("field,value", [("intent", None), ("kind", "unknown"),
    ("kind", None), ("delivery", object())])
def test_evidence_shape(field, value):
    """Unknown obligations cannot be represented by an empty certificate."""
    _, journal, _, evidence = fixture()
    with pytest.raises(ValueError):
        replace(evidence, **{field: value})
    with pytest.raises(ValueError):
        journal.retire_without_reader(object(), deadline=horizon())


def test_empty_delivery_forbidden():
    """The empty path must not manufacture command delivery."""
    _, _, intent, evidence = fixture()
    with pytest.raises(ValueError):
        replace(evidence, delivery=CleanupDeliveryReceipt(CleanupCommand(intent.receipt.admission, 1)))


@pytest.mark.parametrize("field", ["producer", "cleanup_owner", "publication", "receipt", "seal", "foreign_seal"])
def test_exact_authorities(field):
    """Reject copied/foreign identities instead of comparing dataclass values."""
    _, journal, intent, evidence = fixture()
    certificate = evidence.intent
    if field in ("producer", "cleanup_owner"):
        certificate = replace(certificate, **{field: object()})
    elif field == "publication":
        certificate = replace(certificate, publication=replace(intent))
    elif field == "receipt":
        copied = replace(intent, receipt=replace(intent.receipt))
        certificate = replace(certificate, publication=copied)
    else:
        seal = replace(certificate.command_seal) if field == "seal" else CleanupCommandSealIntent(CleanupMailbox(1).prepare_admission(0))
        certificate = replace(certificate, command_seal=seal)
    result = journal.retire_without_reader(replace(evidence, intent=certificate), deadline=horizon())
    assert result.state in ("foreign", "conflict", "start_pending")
    assert journal.observe(intent, deadline=horizon()).entries[0].retirement is None


@pytest.mark.parametrize("stage", ["absent", "joined", "resources", "transfer", "producer_handback"])
def test_illegal_empty_lifecycle(stage):
    """Empty certificates cannot discard started resources or transferred custody."""
    _, journal, intent, evidence = fixture(stage="joined" if stage == "joined" else "absent" if stage == "absent" else None)
    if stage not in ("absent", "joined"):
        for name in ("resources", "transfer", "producer_handback"):
            step(journal, intent, name)
            if name == stage:
                break
    result = journal.retire_without_reader(evidence, deadline=horizon())
    assert result.state == ("absent" if stage == "absent" else "blocked")


@pytest.mark.parametrize("field,value", [("owner_admitted", False), ("admission_producers", 1),
    ("producers", 0), ("readers", 1), ("mutation_owner", None)])
def test_empty_all_predicates(field, value):
    """Synthetic inconsistent metadata must not bypass any count/owner predicate."""
    _, journal, _, evidence = fixture()
    journal._slots = (replace(journal._slots[0], **{field: value}),)
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "blocked"


@pytest.mark.parametrize("variant", ["missing", "copied", "foreign"])
def test_settled_delivery_identity(variant):
    """Only the exact latest acknowledged delivery can authorize no-reader retirement."""
    _, journal, _, evidence = fixture("settled_no_reader")
    delivery = None if variant == "missing" else replace(evidence.delivery)
    if variant == "foreign":
        delivery = CleanupDeliveryReceipt(CleanupCommand(CleanupMailbox(1).prepare_admission(0), 1))
    result = journal.retire_without_reader(replace(evidence, delivery=delivery), deadline=horizon())
    assert result.state in ("foreign", "blocked", "settled")


@pytest.mark.parametrize("readers", ["active", "returned"])
def test_reader_history_rejected(readers):
    """Real reader paths remain on the original genuine handback terminal path."""
    _, journal, intent, evidence = fixture("settled_no_reader", stage="producer_handback")
    step(journal, intent, "reader_grant")
    if readers == "returned":
        step(journal, intent, "reader_handback")
        step(journal, intent, "settle")
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "blocked"


@pytest.mark.parametrize("kind", ["empty_failure", "settled_no_reader"])
def test_pending_commands_and_latest_delivery(kind):
    """Sealing with active producer/new command is not command quiescence."""
    mailbox, journal, intent, evidence = fixture(kind)
    # A fresh open mailbox/journal permits the real command lifecycle before sealing.
    mailbox, journal, intent, evidence = fixture(kind, stage="absent")
    journal.publish(intent, deadline=horizon())
    for name in ("owner_admit", "admission_handback", "start"):
        step(journal, intent, name)
    if kind == "settled_no_reader":
        for name in ("resources", "transfer", "producer_handback", "settle"):
            step(journal, intent, name)
    producer = CleanupCommandProducerIntent(intent.receipt.admission)
    mailbox.admit_command_producer(producer, deadline=horizon())
    old = complete(mailbox, intent, 1)
    newer = CleanupCommand(intent.receipt.admission, 2)
    latest = CleanupDeliveryReceipt(newer)
    mailbox.submit(newer, deadline=horizon())
    mailbox.take(newer.receipt, delivery=latest, deadline=horizon())
    evidence = replace(evidence, delivery=old if kind == "settled_no_reader" else None)
    mailbox.seal_commands(evidence.intent.command_seal, deadline=horizon())
    assert journal.retire_without_reader(evidence, deadline=horizon()).state != "committed"
    mailbox.acknowledge(newer, delivery=latest, deadline=horizon())
    assert journal.retire_without_reader(evidence, deadline=horizon()).state != "committed"
    mailbox.handback_command_producer(producer, deadline=horizon())
    if kind == "settled_no_reader":
        assert journal.retire_without_reader(evidence, deadline=horizon()).state == "settled"
        evidence = replace(evidence, delivery=latest)
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "committed"


@pytest.mark.parametrize("target", ["command_quiescence", "delivery_status"])
def test_mailbox_checks_outside_lock_and_unavailable(monkeypatch, target):
    """Public mailbox calls never nest publication custody or infer absence."""
    mailbox, journal, _, evidence = fixture("settled_no_reader")
    original = getattr(mailbox, target)
    def checked(*args, **kwargs):
        """Check exact public boundary and force bounded contention."""
        assert not journal._lock.locked()
        mailbox._lock.acquire()
        try:
            return original(*args, **kwargs)
        finally:
            mailbox._lock.release()
    monkeypatch.setattr(mailbox, target, checked)
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "unavailable"


@pytest.mark.parametrize("boundary", ["check", "candidate", "committed", "finalized"])
def test_original_deadline_and_reconciliation(monkeypatch, boundary):
    """No late check/candidate/return extends the caller's original horizon."""
    _, journal, intent, evidence = fixture()
    base = time.monotonic()
    clock = [base]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    target = "_retirement_candidate" if boundary == "candidate" else "_finish" if boundary == "finalized" else "_query"
    original = getattr(journal, target)
    def late(*args):
        """Expire after one precise boundary, retaining committed evidence."""
        result = original(*args)
        if target != "_query" or args[0] == ("retirement_check" if boundary == "check" else "retire"):
            clock[0] = base + 10
        return result
    monkeypatch.setattr(journal, target, late)
    assert journal.retire_without_reader(evidence, deadline=base + 5).state == "unavailable"
    monkeypatch.setattr(journal, target, original)
    state = journal.observe(intent, deadline=base + 20).entries[0]
    assert (state.retirement is evidence) == (boundary == "committed")


@pytest.mark.parametrize("boundary", ["before", "after", "return"])
def test_first_interruption_and_lost_return(boundary):
    """Retain preheld evidence through first interruption, without mutation replay."""
    _, journal, intent, evidence = fixture()
    target = journal._locked if boundary != "return" else journal.retire_without_reader
    lines, start = inspect.getsourcelines(target)
    commit = start + next((i for i, text in enumerate(lines) if "self._slots =" in text), 0)
    primary = KeyboardInterrupt("retirement")
    fired = False
    old = sys.gettrace()
    def trace(frame, event, arg):
        """Disarm before raising so reconciliation is not interrupted again."""
        nonlocal fired
        match = event == "line" and frame.f_lineno == commit if boundary == "before" else event == "return"
        if boundary != "return":
            match = match and frame.f_locals.get("operation") == "retire"
        if not fired and frame.f_code is target.__code__ and match:
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            journal.retire_without_reader(evidence, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired
    state = journal.observe(intent, deadline=horizon()).entries[0]
    assert (state.retirement is evidence) == (boundary != "before")
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == ("committed" if boundary == "before" else "duplicate")


def test_concurrent_transition_revalidated(monkeypatch):
    """An intervening resource publication invalidates the empty certificate."""
    mailbox, journal, intent, evidence = fixture()
    original = mailbox.command_quiescence
    def checked(*args, **kwargs):
        """Linearize a competing transition between two separate metadata locks."""
        result = original(*args, **kwargs)
        step(journal, intent, "resources")
        return result
    monkeypatch.setattr(mailbox, "command_quiescence", checked)
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "blocked"
    assert journal.observe(intent, deadline=horizon()).entries[0].retirement is None


def test_contention_expiry_and_existing_terminal():
    """Unavailable observation and old terminal cannot be overwritten."""
    _, journal, intent, evidence = fixture()
    assert journal.retire_without_reader(evidence, deadline=0).state == "unavailable"
    journal._lock.acquire()
    try:
        assert journal.retire_without_reader(evidence, deadline=horizon()).state == "unavailable"
    finally:
        journal._lock.release()
    journal._slots = (replace(journal._slots[0], stage="terminal"),)
    assert journal.retire_without_reader(evidence, deadline=horizon()).state == "blocked"
