"""Resource-free publication authority regressions. Author: DawsonLin."""

from dataclasses import FrozenInstanceError, replace
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
)
from topsailai.hooks.process_state import LaunchRecord


def horizon():
    """Retain a single generous absolute horizon without sleeps."""
    return time.monotonic() + 1


def setup(capacity=2):
    """Construct inert exact authority without thread/process activation."""
    mailbox = CleanupMailbox(capacity)
    journal = CleanupPublication(mailbox, capacity, backend=object(),
                                 profile="custodian_v1", cleanup_owner=object())
    return mailbox, journal


def intent_for(journal, index=0, **kwargs):
    """Prehold the entire association before both journal and mailbox commits."""
    receipt = journal.prepare(index)
    values = dict(receipt=receipt, admission=CleanupAdmissionIntent(receipt.admission),
                  record=LaunchRecord("mutable"), debt_id="immutable-debt",
                  owner=object(), producer=object(), budget=CleanupBudget(horizon(), horizon()+1))
    values.update(kwargs)
    return PublicationIntent(**values)


def action_for(journal, intent, name, **kwargs):
    """Prehold an exact transition with the required actor token."""
    actor = intent.producer if name in (
        "admission_handback", "start", "resources", "transfer", "producer_handback"
    ) else intent.owner if name in ("owner_admit", "reader_grant", "reader_handback", "never_started") else journal.handle.cleanup_owner
    return PublicationAction(intent, name, actor, **kwargs)


def advance(journal, intent, name, **kwargs):
    """Require committed metadata, never treat it as a resource callback."""
    action = action_for(journal, intent, name, **kwargs)
    result = journal.transition(action, deadline=horizon())
    assert result.state == "committed"
    return action, result.entries[0]


def joined(journal):
    """Join both authorities and explicitly hand back the admission producer."""
    intent = intent_for(journal)
    assert journal.publish(intent, deadline=horizon()).state == "committed"
    advance(journal, intent, "admission_handback")
    advance(journal, intent, "owner_admit")
    return intent


@pytest.mark.parametrize("index", [-1, 2, True, "0", None, 0.0])
def test_invalid_preparation(index):
    """Reject indices without mutable issuance."""
    _, journal = setup()
    with pytest.raises(ValueError):
        journal.prepare(index)


@pytest.mark.parametrize("capacity", [0, 257, True, None, 1.0])
def test_invalid_capacity(capacity):
    """Reject unsafe capacity before catalog construction."""
    with pytest.raises(ValueError):
        CleanupPublication(CleanupMailbox(1), capacity, backend=object(),
                           profile="custodian_v1", cleanup_owner=object())


@pytest.mark.parametrize("field,value", [("mailbox", None), ("profile", "legacy"),
    ("backend", None), ("cleanup_owner", None), ("profile", None)])
def test_constructor_contract(field, value):
    """Keep profile immutable and exact owner tokens resource-free."""
    values = dict(mailbox=CleanupMailbox(1), capacity=1, backend=object(),
                  profile="custodian_v1", cleanup_owner=object())
    values[field] = value
    with pytest.raises(ValueError):
        CleanupPublication(**values)


@pytest.mark.parametrize("field,value", [("record", object()), ("budget", None),
    ("debt_id", ""), ("debt_id", "x"*129), ("debt_id", 1), ("owner", None),
    ("producer", None), ("receipt", None), ("admission", None)])
def test_intent_shape(field, value):
    """Reject malformed association before lock acquisition."""
    _, journal = setup()
    with pytest.raises(ValueError):
        intent_for(journal, **{field: value})


