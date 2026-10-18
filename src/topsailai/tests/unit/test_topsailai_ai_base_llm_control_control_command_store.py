"""Registry, ledger retention and recovery tests. Author: DawsonLin."""
from dataclasses import replace
import threading

import pytest

from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.request_control import (
    RequestControl, current_control_target, request_control_scope,
)


def target(attempt="a", binding="b", generation=1):
    """Return exact scalar routing identity."""
    return AttemptTarget(binding, generation, "i", attempt)


def test_idempotency_before_stale_checks_and_conflicts():
    """Retransmission reports retained state even after route revocation."""
    registry = RequestControl()
    t = target()
    registry.bind(t)
    queued = registry.submit(t, "c", "force_retry")
    assert queued.state == "queued"
    assert registry.submit(t, "c", "force_retry") is queued
    assert registry.submit(t, "c", "hard_interrupt").reason == "conflict"
    assert registry.retire(t)
    assert registry.submit(t, "c", "force_retry").reason == "stale_target"
    assert registry.submit(t, "new", "force_retry").reason == "stale_target"
    assert not registry.retire(t)
    assert registry.snapshot(t) is None
    assert registry.probe(t, "creating") is None
    assert not registry.validates(t, queued.proposal)


@pytest.mark.parametrize("changed", [dict(attempt_id="other"), dict(invocation_id="other"),
                                    dict(binding_id="other"), dict(generation=2)])
def test_exact_target_and_forged_reference(changed):
    """Cross-route and detached equal proposals never carry authority."""
    registry = RequestControl()
    t = target()
    registry.bind(t)
    issued = registry.submit(t, "c", "force_retry").proposal
    assert registry.submit(replace(t, **changed), "other", "force_retry").reason == "stale_target"
    assert not registry.validates(t, replace(issued))
    assert registry.select(t, replace(issued)) is None
    assert not registry.validates(t, None)
    assert registry.probe(t, "bad") is None
    assert registry.probe(t, []) is None
    assert registry.snapshot(None) is None


def test_one_winner_losers_and_recovery_custody():
    """Accepted work cannot be evicted until exact cleanup settlement."""
    now = [0.0]
    registry = RequestControl(capacity=4, retention=10, clock=lambda: now[0])
    t = target()
    authority = registry.bind(t)
    p = registry.submit(t, "c", "force_retry").proposal
    registry.submit(t, "loser", "hard_interrupt")
    assert registry.probe(t, "creating") is p
    assert registry.probe(t, "creating") is p
    assert registry.select(t, p).state == "accepted"
    assert registry.status("loser").reason == "already_decided"
    assert registry.submit(t, "late", "hard_interrupt").reason == "already_decided"
    assert not authority.publish("value")
    assert not registry.settle(p)
    assert not registry.settle(None)
    assert registry.applied(p)
    assert not registry.applied(p)
    now[0] = 100
    assert registry.status("c").state == "recovery"
    assert registry.status("loser") is None
    assert registry.retire(t)
    second = target("a2")
    registry.bind(second)
    retry = registry.submit(second, "retry", "force_retry").proposal
    assert registry.select(second, retry).reason == "cleanup_pending"
    hard = registry.submit(second, "hard", "hard_interrupt").proposal
    assert registry.select(second, hard).state == "accepted"
    assert not registry.settle(replace(p))
    assert registry.settle(p)
    assert not registry.settle(p)
    assert registry.applied(hard)
    assert registry.settle(hard)
    now[0] += 11
    assert registry.status("c") is None
    assert registry.status("hard") is None


def test_capacity_never_discards_pending_and_isolation():
    """Global finite capacity rejects, and retirement touches only its target."""
    now = [0]
    registry = RequestControl(capacity=2, retention=1, clock=lambda: now[0])
    a, b = target(), target(binding="other")
    registry.bind(a)
    registry.bind(b)
    registry.submit(a, "a", "force_retry")
    pb = registry.submit(b, "b", "force_retry").proposal
    now[0] = 100
    assert registry.submit(a, "overflow", "force_retry").reason == "capacity"
    assert registry.retire(a)
    assert registry.probe(b, "creating") is pb
    now[0] += 2
    assert registry.status("a") is None
    assert registry.status("b").state == "queued"
    assert registry.submit(b, "new", "force_retry").state == "queued"


