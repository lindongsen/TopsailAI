"""Resource-free custodian lifecycle regressions. Author: DawsonLin."""

from dataclasses import FrozenInstanceError
import threading
import time
from types import SimpleNamespace

import pytest

from topsailai.hooks.cleanup_budget import CleanupBudget
from topsailai.hooks.cleanup_custodian import CleanupCustodian


def end():
    """Return one generous absolute test horizon without resource work."""
    return time.monotonic() + 1


def custodian():
    """Construct one owner-confined fixture with frozen original horizons."""
    return CleanupCustodian(2, CleanupBudget(1, 2))


def test_constructor_open_close_and_no_restart():
    """Constructor starts nothing; repeated operations retain exact actor."""
    owner = custodian()
    assert owner.actor_receipt is None
    assert owner.open(deadline=end())
    actor = owner.actor_receipt
    assert actor.thread.daemon
    assert owner.open(deadline=end())
    assert owner.actor_receipt is actor
    report = owner.close(deadline=end())
    assert report.fully_closed and report.actor_stopped and report.admission_closed
    assert report.state == "CLOSED" and report.producer_count == 0
    assert owner.close(deadline=end()).fully_closed
    assert not owner.open(deadline=end())
    assert owner.reserve(deadline=end()) is None
    assert owner._budget == CleanupBudget(1, 2)
    with pytest.raises(FrozenInstanceError):
        report.fully_closed = False


def test_unstarted_close():
    """An empty never-started controller can close without manufacturing an actor."""
    owner = custodian()
    assert owner.close(deadline=end()).fully_closed
    assert owner.actor_receipt is None


def test_pending_slots_prevent_full_close():
    """Actor exit does not settle admitted debt or release slot capacity."""
    owner = custodian()
    receipt = owner.reserve(deadline=end())
    report = owner.close(deadline=end())
    assert report.actor_stopped and not report.fully_closed
    assert report.retained_debts == (receipt.pending_debt,)
    assert owner.close(deadline=end()).retained_debts == report.retained_debts
    assert owner.reserve(deadline=end()) is None


@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf")])
def test_invalid_deadline_before_start(value):
    """Malformed deadlines cannot launch the actor."""
    owner = custodian()
    with pytest.raises(ValueError):
        owner.open(deadline=value)
    assert owner.actor_receipt is None


def test_invalid_budget():
    """Reject budget lookalikes before construction."""
    with pytest.raises(ValueError):
        CleanupCustodian(1, None)


def test_expired_and_contended_observation():
    """Unavailable never consults lifecycle inventory or starts a thread."""
    owner = custodian()
    assert not owner.open(deadline=time.monotonic() - 1)
    owner._mailbox._lock.acquire()
    try:
        assert not owner.open(deadline=end())
        assert owner.reserve(deadline=end()) is None
        report = owner.close(deadline=end())
        assert report.retained_debts == (owner.handle.unavailable_debt,)
        assert report.producer_count is None and not report.fully_closed
        assert owner.snapshot(deadline=end()).state == "unavailable"
    finally:
        owner._mailbox._lock.release()
    assert owner.actor_receipt is None


def test_owner_affinity():
    """Foreign threads cannot operate the lifecycle controller."""
    owner = custodian()
    errors = []
    def foreign():
        """Capture rejection without changing lifecycle state."""
        try:
            owner.open(deadline=end())
        except ValueError as error:
            errors.append(error)
    thread = threading.Thread(target=foreign)
    thread.start()
    thread.join(1)
    assert not thread.is_alive() and len(errors) == 1
    assert owner.actor_receipt is None


def test_uncertain_start_is_not_retried(monkeypatch):
    """Prepublished identity survives start failure; no second actor is created."""
    owner = custodian()
    primary = KeyboardInterrupt()
    calls = []
    def fail(thread):
        """Model a start with no proven outcome."""
        calls.append(thread)
        raise primary
    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.open(deadline=end())
    assert caught.value is primary
    assert primary.cleanup_actor_receipt is owner.actor_receipt
    assert not owner.open(deadline=end()) and len(calls) == 1
    report = owner.close(deadline=end())
    assert not report.actor_stopped and not report.fully_closed


@pytest.mark.parametrize("method", ["open", "reserve", "snapshot", "close"])
def test_mailbox_uncertainty_quarantines(method, monkeypatch):
    """Exact retained lock authority triggers STOP rather than another observation."""
    owner = custodian()
    ticket = SimpleNamespace(handle=owner.handle, state="held")
    primary = KeyboardInterrupt()
    primary.cleanup_mailbox_ticket = ticket
    def fail(**kwargs):
        """Expose explicit mailbox uncertainty at the observation boundary."""
        raise primary
    monkeypatch.setattr(owner._mailbox, "snapshot", fail)
    with pytest.raises(KeyboardInterrupt) as caught:
        getattr(owner, method)(deadline=end())
    assert caught.value is primary and owner.quarantine_ticket is ticket
    assert not owner.open(deadline=end())
    assert owner.close(deadline=end()).retained_debts == (owner.handle.unavailable_debt,)