def test_immutable_exact_association_and_no_record_reads():
    """Immutable debt/profile authority never reads mutable LaunchRecord state."""
    mailbox, journal = setup()
    intent = intent_for(journal)
    assert journal.prepare(0) is intent.receipt
    with pytest.raises(FrozenInstanceError):
        intent.debt_id = "changed"
    intent.record.debt_id = "not-authority"
    intent.record.process = object()
    result = journal.publish(intent, deadline=horizon())
    state = result.entries[0]
    assert state.intent is intent and state.intent.record is intent.record
    assert state.intent.budget is intent.budget
    assert state.intent.debt_id == "immutable-debt"
    assert state.admission_producers == state.producers == 1
    assert state.readers == 0 and state.mutation_owner is intent.producer
    assert mailbox.admission_status(intent.admission, deadline=horizon()).state == "admitted"
    assert journal.snapshot(intent.owner, deadline=horizon()).entries == (state,)
    assert journal.snapshot(object(), deadline=horizon()).entries == ()
    assert journal.observe(replace(intent), deadline=horizon()).state == "conflict"
    foreign = replace(intent, receipt=replace(intent.receipt))
    assert journal.observe(foreign, deadline=horizon()).state == "foreign"
    assert journal.observe(replace(intent, receipt=replace(intent.receipt, generation="stale")), deadline=horizon()).state == "foreign"
    competing = intent_for(journal, 1, record=intent.record)
    assert journal.publish(competing, deadline=horizon()).state == "conflict"
    assert journal.publish(intent_for(journal, 1, producer=intent.producer), deadline=horizon()).state == "conflict"


def test_partial_join_full_mailbox_retained_without_false_absence():
    """A failed second commit keeps the exact pending admission producer."""
    mailbox, journal = setup(1)
    mailbox.reserve(deadline=horizon())
    intent = intent_for(journal)
    result = journal.publish(intent, deadline=horizon())
    assert result.state == "pending"
    assert result.entries[0].admission_producers == 1
    assert journal.reconcile(intent, deadline=horizon()).state == "pending"
    assert journal.snapshot(intent.owner, deadline=horizon()).debts
    assert journal.transition(action_for(journal, intent, "start"), deadline=horizon()).state == "blocked"