def test_deadline_and_publication_after_probe():
    """A pending reference reserves no victory against deadline or publication."""
    now = [0]
    registry = RequestControl(clock=lambda: now[0])
    t = target()
    registry.bind(t, deadline=1)
    p = registry.submit(t, "c", "hard_interrupt").proposal
    now[0] = 1
    assert registry.select(t, p).reason == "already_decided"
    assert registry.snapshot(t).outcome == "timeout"
    assert registry.probe(t, "creating") is None
    registry.retire(t)
    authority = registry.bind(target("next"))
    p = registry.submit(target("next"), "d", "force_retry").proposal
    assert authority.publish("eof")
    assert registry.select(target("next"), p) is None


@pytest.mark.parametrize("kwargs", [{"capacity": 0}, {"capacity": True}, {"retention": 0},
                                    {"retention": float("nan")}, {"retention": "1"}])
def test_bad_configuration(kwargs):
    """Finite bounds reject malformed inputs before creating state."""
    with pytest.raises(ValueError):
        RequestControl(**kwargs)


def test_binding_admission_and_context_isolation():
    """Explicit scoped identity restores nesting and never inherits to threads."""
    registry = RequestControl(capacity=1)
    t = target()
    registry.bind(t)
    for candidate in (t, target(binding="other"), None):
        with pytest.raises(ValueError):
            registry.bind(candidate)
    assert current_control_target() is None
    with request_control_scope(t):
        assert current_control_target() is t
        with request_control_scope(target("nested")):
            assert current_control_target().attempt_id == "nested"
        seen = []
        worker = threading.Thread(target=lambda: seen.append(current_control_target()))
        worker.start()
        worker.join()
        assert seen == [None]
        assert current_control_target() is t
    assert current_control_target() is None
    with pytest.raises(ValueError):
        with request_control_scope(None):
            pass