def test_foreign_quarantine():
    """A copied handle cannot confer quarantine authority."""
    owner = custodian()
    with pytest.raises(ValueError):
        owner.quarantine(SimpleNamespace(handle=custodian().handle, state="held"))
    assert owner.quarantine_ticket is None


def test_reserve_uncertainty_and_plain_exception(monkeypatch):
    """Reservation failures retain exact tickets without inventing missing custody."""
    owner = custodian()
    assert owner.open(deadline=end())
    actor = owner.actor_receipt
    ticket = SimpleNamespace(handle=owner.handle, state="releasing")
    primary = KeyboardInterrupt()
    primary.cleanup_mailbox_ticket = ticket
    def fail(**kwargs):
        """Fail once at reservation handoff."""
        raise primary
    monkeypatch.setattr(owner._mailbox, "reserve", fail)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.reserve(deadline=end())
    assert caught.value is primary and owner.quarantine_ticket is ticket
    report = owner.close(deadline=end())
    assert actor.stop.is_set() and not actor.thread.is_alive()
    assert report.actor_stopped and not report.fully_closed
    other = custodian()
    monkeypatch.setattr(other._mailbox, "snapshot", fail)
    del primary.cleanup_mailbox_ticket
    with pytest.raises(KeyboardInterrupt) as caught:
        other.snapshot(deadline=end())
    assert caught.value is primary and other.quarantine_ticket is None


def test_default_deadline_and_late_readiness(monkeypatch):
    """STARTING retains one actor after readiness delay; later open observes it."""
    owner = custodian()
    release = threading.Event()
    def delayed(ready, stop):
        """Synchronize delayed readiness without duration-equal sleeps."""
        release.wait()
        ready.set()
        stop.wait()
    monkeypatch.setattr("topsailai.hooks.cleanup_custodian._idle_actor", delayed)
    try:
        assert not owner.open(deadline=time.monotonic() + .01)
        actor = owner.actor_receipt
        release.set()
        assert owner.open()
        assert owner.actor_receipt is actor
        assert owner.snapshot().state == "current"
    finally:
        release.set()
        report = owner.close()
    assert report.fully_closed


def test_dead_actor_is_not_restarted(monkeypatch):
    """Readiness without a living actor grants no running admission."""
    owner = custodian()
    def exited(ready, stop):
        """Model actor exit after startup notification."""
        ready.set()
    monkeypatch.setattr("topsailai.hooks.cleanup_custodian._idle_actor", exited)
    owner.open(deadline=end())
    actor = owner.actor_receipt
    actor.thread.join(1)
    assert not owner.open(deadline=end())
    assert owner.actor_receipt is actor
    assert owner.close(deadline=end()).fully_closed


def test_close_observation_expires(monkeypatch):
    """Late close result never implies verified emptiness."""
    owner = custodian()
    assert owner.open(deadline=end())
    original = owner._mailbox.snapshot
    calls = []
    def observe(**kwargs):
        """Return unavailable on the first post-shutdown observation."""
        calls.append(1)
        if len(calls) == 1:
            return original(deadline=time.monotonic() - 1)
        return original(**kwargs)
    monkeypatch.setattr(owner._mailbox, "snapshot", observe)
    report = owner.close(deadline=end())
    assert not report.fully_closed and report.state == "UNAVAILABLE"
    assert report.actor_stopped and report.admission_closed
    assert report.producer_count is None
    assert owner.close(deadline=end()).fully_closed


def test_primary_at_start_handoff_is_reachable(monkeypatch):
    """An interrupted start of a real thread retains prepublished exact custody."""
    owner = custodian()
    original = threading.Thread.start
    primary = KeyboardInterrupt()
    def started(thread):
        """Start exactly once before returning an interruption."""
        original(thread)
        raise primary
    monkeypatch.setattr(threading.Thread, "start", started)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.open(deadline=end())
    assert caught.value is primary
    assert primary.cleanup_actor_receipt is owner.actor_receipt
    assert not owner.open(deadline=end())
    assert owner.close(deadline=end()).fully_closed