@pytest.mark.parametrize("boundary", ["journal_before", "journal_after", "mailbox_after", "join_after", "public_return"])
def test_lost_publication_return(boundary, monkeypatch):
    """Preheld intent reconciles each partial commit without replacing identity."""
    mailbox, journal = setup(1)
    intent = intent_for(journal)
    primary = KeyboardInterrupt(boundary)
    target = {"journal_before": CleanupPublication._insert,
              "journal_after": CleanupPublication._insert,
              "mailbox_after": CleanupMailbox.admit,
              "join_after": CleanupPublication._locked,
              "public_return": CleanupPublication.publish}[boundary]
    lines, start = inspect.getsourcelines(target)
    commit = start + next((i for i, text in enumerate(lines) if "self._slots =" in text), 0)
    fired = False
    old = sys.gettrace()
    def trace(frame, event, arg):
        """Disarm before raising so exact reconciliation can run normally."""
        nonlocal fired
        matched = (event == "line" and frame.f_lineno == commit) if boundary == "journal_before" else event == "return"
        if boundary == "join_after":
            matched = matched and frame.f_locals.get("operation") == "join"
        if not fired and frame.f_code is target.__code__ and matched:
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            journal.publish(intent, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired and not journal._lock.locked()
    result = journal.reconcile(intent, deadline=horizon())
    expected = "absent" if boundary == "journal_before" else "pending" if boundary == "journal_after" else "committed" if boundary == "mailbox_after" else "joined"
    assert result.state == expected
    if result.entries:
        assert result.entries[0].intent is intent
        assert result.entries[0].admission_producers == 1


def test_transition_identity_and_exclusive_transfer(monkeypatch):
    """Lost transfer return never restores producer mutation authority."""
    _, journal = setup(1)
    intent = joined(journal)
    advance(journal, intent, "start")
    advance(journal, intent, "resources")
    transfer = action_for(journal, intent, "transfer")
    original = journal._query
    primary = KeyboardInterrupt("transfer acknowledgement lost")
    def lose(*args):
        """Drop a finalized committed return, not the retained exact action."""
        original(*args)
        raise primary
    monkeypatch.setattr(journal, "_query", lose)
    with pytest.raises(KeyboardInterrupt) as caught:
        journal.transition(transfer, deadline=horizon())
    assert caught.value is primary
    monkeypatch.setattr(journal, "_query", original)
    current = journal.observe(intent, deadline=horizon()).entries[0]
    assert current.mutation_owner is journal.handle.cleanup_owner
    assert current.producers == 1
    assert journal.transition(transfer, deadline=horizon()).state == "duplicate"
    assert journal.transition(replace(transfer), deadline=horizon()).state == "conflict"
    assert journal.transition(action_for(journal, intent, "resources"), deadline=horizon()).state == "conflict"
    assert journal.publish(intent, deadline=horizon()).state == "transferred"
    advance(journal, intent, "producer_handback")
    grant, state = advance(journal, intent, "reader_grant")
    assert state.producers == 0 and state.readers == 1
    assert journal.transition(grant, deadline=horizon()).state == "duplicate"
    assert journal.transition(action_for(journal, intent, "settle"), deadline=horizon()).state == "blocked"
    assert journal.seal(deadline=horizon()).state == "sealed"
    _, state = advance(journal, intent, "reader_handback")
    assert state.readers == 0
    advance(journal, intent, "settle")


def test_terminal_requires_command_evidence_and_retains_capacity():
    """Command acknowledgement alone cannot transfer, settle or recycle custody."""
    mailbox, journal = setup(1)
    intent = joined(journal)
    command = CleanupCommand(intent.receipt.admission, 1)
    delivery = CleanupDeliveryReceipt(command)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    assert mailbox.take(command.receipt, delivery=delivery, deadline=horizon()) is command
    assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
    assert journal.observe(intent, deadline=horizon()).entries[0].stage == "joined"
    terminal = action_for(journal, intent, "terminal", delivery=delivery)
    assert journal.transition(terminal, deadline=horizon()).state == "blocked"
    for name in ("start", "resources", "transfer", "producer_handback", "reader_grant", "reader_handback", "settle"):
        advance(journal, intent, name)
    assert journal.transition(action_for(journal, intent, "terminal"), deadline=horizon()).state == "blocked"
    assert journal.transition(action_for(journal, intent, "terminal", delivery=replace(delivery)), deadline=horizon()).state == "settled"
    seal = CleanupCommandSealIntent(intent.receipt.admission)
    mailbox.seal_commands(seal, deadline=horizon())
    terminal = replace(terminal, command_seal=seal)
    state = journal.transition(terminal, deadline=horizon()).entries[0]
    assert state.stage == "terminal" and state.mutation_owner is None
    assert journal.snapshot(intent.owner, deadline=horizon()).debts
    assert mailbox.reserve(deadline=horizon()) is None
    assert journal.publish(replace(intent), deadline=horizon()).state == "conflict"


def test_never_started_retirement_seal_and_late_handback():
    """No process inference is needed for explicit never-started synthetic custody."""
    mailbox, journal = setup()
    intent = joined(journal)
    seal = CleanupCommandSealIntent(intent.receipt.admission)
    mailbox.seal_commands(seal, deadline=horizon())
    journal.seal(deadline=horizon())
    assert journal.transition(action_for(journal, intent, "start"), deadline=horizon()).state == "blocked"
    _, state = advance(journal, intent, "never_started", command_seal=seal)
    assert state.stage == "terminal" and state.producers == 0
    assert journal.publish(intent_for(journal, 1), deadline=horizon()).state == "sealed"
    assert len(journal.snapshot(intent.owner, deadline=horizon()).entries) == 1


class ForbiddenInventory:
    """Fail every mutable inventory access after unavailable acquisition."""

    def __iter__(self):
        """Reject unowned reads."""
        pytest.fail("unowned inventory read")

    def __len__(self):
        """Reject unowned capacity queries."""
        pytest.fail("unowned inventory read")


@pytest.mark.parametrize("operation", ["publish", "observe", "reconcile", "snapshot", "seal", "transition"])
@pytest.mark.parametrize("expired", [True, False])
def test_unavailable_has_reserved_tuple_without_inventory(operation, expired):
    """Failed acquisition bypasses slots/catalog/seal and mailbox callbacks."""
    _, journal = setup()
    intent = intent_for(journal)
    action = action_for(journal, intent, "start")
    journal._slots = journal._catalog = journal._sealed = ForbiddenInventory()
    journal._lock.acquire()
    try:
        deadline = time.monotonic()-1 if expired else horizon()
        if operation == "snapshot":
            result = journal.snapshot(intent.owner, deadline=deadline)
        elif operation == "seal":
            result = journal.seal(deadline=deadline)
        elif operation == "transition":
            result = journal.transition(action, deadline=deadline)
        else:
            result = getattr(journal, operation)(intent, deadline=deadline)
        assert result is journal._unavailable
        assert result.debts is journal._unavailable.debts
        assert result.debts[0] is journal.handle.unavailable_debt
    finally:
        journal._lock.release()


@pytest.mark.parametrize("operation", ["publish", "observe", "reconcile", "snapshot", "seal", "transition"])
@pytest.mark.parametrize("deadline", [None, "1", True, float("nan"), float("inf")])
def test_invalid_deadlines(operation, deadline):
    """Validate before protected inventory access."""
    _, journal = setup()
    intent = intent_for(journal)
    value = intent.owner if operation == "snapshot" else action_for(journal, intent, "start") if operation == "transition" else intent
    with pytest.raises(ValueError):
        if operation == "seal":
            journal.seal(deadline=deadline)
        else:
            getattr(journal, operation)(value, deadline=deadline)


@pytest.mark.parametrize("boundary", ["entry", "acquire_return", "caller_finish", "finish_entry", "primary", "release_before", "release_after", "released_return"])
def test_interruption_ticket_matrix(boundary):
    """Every uncertain held/acquiring/releasing boundary retains exact custody."""
    _, journal = setup()
    intent = intent_for(journal)
    primary = KeyboardInterrupt(boundary)
    function = CleanupPublication._query if boundary in ("entry", "caller_finish") else CleanupPublication._acquire if boundary == "acquire_return" else CleanupPublication._finish
    lines, start = inspect.getsourcelines(function)
    patterns = {"caller_finish": "self._finish(ticket)", "primary": "primary = sys.exception()", "release_before": "self._lock.release()", "release_after": 'ticket.state = "released"'}
    line = start + next((i for i, text in enumerate(lines) if patterns.get(boundary, "not-a-line") in text), 0)
    old = sys.gettrace()
    fired = False
    def trace(frame, event, arg):
        """Intercept exactly one executable target frame boundary."""
        nonlocal fired
        match = event == "call" if boundary in ("entry", "finish_entry") else event == "return" if boundary in ("acquire_return", "released_return") else event == "line" and frame.f_lineno == line
        if not fired and frame.f_code is function.__code__ and match:
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            journal.observe(intent, deadline=horizon())
        assert caught.value is primary
    finally:
        sys.settrace(old)
    assert fired
    if boundary == "entry":
        assert not journal._lock.locked()
        return
    ticket = primary.cleanup_publication_ticket
    assert ticket.handle is journal.handle
    assert ticket.state == ("held" if boundary in ("caller_finish", "finish_entry", "primary") else "releasing" if boundary in ("release_before", "release_after") else "released")
    # Discard this resource-free quarantined journal; never retry its native unlock.


@pytest.mark.parametrize("phase", ["acquiring", "releasing"])
def test_native_uncertainty_no_retry(phase):
    """Ambiguous native return remains quarantined without another unlock."""
    _, journal = setup()
    intent = intent_for(journal)
    primary = KeyboardInterrupt(phase)
    class Lock:
        """Inject ambiguity at the native seam without creating resources."""
        releases = 0
        def acquire(self, **kwargs):
            """Either fail ambiguously or report held custody."""
            if phase == "acquiring":
                raise primary
            return True
        def release(self):
            """Record one ambiguous release attempt."""
            self.releases += 1
            raise primary
    lock = Lock()
    journal._lock = lock
    with pytest.raises(KeyboardInterrupt) as caught:
        journal.observe(intent, deadline=horizon())
    assert caught.value is primary
    assert primary.cleanup_publication_ticket.state == phase
    assert lock.releases == (0 if phase == "acquiring" else 1)


def test_deadline_after_finalization_retains_pending(monkeypatch):
    """Expired finalization does not erase a committed pending admission producer."""
    _, journal = setup()
    intent = intent_for(journal)
    original = journal._finish
    def late(ticket):
        """Consume the original horizon after exact normal release."""
        original(ticket)
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 10))
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    monkeypatch.setattr(journal, "_finish", late)
    assert journal.publish(intent, deadline=5).state == "unavailable"
    monkeypatch.setattr(journal, "_finish", original)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    current = journal.observe(intent, deadline=5)
    assert current.state == "pending" and current.entries[0].admission_producers == 1