def test_forged_recovery_and_parallel_command_selection():
    """Only retained proposals win selection or release recovery custody."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from topsailai.ai_base.llm_control.control_command_store import CommandStore
    assert not CommandStore().owns(None)
    registry = RequestControl()
    t = target()
    registry.bind(t)
    proposals = [registry.submit(t, key, action).proposal for key, action in
                 (("hard", "hard_interrupt"), ("retry", "force_retry"))]
    barrier = Barrier(2)

    def select(proposal):
        """Start two independent command consumers at the same boundary."""
        barrier.wait()
        return registry.select(t, proposal)

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(select, proposals))
    assert sum(status is not None and status.state == "accepted" for status in outcomes) == 1
    winner = next(status.proposal for status in outcomes if status is not None and status.state == "accepted")
    assert not registry.applied(replace(winner))
    assert registry.applied(winner)
    assert registry.settle(winner)


def interrupted_once(call, code, line):
    """Raise one exact host interruption before a selected mutation boundary."""
    import sys
    error = KeyboardInterrupt("mutation boundary")
    previous = sys.gettrace()
    fired = False

    def trace(frame, event, arg):
        """Disarm before raising so the real reconciliation can proceed."""
        nonlocal fired
        if not fired and frame.f_code is code and event == "line" and frame.f_lineno == line:
            fired = True
            raise error
        return trace

    sys.settrace(trace)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            call()
        assert caught.value is error
        assert fired
    finally:
        sys.settrace(previous)


def mutation_lines(method):
    """Record actual successful-selection boundaries on this interpreter."""
    import sys
    registry = RequestControl()
    t = target()
    registry.bind(t)
    p = registry.submit(t, "selected", "force_retry").proposal
    observed = set()
    previous = sys.gettrace()

    def trace(frame, event, arg):
        """Observe only the target method without changing registry behavior."""
        if frame.f_code is method.__code__ and event == "line":
            observed.add(frame.f_lineno)
        return trace

    sys.settrace(trace)
    try:
        registry.select(t, p)
    finally:
        sys.settrace(previous)
    return sorted(observed)


@pytest.mark.parametrize("boundary", mutation_lines(RequestControl.select))
def test_selection_interruption_reconciles_exact_custody(boundary):
    """Every selection line preserves winner identity and retryable recovery."""
    registry = RequestControl()
    t, other = target(), target(binding="unrelated")
    authority = registry.bind(t)
    registry.bind(other)
    p = registry.submit(t, "selected", "force_retry").proposal
    unrelated = registry.submit(other, "unrelated", "hard_interrupt").proposal
    interrupted_once(lambda: registry.select(t, p), RequestControl.select.__code__, boundary)
    status = registry.select(t, p)
    assert status.state == "accepted"
    assert authority.snapshot().outcome == "force_retry"
    assert authority.selected(p)
    assert registry.select(t, p).state == "accepted"
    assert registry.probe(other, "creating") is unrelated
    assert registry.applied(p)
    assert registry.settle(p)
    assert not registry.settle(p)
    assert registry._debts == {}


@pytest.mark.parametrize("method", [RequestControl.settle, RequestControl._remove_debt])
def test_settlement_interruption_matrix(method):
    """Partial removal cannot expire the journal or leak invocation capacity."""
    # Only execute the successful path, with a fresh registry per line boundary.
    import sys
    observed = set()
    registry = RequestControl()
    t = target()
    registry.bind(t)
    p = registry.submit(t, "selected", "force_retry").proposal
    registry.select(t, p)
    registry.applied(p)
    previous = sys.gettrace()

    def record(frame, event, arg):
        """Record reached mutation lines rather than unreachable guard branches."""
        if frame.f_code is method.__code__ and event == "line":
            observed.add(frame.f_lineno)
        return record

    sys.settrace(record)
    try:
        assert registry.settle(p)
    finally:
        sys.settrace(previous)
    for boundary in sorted(observed):
        now = [0]
        registry = RequestControl(capacity=3, retention=1, clock=lambda: now[0])
        registry.bind(t)
        other = target(binding="unrelated")
        registry.bind(other)
        unrelated = registry.submit(other, "unrelated", "hard_interrupt").proposal
        p = registry.submit(t, "selected", "force_retry").proposal
        registry.select(t, p)
        registry.applied(p)
        interrupted_once(lambda: registry.settle(p), method.__code__, boundary)
        status = registry.status("selected")
        if status.state == "recovery":
            now[0] = 10
            assert registry.status("selected").state == "recovery"
            assert registry.settle(p)
        else:
            assert status.state == "applied"
            assert not registry.settle(p)
        assert registry._debts == {}
        assert registry.probe(other, "creating") is unrelated
        assert registry.retire(t)
        next_target = target("next")
        registry.bind(next_target)
        retry = registry.submit(next_target, "retry", "force_retry").proposal
        assert registry.select(next_target, retry).state == "accepted"


def test_armed_candidate_cannot_claim_different_winner(monkeypatch):
    """An interrupted candidate cannot inherit a later same-operation winner."""
    registry = RequestControl()
    t = target()
    authority = registry.bind(t)
    first = registry.submit(t, "first", "hard_interrupt").proposal
    second = registry.submit(t, "second", "hard_interrupt").proposal
    original = authority.select

    def interrupt(*args, **kwargs):
        """Interrupt after custody arming but before terminal selection."""
        raise KeyboardInterrupt("before selection")

    monkeypatch.setattr(authority, "select", interrupt)
    with pytest.raises(KeyboardInterrupt):
        registry.select(t, first)
    monkeypatch.setattr(authority, "select", original)
    assert registry.select(t, second).state == "accepted"
    assert registry.select(t, first) is None
    assert authority.selected(second)
    assert not authority.selected(first)


def test_retire_reconciles_selected_but_drops_unselected_custody(monkeypatch):
    """Retirement never turns an armed but unselected proposal into a winner."""
    for selected in (False, True):
        registry = RequestControl()
        t = target()
        authority = registry.bind(t)
        p = registry.submit(t, "selected", "hard_interrupt").proposal
        original = authority.select

        def interrupt(*args, **kwargs):
            """Interrupt immediately before or after the terminal commit."""
            if selected:
                original(*args, **kwargs)
            raise KeyboardInterrupt("selection")

        monkeypatch.setattr(authority, "select", interrupt)
        with pytest.raises(KeyboardInterrupt):
            registry.select(t, p)
        monkeypatch.setattr(authority, "select", original)
        assert registry.retire(t)
        if selected:
            assert registry.status("selected").state == "accepted"
            assert registry.applied(p)
            assert registry.settle(p)
        else:
            assert registry.status("selected").state == "rejected"
            assert not registry._debts


def test_partial_last_debt_removal_does_not_unblock_sibling():
    """Settlement reconciles only its own entry and keeps other owned debt."""
    registry = RequestControl()
    t = target()
    registry.bind(t)
    first = registry.submit(t, "first", "hard_interrupt").proposal
    registry.select(t, first)
    registry.retire(t)
    second_target = target("second")
    registry.bind(second_target)
    second = registry.submit(second_target, "second", "hard_interrupt").proposal
    registry.select(second_target, second)
    registry.applied(first)
    assert registry.settle(first)
    assert registry._debts[registry._debt_key(second)] == {"second": second}
    registry.applied(second)
    assert registry.settle(second)
    assert not registry._debts
    assert registry.select(None, None) is None


def test_selection_inside_authority_interruption():
    """The terminal outcome and exact proposal identity publish together."""
    import dis
    from topsailai.ai_base.llm_control.attempt_control import AttemptControl
    lines = sorted({line for _, line in dis.findlinestarts(AttemptControl.select.__code__)
                    if line is not None})
    # Target the terminal assignment and the return immediately following it.
    import inspect
    source, start = inspect.getsourcelines(AttemptControl.select)
    boundaries = [start + offset for offset, text in enumerate(source)
                  if 'self._decision = (operation, proposal)' in text or 'return "accepted"' in text]
    assert all(line in lines for line in boundaries)
    for boundary in boundaries:
        registry = RequestControl()
        t = target()
        authority = registry.bind(t)
        p = registry.submit(t, "selected", "force_retry").proposal
        interrupted_once(lambda: registry.select(t, p), AttemptControl.select.__code__, boundary)
        assert registry._debts[registry._debt_key(p)][p.command_id] is p
        assert registry.select(t, p).state == "accepted"
        assert authority.selected(p)
        assert registry.applied(p)
        assert registry.settle(p)


def retirement_fixture(state, isolated):
    """Build exact pending/custody states without selecting during retirement."""
    now = [0.0]
    registry = RequestControl(capacity=6 if isolated else 1, retention=1, clock=lambda: now[0])
    t = target()
    sibling = unrelated = None
    if isolated:
        old = target("old")
        registry.bind(old)
        sibling = registry.submit(old, "sibling", "hard_interrupt").proposal
        registry.select(old, sibling)
        registry.retire(old)
        other = target(binding="unrelated")
        registry.bind(other)
        unrelated = registry.submit(other, "unrelated", "hard_interrupt").proposal
    authority = registry.bind(t)
    p = registry.submit(t, "retiring", "hard_interrupt").proposal
    if state == "selected":
        registry.select(t, p)
    if state == "provisional":
        registry._debts[registry._debt_key(p)] = {
            **registry._debts.get(registry._debt_key(p), {}), p.command_id: p}
    return registry, t, authority, p, now, sibling, unrelated


@pytest.mark.parametrize("state", ["queued", "provisional", "selected"])
@pytest.mark.parametrize("isolated", [False, True])
def test_retirement_interruption_matrix(state, isolated):
    """Retirement retains authority through rejection and exact custody cleanup."""
    import sys
    from topsailai.ai_base.llm_control.control_command_store import CommandStore
    methods = (RequestControl.retire, RequestControl._remove_debt,
               CommandStore.reject_pending, CommandStore.transition)
    codes = {method.__code__ for method in methods}
    reached = set()
    registry, t, *_ = retirement_fixture(state, isolated)
    previous = sys.gettrace()

    def record(frame, event, arg):
        """Discover executed boundaries including nested ledger mutations."""
        if event == "line" and frame.f_code in codes:
            reached.add((frame.f_code, frame.f_lineno))
        return record

    sys.settrace(record)
    try:
        assert registry.retire(t)
    finally:
        sys.settrace(previous)
    assert reached
    for code, boundary in sorted(reached, key=lambda item: (item[0].co_name, item[1])):
        registry, t, authority, p, now, sibling, unrelated = retirement_fixture(state, isolated)
        interrupted_once(lambda: registry.retire(t), code, boundary)
        now[0] = 10
        registry.status(p.command_id)
        registry.retire(t)
        assert not registry.retire(t)
        assert registry.snapshot(t) is None
        assert authority.snapshot().outcome == ("hard_interrupt" if state == "selected" else None)
        if state == "selected":
            assert registry.status(p.command_id).state == "accepted"
            assert registry.applied(p)
            assert registry.settle(p)
        else:
            status = registry.status(p.command_id)
            assert status is None or status.state == "rejected"
        assert not registry.settle(p)
        now[0] = 20
        assert registry.status(p.command_id) is None
        if isolated:
            assert registry.status("sibling").proposal is sibling
            assert registry.status("sibling").state == "accepted"
            assert registry.probe(unrelated.target, "creating") is unrelated
            assert registry._debts[registry._debt_key(sibling)] == {"sibling": sibling}
        else:
            assert registry._debts == {}
        fresh = target("fresh")
        registry.bind(fresh)
        assert registry.submit(fresh, "fresh", "hard_interrupt").state == "queued"
        assert registry.retire(fresh)
