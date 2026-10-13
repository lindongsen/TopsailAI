"""Resource-free durable command closure tests. Author: DawsonLin."""

from dataclasses import FrozenInstanceError, replace
import inspect
import sys
import time
from types import SimpleNamespace

import pytest

import topsailai.hooks.cleanup_mailbox as module
from topsailai.hooks.cleanup_mailbox import (
    CleanupAdmissionIntent, CleanupMailbox, CleanupCommand, CleanupDeliveryReceipt,
    CleanupCommandProducerIntent, CleanupCommandSealIntent,
)

OPERATIONS = ("admit_command_producer", "command_producer_status",
              "handback_command_producer", "seal_commands", "command_quiescence")
MUTATIONS = ("admit_command_producer", "handback_command_producer", "seal_commands")


def horizon():
    """Use a generous single invocation horizon without sleeps."""
    return time.monotonic() + 2


def setup(legacy=False):
    """Construct exact resource-free authority for an admitted slot."""
    mailbox = CleanupMailbox(2)
    receipt = mailbox.reserve(deadline=horizon()) if legacy else mailbox.prepare_admission(0)
    if not legacy:
        assert mailbox.admit(CleanupAdmissionIntent(receipt), deadline=horizon()).state == "admitted"
    return mailbox, receipt, CleanupCommandProducerIntent(receipt), CleanupCommandSealIntent(receipt)


def call(mailbox, name, producer, seal, deadline=None):
    """Dispatch one exact preheld operation with an explicit horizon."""
    intent = seal if name in ("seal_commands", "command_quiescence") else producer
    return getattr(mailbox, name)(intent, deadline=horizon() if deadline is None else deadline)


def cycle(mailbox, receipt, sequence):
    """Complete one command using exact consumer custody."""
    command = CleanupCommand(receipt, sequence)
    delivery = CleanupDeliveryReceipt(command)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    assert mailbox.take(receipt, delivery=delivery, deadline=horizon()) is command
    assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
    return delivery


@pytest.mark.parametrize("legacy", [False, True])
def test_empty_seal_is_durable_and_retains_capacity(legacy):
    """Never-started closure is honest without fabricated command evidence."""
    mailbox, receipt, producer, seal = setup(legacy)
    assert mailbox.command_quiescence(seal, deadline=horizon()).state == "open"
    observed = mailbox.seal_commands(seal, deadline=horizon())
    assert observed.state == "quiescent" and observed.intent is seal
    assert observed.debts == (receipt.pending_debt,)
    for sequence in (1, 2, 1):
        assert mailbox.submit(CleanupCommand(receipt, sequence), deadline=horizon()) == "sealed"
    assert mailbox.admit_command_producer(producer, deadline=horizon()).state == "sealed"
    assert mailbox.handback_command_producer(producer, deadline=horizon()).state == "absent"
    assert mailbox.seal_commands(seal, deadline=horizon()).state == "quiescent"
    assert mailbox.reserve(deadline=horizon()) is not None
    assert mailbox.reserve(deadline=horizon()) is None
    assert len(mailbox.snapshot(deadline=horizon()).debts) == 2


@pytest.mark.parametrize("taken", [False, True])
def test_historical_ack_does_not_discharge_new_work(taken):
    """A newer ready/taken command blocks quiescence despite old acknowledgement."""
    mailbox, receipt, producer, seal = setup()
    old = cycle(mailbox, receipt, 1)
    command = CleanupCommand(receipt, 2)
    delivery = CleanupDeliveryReceipt(command)
    assert mailbox.submit(command, deadline=horizon()) == "accepted"
    if taken:
        assert mailbox.take(receipt, delivery=delivery, deadline=horizon()) is command
    assert mailbox.delivery_status(old, deadline=horizon()) == "acknowledged"
    assert mailbox.seal_commands(seal, deadline=horizon()).state == "sealed_pending"
    assert mailbox.command_quiescence(seal, deadline=horizon()).state == "sealed_pending"
    if not taken:
        assert mailbox.take(receipt, delivery=delivery, deadline=horizon()) is command
    assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
    assert mailbox.command_quiescence(seal, deadline=horizon()).state == "quiescent"
    assert mailbox.submit(command, deadline=horizon()) == "sealed"