def test_resource_free_and_exact_action_validation(monkeypatch):
    """No thread/process/callback or mutable record inspection occurs."""
    def forbidden(*args, **kwargs):
        """Reject any resource activation."""
        pytest.fail("resource activation")
    monkeypatch.setattr(module, "threading", SimpleNamespace(Lock=module.threading.Lock, Thread=forbidden))
    mailbox, journal = setup(1)
    intent = intent_for(journal)
    with pytest.raises(ValueError):
        PublicationAction(intent, "unknown", intent.owner)
    with pytest.raises(ValueError):
        PublicationAction(None, "start", intent.producer)
    with pytest.raises(ValueError):
        PublicationAction(intent, "start", None)
    with pytest.raises(ValueError):
        journal.transition(None, deadline=horizon())
    with pytest.raises(ValueError):
        journal.snapshot(None, deadline=horizon())
    with pytest.raises(ValueError):
        journal.observe(None, deadline=horizon())
    assert journal.publish(intent, deadline=horizon()).state == "committed"
    wrong = PublicationAction(intent, "start", object())
    assert journal.transition(wrong, deadline=horizon()).state == "foreign"
    assert mailbox.snapshot(deadline=horizon()).debts


@pytest.mark.parametrize("action_name", ["start", "resources", "transfer", "producer_handback", "reader_grant", "reader_handback", "settle", "terminal", "never_started"])
def test_transition_before_join_blocked(action_name):
    """Potential producer remains pending until both admissions are confirmed."""
    mailbox, journal = setup(1)
    mailbox.reserve(deadline=horizon())
    intent = intent_for(journal)
    journal.publish(intent, deadline=horizon())
    assert journal.transition(action_for(journal, intent, action_name), deadline=horizon()).state == "blocked"
    assert journal.observe(intent, deadline=horizon()).entries[0].producers == 1