@pytest.mark.parametrize("state", ["held", "acquiring", "releasing", "contended"])
def test_close_stops_exact_actor_without_inventory_authority(state):
    """Close owns actor shutdown independently of unavailable mailbox custody."""
    owner = custodian()
    assert owner.open(deadline=end())
    actor = owner.actor_receipt
    receipt = owner.reserve(deadline=end())
    ticket = SimpleNamespace(handle=owner.handle, state=state)
    if state == "contended":
        owner._mailbox._lock.acquire()
    else:
        owner.quarantine(ticket)
    try:
        report = owner.close(deadline=end())
        assert actor.stop.is_set() and not actor.thread.is_alive()
        assert owner.actor_receipt is actor
        assert report.admission_closed and report.actor_stopped
        assert report.state == "UNAVAILABLE" and report.producer_count is None
        assert report.retained_debts == (owner.handle.unavailable_debt,)
        assert not report.fully_closed
        again = owner.close(deadline=end())
        assert again == report
        assert not owner.open(deadline=end())
        assert owner.reserve(deadline=end()) is None
        if state != "contended":
            assert owner.quarantine_ticket is ticket
    finally:
        if state == "contended":
            owner._mailbox._lock.release()
        # Failure-only safety cleanup is not evidence for successful close.
        if actor.thread.is_alive():
            actor.stop.set()
            actor.thread.join(1)
    if state == "contended":
        assert owner.snapshot(deadline=end()).debts == (receipt.pending_debt,)
        settled = owner.close(deadline=end())
        assert settled.actor_stopped and not settled.fully_closed
        assert settled.retained_debts == (receipt.pending_debt,)


@pytest.mark.parametrize("quarantined", [False, True])
def test_expired_close_signals_actor_and_retains_unknown_debt(quarantined):
    """An expired horizon still requests stop without claiming settled inventory."""
    owner = custodian()
    assert owner.open(deadline=end())
    actor = owner.actor_receipt
    if quarantined:
        owner.quarantine(SimpleNamespace(handle=owner.handle, state="held"))
    report = owner.close(deadline=time.monotonic() - 1)
    assert actor.stop.is_set()
    assert report.admission_closed and not report.fully_closed
    assert report.producer_count is None
    assert report.retained_debts == (owner.handle.unavailable_debt,)
    repeated = owner.close(deadline=end())
    assert repeated.actor_stopped and not actor.thread.is_alive()
    assert repeated.fully_closed is (not quarantined)


def test_close_observation_interruption_occurs_after_actor_shutdown(monkeypatch):
    """A first inventory interruption preserves its identity after exact actor stop."""
    owner = custodian()
    assert owner.open(deadline=end())
    actor = owner.actor_receipt
    primary = KeyboardInterrupt()
    ticket = SimpleNamespace(handle=owner.handle, state="acquiring")
    primary.cleanup_mailbox_ticket = ticket
    def fail(**kwargs):
        """Assert independent shutdown before exposing inventory uncertainty."""
        assert actor.stop.is_set() and not actor.thread.is_alive()
        raise primary
    monkeypatch.setattr(owner._mailbox, "snapshot", fail)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.close(deadline=end())
    assert caught.value is primary and owner.quarantine_ticket is ticket
    report = owner.close(deadline=end())
    assert report.actor_stopped and report.admission_closed
    assert report.producer_count is None and not report.fully_closed


@pytest.mark.parametrize("boundary", ["observation", "preparation"])
def test_startup_expiry_prevents_native_start(boundary, monkeypatch):
    """Late observation or preparation cannot authorize startup or create debt."""
    import topsailai.hooks.cleanup_custodian as module

    owner = custodian()
    horizon = end()
    clock = SimpleNamespace(now=horizon - .5)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    starts = []
    original_start = threading.Thread.start
    original_snapshot = owner._mailbox.snapshot
    original_receipt = module.CleanupActorReceipt

    def start(thread):
        """Record any forbidden native start without hiding the real boundary."""
        starts.append(thread)
        original_start(thread)

    def observe(**kwargs):
        """Return real current inventory under the same original horizon."""
        assert kwargs["deadline"] == horizon
        result = original_snapshot(**kwargs)
        assert result.state == "current"
        if boundary == "observation":
            clock.now = horizon + 1
        return result

    def prepare(*args):
        """Expire only after constructing a real but never-started receipt."""
        actor = original_receipt(*args)
        clock.now = horizon + 1
        return actor

    monkeypatch.setattr(threading.Thread, "start", start)
    monkeypatch.setattr(owner._mailbox, "snapshot", observe)
    if boundary == "preparation":
        monkeypatch.setattr(module, "CleanupActorReceipt", prepare)
    try:
        assert not owner.open(deadline=horizon)
        assert starts == []
        actor = owner.actor_receipt
        if boundary == "observation":
            assert actor is None
        else:
            assert actor is not None and actor.thread.ident is None
        monkeypatch.setattr(owner._mailbox, "snapshot", original_snapshot)
        report = owner.close(deadline=end())
        assert report.admission_closed and report.actor_stopped
        assert report.producer_count == 0 and report.retained_debts == ()
        assert report.fully_closed and report.state == "CLOSED"
        assert owner.close(deadline=end()) == report
        assert not owner.open(deadline=end())
        assert starts == []
    finally:
        # Failure-only teardown never substitutes for the zero-start assertion.
        actor = owner.actor_receipt
        if actor is not None and actor.thread.ident is not None:
            actor.stop.set()
            actor.thread.join(1)