@pytest.mark.parametrize("handback_first", [False, True])
@pytest.mark.parametrize("command_pending", [False, True])
def test_producer_lifetime_and_command_drain(handback_first, command_pending):
    """Exact handback and command completion are independent required facts."""
    mailbox, receipt, producer, seal = setup()
    assert mailbox.handback_command_producer(producer, deadline=horizon()).state == "absent"
    assert mailbox.admit_command_producer(producer, deadline=horizon()).state == "active"
    for sequence in range(1, 4):
        cycle(mailbox, receipt, sequence)
        assert mailbox.command_producer_status(producer, deadline=horizon()).state == "active"
    command = CleanupCommand(receipt, 4)
    delivery = CleanupDeliveryReceipt(command)
    if command_pending:
        assert mailbox.submit(command, deadline=horizon()) == "accepted"
    if handback_first:
        assert mailbox.handback_command_producer(producer, deadline=horizon()).state == "returned"
    expected = "sealed_pending" if command_pending or not handback_first else "quiescent"
    assert mailbox.seal_commands(seal, deadline=horizon()).state == expected
    assert mailbox.handback_command_producer(producer, deadline=horizon()).state == "returned"
    if command_pending:
        assert mailbox.command_quiescence(seal, deadline=horizon()).state == "sealed_pending"
        assert mailbox.take(receipt, delivery=delivery, deadline=horizon()) is command
        assert mailbox.acknowledge(command, delivery=delivery, deadline=horizon()) == "acknowledged"
    assert mailbox.command_quiescence(seal, deadline=horizon()).state == "quiescent"
    for _ in range(5):
        assert mailbox.admit_command_producer(producer, deadline=horizon()).state == "returned"
        assert mailbox.handback_command_producer(producer, deadline=horizon()).state == "returned"
        assert mailbox.admit_command_producer(replace(producer), deadline=horizon()).state == "conflict"
    assert mailbox._slots[0].producer is producer and mailbox._slots[0].seal is seal
    assert len(mailbox._slots) == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_exact_identity_and_unadmitted_receipts(operation):
    """Equality and copied/foreign/unadmitted receipts convey no authority."""
    mailbox, receipt, producer, seal = setup()
    call(mailbox, "admit_command_producer", producer, seal)
    call(mailbox, "seal_commands", producer, seal)
    intent = seal if operation in ("seal_commands", "command_quiescence") else producer
    assert getattr(mailbox, operation)(replace(intent), deadline=horizon()).state == "conflict"
    for other in (replace(receipt), CleanupMailbox(1).prepare_admission(0), mailbox.prepare_admission(1)):
        observed = getattr(mailbox, operation)(type(intent)(other), deadline=horizon())
        assert observed.state == "foreign" and observed.debts == ()
    with pytest.raises(FrozenInstanceError):
        intent.receipt = receipt
    with pytest.raises(ValueError):
        type(intent)(None)
    for invalid in (None, SimpleNamespace(receipt=receipt), producer if intent is seal else seal):
        with pytest.raises(ValueError):
            getattr(mailbox, operation)(invalid, deadline=horizon())
    corrupt = replace(intent)
    object.__setattr__(corrupt, "receipt", None)
    with pytest.raises(ValueError):
        getattr(mailbox, operation)(corrupt, deadline=horizon())


class Poison:
    """Reject every protected read when acquisition is unavailable."""

    def __iter__(self):
        """Forbid inventory iteration."""
        pytest.fail("protected inventory read")

    def __len__(self):
        """Forbid inventory capacity checks."""
        pytest.fail("protected inventory read")


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("deadline", [None, True, "1", float("nan"), float("inf")])
def test_invalid_deadlines(operation, deadline):
    """Malformed horizons fail before synchronization."""
    mailbox, receipt, producer, seal = setup()
    mailbox._slots = Poison()
    with pytest.raises(ValueError):
        intent = seal if operation in ("seal_commands", "command_quiescence") else producer
        getattr(mailbox, operation)(intent, deadline=deadline)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("blocked", [False, True])