def test_owner_gate_and_original_execution_budget():
    """A fresh query horizon cannot revive an expired execution budget."""
    _, journal = setup(1)
    intent = intent_for(journal, budget=CleanupBudget(0, 1))
    journal.publish(intent, deadline=horizon())
    advance(journal, intent, "admission_handback")
    start = action_for(journal, intent, "start")
    assert journal.transition(start, deadline=horizon()).state == "unavailable"
    advance(journal, intent, "owner_admit")
    assert journal.transition(start, deadline=horizon()).state == "unavailable"
    assert journal.observe(intent, deadline=horizon()).entries[0].stage == "joined"


@pytest.mark.parametrize("ticks,committed", [([10], False), ([0,10], False), ([0,0,10], False), ([0,0,0,10], False), ([0,0,0,0,10], True)])
def test_publication_deadline_each_commit_boundary(monkeypatch, ticks, committed):
    """Entry/acquire/insert/commit/return use the same caller horizon."""
    _, journal = setup(1)
    intent = intent_for(journal)
    clock = iter(ticks)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(clock, 10)))
    assert journal.publish(intent, deadline=5).state == "unavailable"
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    assert journal.observe(intent, deadline=5).state == ("pending" if committed else "absent")


def test_primary_survives_release_failure(monkeypatch):
    """Finalization diagnostics never replace the exact primary interruption."""
    _, journal = setup()
    intent = intent_for(journal)
    primary, secondary = KeyboardInterrupt("primary"), RuntimeError("release")
    def fail(*args):
        """Inject business metadata interruption while the lock is held."""
        raise primary
    class Lock:
        """Retain one ambiguous release without retry."""
        def acquire(self, **kwargs):
            """Report proven acquisition."""
            return True
        def release(self):
            """Expose uncertain release diagnostic."""
            raise secondary
    journal._lock = Lock()
    monkeypatch.setattr(journal, "_locked", fail)
    with pytest.raises(KeyboardInterrupt) as caught:
        journal.observe(intent, deadline=horizon())
    assert caught.value is primary
    assert primary.cleanup_publication_release_error is secondary
    assert primary.cleanup_publication_ticket.state == "releasing"


def test_mailbox_unavailable_join_and_no_nested_lock(monkeypatch):
    """Every public mailbox call is outside metadata custody and retains partial join."""
    mailbox, journal = setup(1)
    intent = intent_for(journal)
    original = mailbox.admit
    def admit(value, *, deadline):
        """Assert nonnested public admission and make observation unavailable."""
        assert not journal._lock.locked()
        mailbox._lock.acquire()
        try:
            return original(value, deadline=deadline)
        finally:
            mailbox._lock.release()
    monkeypatch.setattr(mailbox, "admit", admit)
    assert journal.publish(intent, deadline=horizon()).state == "pending"
    mailbox._lock.acquire()
    try:
        assert journal.reconcile(intent, deadline=horizon()).state == "unavailable"
    finally:
        mailbox._lock.release()
    assert journal.observe(intent, deadline=horizon()).entries[0].admission_producers == 1


def test_identity_validation_extra_boundaries():
    """Reject copied shapes and foreign terminal evidence without takeover."""
    mailbox, journal = setup(1)
    intent = intent_for(journal)
    with pytest.raises(ValueError):
        replace(intent, producer=intent.owner)
    with pytest.raises(ValueError):
        replace(intent, admission=CleanupAdmissionIntent(CleanupMailbox(1).prepare_admission(0)))
    with pytest.raises(ValueError):
        PublicationAction(intent, "terminal", journal.handle.cleanup_owner, object())
    delivery = CleanupDeliveryReceipt(CleanupCommand(intent.receipt.admission, 1))
    with pytest.raises(ValueError):
        PublicationAction(intent, "start", intent.producer, delivery)
    journal.publish(intent, deadline=horizon())
    foreign_delivery = CleanupDeliveryReceipt(CleanupCommand(CleanupMailbox(1).prepare_admission(0), 1))
    action = action_for(journal, intent, "terminal", delivery=foreign_delivery)
    assert journal.transition(action, deadline=horizon()).state == "joined"
    assert mailbox.reserve(deadline=horizon()) is None


@pytest.mark.parametrize("operation", ["publish", "reconcile"])
def test_expiry_between_journal_and_mailbox(monkeypatch, operation):
    """A finalized first commit cannot authorize the second after expiry."""
    _, journal = setup(1)
    intent = intent_for(journal)
    if operation == "reconcile":
        journal._query("publish", intent, None, horizon())
    original = journal._query
    def late(*args):
        """Expire immediately after normal finalization of the first query."""
        result = original(*args)
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 10))
        return result
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    monkeypatch.setattr(journal, "_query", late)
    assert getattr(journal, operation)(intent, deadline=5).state == "unavailable"