def test_failed_acquisition_preserves_reserved_unknown(operation, blocked):
    """No failed acquisition reads inventory or fabricates zero custody."""
    mailbox, receipt, producer, seal = setup()
    mailbox._slots = Poison()
    if blocked:
        mailbox._lock.acquire()
    try:
        result = call(mailbox, operation, producer, seal, horizon() if blocked else -1)
        assert result.state == "unavailable"
        assert result.debts is mailbox._unavailable.debts
        assert result.debts[0] is mailbox.handle.unavailable_debt
    finally:
        if blocked:
            mailbox._lock.release()


@pytest.mark.parametrize("operation", MUTATIONS)
@pytest.mark.parametrize("boundary", ["candidate", "commit", "finish"])
def test_deadline_continuity(monkeypatch, operation, boundary):
    """Late commits retain custody, but never return affirmative late permission."""
    mailbox, receipt, producer, seal = setup()
    if operation == "handback_command_producer":
        mailbox.admit_command_producer(producer, deadline=horizon())
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    helper = "_seal_candidate" if operation == "seal_commands" else "_producer_candidate"
    target = helper if boundary == "candidate" else "_publish" if boundary == "commit" else "_finish"
    original = getattr(mailbox, target)
    def expire(*args):
        """Advance only this consumer's clock at the selected boundary."""
        result = original(*args)
        clock.now = 6
        return result
    monkeypatch.setattr(mailbox, target, expire)
    assert call(mailbox, operation, producer, seal, 5).state == "unavailable"
    monkeypatch.setattr(mailbox, target, original)
    observed = call(mailbox, "command_quiescence" if operation == "seal_commands" else "command_producer_status", producer, seal, 10)
    expected = {"admit_command_producer": ("absent", "active"),
                "handback_command_producer": ("active", "returned"),
                "seal_commands": ("open", "quiescent")}[operation]
    assert observed.state == expected[boundary != "candidate"]