@pytest.mark.parametrize("operation", ["insert", "transition"])
def test_expiry_immediately_before_assignment(monkeypatch, operation):
    """Candidate construction does not extend the original commit horizon."""
    _, journal = setup(1)
    intent = joined(journal) if operation == "transition" else intent_for(journal)
    helper = journal._advance if operation == "transition" else journal._insert
    def late(*args):
        """Expire before replacement commit, without touching native lock state."""
        if operation == "transition":
            result = helper(*args)
            monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 10))
            return result
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 10))
        return helper(*args)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    monkeypatch.setattr(journal, "_advance" if operation == "transition" else "_insert", late)
    result = journal.transition(action_for(journal, intent, "start"), deadline=5) if operation == "transition" else journal.publish(intent, deadline=5)
    assert result.state == "unavailable"
    monkeypatch.setattr(journal, "_advance" if operation == "transition" else "_insert", helper)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    assert journal.observe(intent, deadline=5).state == ("joined" if operation == "transition" else "absent")


def test_terminal_no_reader_and_early_owner_gates():
    """Terminal requires reader handback, not merely settled synthetic state."""
    mailbox, journal = setup(1)
    intent = intent_for(journal)
    journal.publish(intent, deadline=horizon())
    advance(journal, intent, "admission_handback")
    assert journal.transition(action_for(journal, intent, "start"), deadline=horizon()).state == "blocked"
    advance(journal, intent, "owner_admit")
    for name in ("start", "resources", "transfer", "producer_handback", "settle"):
        advance(journal, intent, name)
    command = CleanupCommand(intent.receipt.admission, 1)
    delivery = CleanupDeliveryReceipt(command)
    terminal = action_for(journal, intent, "terminal", delivery=delivery)
    assert journal.transition(terminal, deadline=horizon()).state == "settled"
    mailbox.submit(command, deadline=horizon())
    mailbox.take(command.receipt, delivery=delivery, deadline=horizon())
    mailbox.acknowledge(command, delivery=delivery, deadline=horizon())
    seal = CleanupCommandSealIntent(intent.receipt.admission)
    mailbox.seal_commands(seal, deadline=horizon())
    assert journal.transition(replace(terminal, command_seal=seal), deadline=horizon()).state == "blocked"


def test_late_join_never_resets_transfer():
    """A delayed join receipt cannot restore producer mutation ownership."""
    _, journal = setup(1)
    intent = joined(journal)
    for name in ("start", "resources", "transfer"):
        advance(journal, intent, name)
    result = journal._query("join", intent, None, horizon())
    assert result.state == "transferred"
    assert result.entries[0].mutation_owner is journal.handle.cleanup_owner


@pytest.mark.parametrize("boundary", ["candidate", "committed", "finalized"])
def test_original_execution_expiry_at_start_boundaries(monkeypatch, boundary):
    """Caller horizon cannot authorize start after original D, even on late return."""
    _, journal = setup(1)
    intent = intent_for(journal, budget=CleanupBudget(5, 20))
    journal.publish(intent, deadline=horizon())
    for name in ("admission_handback", "owner_admit"):
        advance(journal, intent, name)
    target = {"candidate": "_advance", "committed": "_locked", "finalized": "_finish"}[boundary]
    original = getattr(journal, target)
    clock = [0]
    def late(*args):
        """Advance only the module-local clock after the chosen boundary."""
        result = original(*args)
        clock[0] = 6
        return result
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(journal, target, late)
    assert journal.transition(action_for(journal, intent, "start"), deadline=10) is journal._unavailable
    monkeypatch.setattr(journal, target, original)
    state = journal.observe(intent, deadline=10).entries[0]
    assert state.stage == ("joined" if boundary == "candidate" else "start_pending")
    assert state.producers == 1 and state.mutation_owner is intent.producer
    assert journal.transition(action_for(journal, intent, "start"), deadline=10).state == "unavailable"


@pytest.mark.parametrize("name", ["terminal", "never_started"])
def test_retirement_requires_exact_durable_command_quiescence(monkeypatch, name):
    """Old ack cannot retire newer command or active producer in either path."""
    mailbox, journal = setup(1)
    intent = joined(journal)
    if name == "terminal":
        for step in ("start", "resources", "transfer", "producer_handback", "reader_grant", "reader_handback", "settle"):
            advance(journal, intent, step)
    expected = "settled" if name == "terminal" else "joined"
    producer = CleanupCommandProducerIntent(intent.receipt.admission)
    mailbox.admit_command_producer(producer, deadline=horizon())
    old = CleanupCommand(intent.receipt.admission, 1)
    old_delivery = CleanupDeliveryReceipt(old)
    mailbox.submit(old, deadline=horizon())
    mailbox.take(old.receipt, delivery=old_delivery, deadline=horizon())
    mailbox.acknowledge(old, delivery=old_delivery, deadline=horizon())
    newer = CleanupCommand(old.receipt, 2)
    newer_delivery = CleanupDeliveryReceipt(newer)
    mailbox.submit(newer, deadline=horizon())
    mailbox.take(newer.receipt, delivery=newer_delivery, deadline=horizon())
    seal = CleanupCommandSealIntent(old.receipt)
    action = action_for(journal, intent, name, command_seal=seal,
                        **({"delivery": old_delivery} if name == "terminal" else {}))
    assert journal.transition(replace(action, command_seal=None), deadline=horizon()).state == "blocked"
    assert journal.transition(action, deadline=horizon()).state == expected
    mailbox.seal_commands(seal, deadline=horizon())
    assert journal.transition(action, deadline=horizon()).state == expected
    mailbox.acknowledge(newer, delivery=newer_delivery, deadline=horizon())
    assert journal.transition(action, deadline=horizon()).state == expected
    mailbox.handback_command_producer(producer, deadline=horizon())
    assert journal.transition(replace(action, command_seal=replace(seal)), deadline=horizon()).state == expected
    foreign = CleanupCommandSealIntent(CleanupMailbox(1).prepare_admission(0))
    assert journal.transition(replace(action, command_seal=foreign), deadline=horizon()).state == expected
    original = mailbox.command_quiescence
    def checked(value, *, deadline):
        """Public quiescence must run outside journal synchronization."""
        assert not journal._lock.locked()
        return original(value, deadline=deadline)
    monkeypatch.setattr(mailbox, "command_quiescence", checked)
    mailbox._lock.acquire()
    try:
        assert journal.transition(action, deadline=horizon()) is journal._unavailable
    finally:
        mailbox._lock.release()
    if name == "terminal":
        assert journal.transition(action, deadline=horizon()).state == expected
        action = replace(action, delivery=newer_delivery)
    result = journal.transition(action, deadline=horizon())
    assert result.state == "committed" and result.entries[0].stage == "terminal"
    assert result.entries[0].actions[-1] is action
    assert mailbox.submit(CleanupCommand(old.receipt, 3), deadline=horizon()) == "sealed"
    assert mailbox.reserve(deadline=horizon()) is None


@pytest.mark.parametrize("name,seal", [("start", True), ("terminal", False)])
def test_retirement_seal_shape_validation(name, seal):
    """Only exact seal tokens on retirement actions pass pre-lock validation."""
    _, journal = setup(1)
    intent = intent_for(journal)
    value = CleanupCommandSealIntent(intent.receipt.admission) if seal else object()
    with pytest.raises(ValueError):
        action_for(journal, intent, name, command_seal=value)