@pytest.mark.parametrize("operation", MUTATIONS)
@pytest.mark.parametrize("boundary", ["before", "after", "finish"])
def test_lost_mutation_returns_reconcile(monkeypatch, operation, boundary):
    """Preheld exact identities survive lost commit and finalizer returns."""
    mailbox, receipt, producer, seal = setup()
    if operation == "handback_command_producer":
        mailbox.admit_command_producer(producer, deadline=horizon())
    target = "_finish" if boundary == "finish" else "_publish"
    original = getattr(mailbox, target)
    primary = KeyboardInterrupt("lost return")
    def interrupt(*args):
        """Disarm before interruption so reconciliation can use the real helper."""
        monkeypatch.setattr(mailbox, target, original)
        if boundary != "before":
            original(*args)
        raise primary
    monkeypatch.setattr(mailbox, target, interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        call(mailbox, operation, producer, seal)
    assert caught.value is primary and primary.cleanup_mailbox_ticket.state == "released"
    observed = call(mailbox, "command_quiescence" if operation == "seal_commands" else "command_producer_status", producer, seal)
    states = {"admit_command_producer": ("absent", "active"),
              "handback_command_producer": ("active", "returned"),
              "seal_commands": ("open", "quiescent")}[operation]
    assert observed.state == states[boundary != "before"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("boundary", ["caller", "entry", "primary", "acquiring", "held", "releasing", "released", "return"])
def test_quarantine_matrix(operation, boundary):
    """Every new operation retains exact uncertain custody without retry."""
    mailbox, receipt, producer, seal = setup()
    primary = KeyboardInterrupt("custody boundary")
    function = (CleanupMailbox._command_query if boundary == "caller" else
                CleanupMailbox._acquire if boundary in ("acquiring", "held") else CleanupMailbox._finish)
    patterns = {"caller": "self._finish(ticket)", "primary": "primary = sys.exception()",
                "acquiring": 'ticket.state = "held" if acquired', "held": "if not acquired:",
                "releasing": "self._lock.release()", "released": 'ticket.state = "released"'}
    lines, start = inspect.getsourcelines(function)
    line = start + next(i for i, text in enumerate(lines) if patterns[boundary] in text) if boundary in patterns else None
    old = sys.gettrace()
    fired = False
    def trace(frame, event, arg):
        """Inject once at an executable native/finalization boundary."""
        nonlocal fired
        selected = event == ("call" if boundary == "entry" else "return") if line is None else event == "line" and frame.f_lineno == line
        if not fired and frame.f_code is function.__code__ and selected:
            fired = True
            raise primary
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            call(mailbox, operation, producer, seal)
        assert caught.value is primary
    finally:
        sys.settrace(old)
    expected = {"caller": "held", "entry": "held", "primary": "held", "acquiring": "acquiring",
                "held": "released", "releasing": "releasing", "released": "releasing", "return": "released"}[boundary]
    assert fired and primary.cleanup_mailbox_ticket.state == expected
    assert primary.cleanup_mailbox_ticket.handle is mailbox.handle
    if mailbox._lock.locked():
        # Fixture-owned lock only; production must quarantine uncertain tickets.
        mailbox._lock.release()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("failure", ["acquire", "release", "primary"])
def test_native_uncertainty_and_primary_precedence(monkeypatch, operation, failure):
    """No second native release and no replacement of the active interruption."""
    mailbox, receipt, producer, seal = setup()
    primary, secondary = KeyboardInterrupt("primary"), RuntimeError("release uncertainty")
    class Lock:
        """Simulate ambiguous native custody without a resource."""
        releases = 0
        def acquire(self, blocking=False):
            """Acquire once or lose its evidence."""
            assert blocking is False
            if failure == "acquire":
                raise primary
            return True
        def release(self):
            """Lose native release evidence once."""
            self.releases += 1
            raise secondary
    mailbox._lock = Lock()
    if failure == "primary":
        def interrupt(*args):
            """Interrupt inside proven custody."""
            raise primary
        monkeypatch.setattr(mailbox, "_command_locked", interrupt)
    with pytest.raises(BaseException) as caught:
        call(mailbox, operation, producer, seal)
    assert caught.value is (secondary if failure == "release" else primary)
    assert caught.value.cleanup_mailbox_ticket.state == ("acquiring" if failure == "acquire" else "releasing")
    assert mailbox._lock.releases == (0 if failure == "acquire" else 1)
    if failure == "primary":
        assert primary.cleanup_mailbox_release_error is secondary


@pytest.mark.parametrize("first", ["seal", "submit", "producer"])
def test_deterministic_arbitration(monkeypatch, first):
    """One synchronization authority orders contending producer/command/seal commits."""
    mailbox, receipt, producer, seal = setup()
    command = CleanupCommand(receipt, 1)
    original = mailbox._publish
    contention = []
    def publish(*args):
        """Contending seal cannot observe inventory under another operation's lock."""
        contention.append(mailbox.seal_commands(seal, deadline=horizon()).state)
        return original(*args)
    monkeypatch.setattr(mailbox, "_publish", publish)
    if first == "seal":
        assert mailbox.seal_commands(seal, deadline=horizon()).state == "quiescent"
    elif first == "submit":
        assert mailbox.submit(command, deadline=horizon()) == "accepted"
    else:
        assert mailbox.admit_command_producer(producer, deadline=horizon()).state == "active"
    monkeypatch.setattr(mailbox, "_publish", original)
    assert contention == ["unavailable"]
    assert mailbox.seal_commands(seal, deadline=horizon()).state == ("quiescent" if first == "seal" else "sealed_pending")
    assert mailbox.submit(command, deadline=horizon()) == "sealed"
    assert mailbox.admit_command_producer(producer, deadline=horizon()).state == ("active" if first == "producer" else "sealed")
    other = mailbox.reserve(deadline=horizon())
    assert mailbox.submit(CleanupCommand(other, 1), deadline=horizon()) == "accepted"


def test_delayed_submit_and_producer_lose_to_seal(monkeypatch):
    """Calls begun before seal cannot commit after its authoritative closure."""
    for operation in ("submit", "producer"):
        mailbox, receipt, producer, seal = setup()
        original = mailbox._acquire
        def acquire(end, ticket):
            """Pause before acquisition and let closure commit first."""
            monkeypatch.setattr(mailbox, "_acquire", original)
            assert mailbox.seal_commands(seal, deadline=horizon()).state == "quiescent"
            return original(end, ticket)
        monkeypatch.setattr(mailbox, "_acquire", acquire)
        observed = mailbox.submit(CleanupCommand(receipt, 1), deadline=horizon()) if operation == "submit" else mailbox.admit_command_producer(producer, deadline=horizon()).state
        assert observed == "sealed"


@pytest.mark.parametrize("boundary", ["candidate", "commit", "finish"])
def test_submit_deadline_boundary(monkeypatch, boundary):
    """Candidate preparation cannot extend command admission beyond its horizon."""
    mailbox, receipt, producer, seal = setup()
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    target = "replace" if boundary == "candidate" else "_publish" if boundary == "commit" else "_finish"
    owner = module if boundary == "candidate" else mailbox
    original = getattr(owner, target)
    def expire(*args, **kwargs):
        """Expire after candidate/commit/finalization using a consumer-local clock."""
        result = original(*args, **kwargs)
        clock.now = 6
        return result
    monkeypatch.setattr(owner, target, expire)
    command = CleanupCommand(receipt, 1)
    assert mailbox.submit(command, deadline=5) == "unavailable"
    monkeypatch.setattr(owner, target, original)
    assert mailbox.delivery_status(CleanupDeliveryReceipt(command), deadline=10) == ("foreign" if boundary == "candidate" else "ready")


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("boundary", ["postacquire", "preobserve", "finish"])
def test_all_query_horizon_boundaries(monkeypatch, operation, boundary):
    """Observation as well as mutation rejects late affirmative evidence."""
    mailbox, receipt, producer, seal = setup()
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    target = "_acquire" if boundary == "postacquire" else "_index" if boundary == "preobserve" else "_finish"
    original = getattr(mailbox, target)
    def expire(*args):
        """Advance after acquisition/read/finalization without global clock mutation."""
        result = original(*args)
        clock.now = 6
        return result
    monkeypatch.setattr(mailbox, target, expire)
    result = call(mailbox, operation, producer, seal, 5)
    assert result.state == "unavailable" and result.debts is mailbox._unavailable.debts
    assert not mailbox._lock.locked()


def test_submit_postacquire_expiry(monkeypatch):
    """Late acquired custody cannot authorize a command commit."""
    mailbox, receipt, producer, seal = setup()
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    original = mailbox._acquire
    def expire(end, ticket):
        """Let the acquired lock outlive the original command horizon."""
        result = original(end, ticket)
        clock.now = 6
        return result
    monkeypatch.setattr(mailbox, "_acquire", expire)
    assert mailbox.submit(CleanupCommand(receipt, 1), deadline=5) == "unavailable"
    assert mailbox._slots[0].command is None and not mailbox._lock.locked()


def test_resource_free_methods_and_immutable_observation(monkeypatch):
    """No new operation launches resources or calls external work."""
    import ast
    source = inspect.getsource(module)
    tree = ast.parse(source)
    names = set(OPERATIONS) | {"_command_query", "_command_locked", "_producer_candidate", "_seal_candidate"}
    forbidden = {"Thread", "Popen", "start", "spawn", "open", "callback", "execute", "wait", "sleep"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            calls = [child.func for child in ast.walk(node) if isinstance(child, ast.Call)]
            assert not any(isinstance(func, ast.Attribute) and func.attr in forbidden for func in calls)
    mailbox, receipt, producer, seal = setup()
    observed = mailbox.seal_commands(seal, deadline=horizon())
    with pytest.raises(FrozenInstanceError):
        observed.state = "open"
    assert observed.debts == (receipt.pending_debt,)
