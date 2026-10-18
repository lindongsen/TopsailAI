"""Bounded control custody and legacy fallback regressions. Author: DawsonLin."""
from dataclasses import replace
import os
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from topsailai.ai_base.llm_control import control_runtime as runtime
from topsailai.ai_base.llm_control import control_recovery as recovery
from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.request_control import REQUEST_CONTROL, RequestControl
from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner, response_ownership_scope
from tests.unit.test_topsailai_ai_base_llm_control_control_wait import Host


def target():
    """Mint isolated exact identifiers for each lease."""
    return AttemptTarget(uuid4().hex, 1, uuid4().hex, uuid4().hex)


@pytest.mark.parametrize("capacity", [0, -1, True])
def test_invalid_capacity(capacity):
    """Reject malformed bounds before admitting resources."""
    with pytest.raises(ValueError):
        recovery.RecoveryPool(capacity)


@pytest.mark.parametrize("timeout", [0, -1, 1])
@pytest.mark.parametrize("stream", [False, True])
def test_saturation_preserves_entire_legacy_attempt(monkeypatch, timeout, stream):
    """A full pool disables control, not provider work or legacy accounting."""
    pool = recovery.RecoveryPool(1)
    blocker = pool.reserve(target(), AttemptResponseOwner())
    monkeypatch.setattr(runtime, "RECOVERY_POOL", pool)
    agent = object()
    route = runtime.ControlRoute("fallback", os.getpid(), agent, interrupt_supported=True)
    host = Host(lambda: iter(["", "body"]) if stream else "body")
    with runtime.application_control_scope(route), response_ownership_scope():
        invocation = runtime._INVOCATION.set("fallback")
        inherited = runtime._ATTEMPT.set(object())
        try:
            with runtime.attempt_control_scope(None, False) as context:
                assert context is None and runtime.current_attempt_control() is None
                assert route.view()["reason"] == "control_capacity"
                assert route.target is None
                result = host._create_with_first_byte_timeout([], stream=stream, first_byte_timeout=timeout)
                if stream:
                    response = result[0]
                    assert list(host.iter_stream_with_first_byte_timeout(response, timeout)) == ["", "body"]
                else:
                    assert result == "body"
                # Releasing capacity cannot reactivate this in-flight attempt.
                blocker.active = False
                pool.maintain()
                if pool.worker is not None:
                    pool.worker.join(2)
                assert runtime.current_attempt_control() is None
                assert len(host.calls) == 1
            assert runtime.current_attempt_control() is not None
            with runtime.attempt_control_scope(None, False) as context:
                assert context is not None
        finally:
            runtime._ATTEMPT.reset(inherited)
            runtime._INVOCATION.reset(invocation)
    if pool.worker is not None:
        pool.worker.join(2)
    pool.maintain()
    assert not pool.leases


def test_final_route_cleanup_needs_no_further_query():
    """The single maintenance driver releases a finite late worker independently."""
    pool = recovery.RecoveryPool(1, interval=0.001)
    owner = AttemptResponseOwner()
    release = threading.Event()
    started = threading.Event()

    def provider():
        """Keep an exact worker live until the test permits completion."""
        started.set()
        release.wait(2)

    owner.create_thread = threading.Thread(target=provider)
    owner.create_thread.start()
    assert started.wait(2)
    lease = pool.reserve(target(), owner)
    lease.active = False
    pool.schedule()
    driver = pool.worker
    assert driver is not None
    release.set()
    owner.create_thread.join(2)
    driver.join(2)
    assert not driver.is_alive()
    assert not pool.leases


@pytest.mark.parametrize("consumed", [False, True])
def test_exact_delivery_and_undelivered_settlement(consumed):
    """Cleanup and consumer acknowledgment are separate durable facts."""
    pool = recovery.RecoveryPool(1)
    lease = pool.reserve(target(), AttemptResponseOwner())
    lease.authority = REQUEST_CONTROL.bind(lease.target)
    proposal = REQUEST_CONTROL.submit(lease.target, uuid4().hex, "force_retry").proposal
    lease.proposal = proposal
    signal = runtime.LLMRequestedRetryError("selected")
    lease.signal = signal
    signal._control_lease = lease
    assert REQUEST_CONTROL.select(lease.target, proposal).state == "accepted"
    assert not recovery.acknowledge_control(SimpleNamespace(_control_lease=lease))
    if consumed:
        assert recovery.acknowledge_control(signal)
        assert recovery.acknowledge_control(signal)
    lease.active = False
    pool.maintain()
    if not consumed:
        assert lease.target in pool.leases
        assert REQUEST_CONTROL.status(proposal.command_id).state == "accepted"
        lease.superseded = True
    pool.maintain()
    assert not pool.leases
    assert REQUEST_CONTROL.status(proposal.command_id).state == ("applied" if consumed else "rejected")
    if not consumed:
        assert not recovery.acknowledge_control(signal)


def test_undelivered_exact_reference_and_interrupted_debt_removal(monkeypatch):
    """Keep accepted recovery non-evictable until exact debt removal completes."""
    registry = RequestControl()
    identity = target()
    registry.bind(identity)
    proposal = registry.submit(identity, uuid4().hex, "force_retry").proposal
    assert not registry.settle_undelivered(proposal)
    registry.select(identity, proposal)
    assert not registry.settle_undelivered(replace(proposal))
    original = registry._remove_debt
    primary = KeyboardInterrupt("settlement boundary")

    def interrupted(value):
        """Disarm before interrupting an already mutated debt registry."""
        monkeypatch.setattr(registry, "_remove_debt", original)
        original(value)
        raise primary

    monkeypatch.setattr(registry, "_remove_debt", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        registry.settle_undelivered(proposal)
    assert caught.value is primary
    assert registry.status(proposal.command_id).state == "accepted"
    assert registry.settle_undelivered(proposal)
    assert registry.settle_undelivered(proposal)
    assert not registry.settle_undelivered(replace(proposal))
    registry.retire(identity)


def test_maintenance_failure_retains_custody(monkeypatch):
    """A failed pass retains its owner and releases the pass lock for retry."""
    pool = recovery.RecoveryPool(1)
    lease = pool.reserve(target(), AttemptResponseOwner())
    lease.active = False
    original = lease.reconcile

    def fail():
        """Model a recoverable bookkeeping failure."""
        raise RuntimeError("bookkeeping")

    monkeypatch.setattr(lease, "reconcile", fail)
    pool.maintain()
    assert pool.leases[lease.target] is lease
    assert pool.pass_lock.acquire(False)
    pool.maintain()
    pool.pass_lock.release()
    monkeypatch.setattr(lease, "reconcile", original)
    pool.maintain()
    assert not pool.leases


def test_unknown_signal_and_failed_disposal_retain_slot():
    """Neither a forged signal nor uncertain close authorizes successful release."""
    assert not recovery.acknowledge_control(Exception("ordinary"))
    pool = recovery.RecoveryPool(1)
    owner = AttemptResponseOwner()
    lease = pool.reserve(target(), owner)
    owner.disposal_error = RuntimeError("uncertain close")
    lease.active = False
    pool.maintain()
    assert pool.reserve(target(), AttemptResponseOwner()) is None
    owner.disposal_error = None
    pool.maintain()
    assert not pool.leases


def test_driver_start_failure_is_reachable(monkeypatch):
    """Failure to start maintenance does not release exact recovery custody."""
    pool = recovery.RecoveryPool(1)
    lease = pool.reserve(target(), AttemptResponseOwner())

    class BrokenThread:
        """Represent an unstarted driver, never an external resource."""
        def __init__(self, **kwargs):
            """Accept the production constructor shape."""

        def is_alive(self):
            """Report no started worker."""
            return False

        def start(self):
            """Fail before any background execution."""
            raise RuntimeError("driver start")

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "Thread", BrokenThread)
        with pytest.raises(RuntimeError, match="driver start"):
            pool.schedule()
        assert pool.leases[lease.target] is lease
    lease.active = False
    pool.schedule()
    assert not pool.leases


def test_superseded_capability_cannot_be_acknowledged():
    """An exact signal superseded by host interruption never becomes applied."""
    lease = recovery.AttemptLease(target(), AttemptResponseOwner())
    lease.proposal = object()
    signal = Exception("signal")
    lease.signal = signal
    signal._control_lease = lease
    assert not recovery.acknowledge_control(signal)
    lease.superseded = True
    assert not recovery.acknowledge_control(signal)


def test_stat_ticket_settles_without_retaining_model():
    """Recovery owns only the production stat and ticket, not a bound callback."""
    from topsailai.context.llm_request_stat import LLMRequestStat
    stat = LLMRequestStat(clock=lambda: 2.0)
    pool = recovery.RecoveryPool(1)
    lease = pool.reserve(target(), AttemptResponseOwner())
    lease.timing_stat = stat
    lease.timing_ticket = stat.start_request()
    lease.active = False
    pool.maintain()
    assert not pool.leases
    assert stat.get_request_stat_info()["request_duration_count"] == 1


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_production_ticket_outcome_accounting(routed, failure):
    """Real timing tickets and the production outcome decorator count once."""
    from topsailai.ai_base.llm_control.request_tracking import record_llm_request_outcome
    from topsailai.ai_base.llm_base import LLMModel
    from topsailai.context.llm_request_stat import LLMRequestStat
    from contextlib import nullcontext
    from tests.unit.test_topsailai_ai_base_llm_control_control_wait import scope

    class AccountingHost(Host):
        """Use real model accounting adapters with an isolated provider."""
        _start_first_byte_request = LLMModel._start_first_byte_request
        _publish_first_byte_request_ticket = LLMModel._publish_first_byte_request_ticket
        _finish_first_byte_request = LLMModel._finish_first_byte_request
        _start_llm_request = LLMModel._start_llm_request
        _finish_llm_request = LLMModel._finish_llm_request
        _get_llm_request_stat = LLMModel._get_llm_request_stat
        _record_llm_request_success = LLMModel._record_llm_request_success
        _record_llm_request_failure = LLMModel._record_llm_request_failure
        _record_llm_request_stat = LLMModel._record_llm_request_stat

        @record_llm_request_outcome
        def invoke(self):
            """Exercise the actual ContextVar start/outcome composition."""
            return self._create_with_first_byte_timeout([], first_byte_timeout=0)

        def _complete_first_byte_request(self, ticket, *, stream):
            """Finalize the exact production timing identity."""
            self._finish_llm_request(ticket)

    def provider():
        """Return or fail after accounting has been admitted."""
        if failure:
            raise LookupError("provider")
        return "body"

    host = AccountingHost(provider)
    host.llm_request_stat = LLMRequestStat(clock=lambda: 1.0)
    with scope(0) if routed else response_ownership_scope():
        if failure:
            with pytest.raises(LookupError):
                host.invoke()
        else:
            assert host.invoke() == "body"
    snapshot = host.llm_request_stat.get_request_stat_info()
    assert snapshot["total_requests"] == 1
    assert snapshot["request_successes"] == (not failure)
    assert snapshot["request_failures"] == failure
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 0.0


@pytest.mark.parametrize("raising", [False, True])
def test_wait_expiry_observation_and_warning_once(monkeypatch, raising):
    """Fake-clock expiry preserves a single warning across repeated ticks."""
    from tests.unit.test_topsailai_ai_base_llm_control_control_wait import scope
    from topsailai.ai_base.llm_control import control_wait as wait
    from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget, first_byte_budget_scope
    clock = [0.0]
    budget = FirstByteBudget.create(1, clock=lambda: clock[0])
    with scope(0) as (_, owner, context):
        context[2]["raise_timeout"] = raising
        ticks = [0]

        class Ready:
            """Drive expiry without thread scheduling or sleeping."""
            def is_set(self):
                """Finish only after two waits in warning mode."""
                return ticks[0] >= 2

            def wait(self, delay):
                """Advance only the scripted event counter."""
                ticks[0] += 1

        def tick(*args):
            """Advance the deadline before coordinator arbitration."""
            clock[0] = 2.0

        monkeypatch.setattr(wait, "_tick", tick)
        if raising:
            # Bind this authority to exactly the same fake-clock deadline.
            context[1]._raise_timeout = True
            context[1]._deadline = 1.0
            context[1]._clock = lambda: clock[0]
        host = Host(lambda: "body")
        with first_byte_budget_scope(budget):
            if raising:
                with pytest.raises(TimeoutError):
                    wait._wait(Ready(), context, owner, host, 1)
            else:
                wait._wait(Ready(), context, owner, host, 1)
        assert len(host.warnings) == 1


def test_fetch_resume_error_keeps_exact_exception():
    """Resume failures publish through the same first-record authority."""
    from tests.unit.test_topsailai_ai_base_llm_control_control_wait import scope
    error = LookupError("resume")

    class FailingHost(Host):
        """Fail the accounting boundary before provider iteration."""
        def _resume_llm_request(self, ticket):
            """Preserve the original exception identity."""
            raise error

    host = FailingHost(lambda: iter(["body"]))
    with scope(0):
        stream, _ = host._create_with_first_byte_timeout([], stream=True, first_byte_timeout=0)
        with pytest.raises(LookupError) as caught:
            list(host.iter_stream_with_first_byte_timeout(stream, 0))
        assert caught.value is error


@pytest.mark.parametrize("primary_present", [False, True])
def test_scope_scheduler_failure_preserves_primary(monkeypatch, primary_present):
    """Cleanup scheduling never replaces the active host exception."""
    pool = recovery.RecoveryPool(2)
    route = runtime.ControlRoute("scheduler", os.getpid(), object(), interrupt_supported=True)
    token = runtime._ROUTE.set(route)
    invocation = runtime._INVOCATION.set("scheduler")
    monkeypatch.setattr(runtime, "RECOVERY_POOL", pool)
    primary = KeyboardInterrupt("host")

    def failure():
        """Fail at the scheduler boundary, leaving exact custody registered."""
        raise RuntimeError("scheduler")

    try:
        with response_ownership_scope():
            with monkeypatch.context() as patch:
                patch.setattr(pool, "schedule", failure)
                with pytest.raises(KeyboardInterrupt if primary_present else RuntimeError) as caught:
                    with runtime.attempt_control_scope(None, False):
                        if primary_present:
                            raise primary
                if primary_present:
                    assert caught.value is primary
                    assert "remains journaled" in primary.__notes__[0]
        pool.maintain()
        assert not pool.leases
    finally:
        runtime._INVOCATION.reset(invocation)
        runtime._ROUTE.reset(token)


def test_closed_route_rechecked_after_reservation(monkeypatch):
    """An ownership revocation between reserve and bind cannot publish a target."""
    pool = recovery.RecoveryPool(1)
    route = runtime.ControlRoute("closed", os.getpid(), object(), interrupt_supported=True)
    original = pool.reserve

    def reserve(*args):
        """Revoke after successful reservation, before binding admission."""
        lease = original(*args)
        route.closed = True
        return lease

    monkeypatch.setattr(pool, "reserve", reserve)
    monkeypatch.setattr(runtime, "RECOVERY_POOL", pool)
    token = runtime._ROUTE.set(route)
    invocation = runtime._INVOCATION.set("closed")
    try:
        with response_ownership_scope():
            with pytest.raises(RuntimeError, match="route closed"):
                with runtime.attempt_control_scope(None, False):
                    pytest.fail("revoked route entered")
        pool.maintain()
        assert route.target is None and not pool.leases
    finally:
        runtime._INVOCATION.reset(invocation)
        runtime._ROUTE.reset(token)


def test_handler_rechecks_replacement_and_capacity(monkeypatch):
    """Maintenance may not make a previously validated route current again."""
    from topsailai.workspace.control_handlers.llm_control import LLMControlHandler
    from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest
    route = runtime.ControlRoute("handler", os.getpid(), object(), interrupt_supported=True)
    chat = SimpleNamespace(ai_agent=route.agent, _llm_control_route=route)
    context = ControlContext(session_id="handler", pid=os.getpid(), agent_chat=chat)
    handler = LLMControlHandler()
    route.reason = "control_capacity"
    assert handler.handle(ControlRequest("cap", "llm_control", {"operation": "force_retry"}), context).error == "unavailable/control_capacity"

    def replace_route():
        """Replace exact ownership during the unlocked maintenance pass."""
        chat._llm_control_route = object()

    monkeypatch.setattr(route, "reconcile", replace_route)
    assert handler.handle(ControlRequest("status", "llm_control"), context).error == "unavailable"


def test_invocation_supersedes_only_its_undelivered_journal(monkeypatch):
    """Host interruption cannot strand delivery or downgrade another invocation."""
    pool = recovery.RecoveryPool(3)
    owner = object()
    route = runtime.ControlRoute("invocation", os.getpid(), owner, interrupt_supported=True)
    other = pool.reserve(target(), None)
    primary = KeyboardInterrupt("consumer interruption")
    monkeypatch.setattr(runtime, "RECOVERY_POOL", pool)

    @runtime.invocation_control
    def invoke(model):
        """Retain one pending journal then model an interrupted consumer."""
        identity = AttemptTarget(route.binding_id, 1, runtime._INVOCATION.get(), uuid4().hex)
        lease = pool.reserve(identity, None)
        lease.signal = Exception("undelivered")
        raise primary

    token = runtime._ROUTE.set(route)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            invoke(owner)
        assert caught.value is primary
        assert not other.superseded
        assert any(lease.superseded for lease in pool.leases.values())
    finally:
        runtime._ROUTE.reset(token)
        for lease in pool.leases.values():
            lease.active = False
        pool.maintain()


@pytest.mark.parametrize("denied_phase", ["create", "resume", "first_fetch"])
def test_provider_claim_denied_before_operation(monkeypatch, denied_phase):
    """Selected control forbids each not-yet-admitted provider operation."""
    from tests.unit.test_topsailai_ai_base_llm_control_control_wait import scope
    from topsailai.ai_base.llm_control import control_wait as wait
    host = Host(lambda: iter(["body"]))
    original = wait._claim_operation
    with scope(0) as (_, owner, context):
        if denied_phase != "create":
            response, _ = host._create_with_first_byte_timeout([], stream=True, first_byte_timeout=0)

        def claim(ctx, exact_owner, exact_host, timeout, phase):
            """Select at the exact admission boundary, not by sleeping."""
            if phase == denied_phase:
                proposal = REQUEST_CONTROL.submit(ctx[1].target, uuid4().hex, "hard_interrupt").proposal
                lease = ctx[2]["lease"]
                lease.proposal = proposal
                lease.signal = runtime.LLMControlledInterruptError("boundary", attempts=1)
                lease.superseded = True
                REQUEST_CONTROL.select(ctx[1].target, proposal)
            return original(ctx, exact_owner, exact_host, timeout, phase)

        monkeypatch.setattr(wait, "_claim_operation", claim)
        # This injected selection bypasses the Hook delivery producer. The
        # worker must not perform I/O; no result may be fabricated for it.
        with pytest.raises(KeyError):
            if denied_phase == "create":
                host._create_with_first_byte_timeout([], first_byte_timeout=0)
            else:
                list(host.iter_stream_with_first_byte_timeout(response, 0))
        assert context[1].snapshot().outcome == "hard_interrupt"
        assert len(host.calls) == (denied_phase != "create")


@pytest.mark.parametrize("primary_present", [False, True])
def test_application_scheduler_failure_preserves_primary(monkeypatch, primary_present):
    """Application teardown is independent of context reset and primary failure."""
    pool = recovery.RecoveryPool(1)
    route = runtime.ControlRoute("app", os.getpid(), object(), interrupt_supported=True)
    primary = KeyboardInterrupt("application")
    monkeypatch.setattr(runtime, "RECOVERY_POOL", pool)

    def fail():
        """Fail without destroying the pool's recovery registry."""
        raise RuntimeError("application scheduler")

    monkeypatch.setattr(pool, "schedule", fail)
    with pytest.raises(KeyboardInterrupt if primary_present else RuntimeError) as caught:
        with runtime.application_control_scope(route):
            if primary_present:
                raise primary
    if primary_present:
        assert caught.value is primary
    assert route.closed and runtime._ROUTE.get() is None


@pytest.mark.parametrize("boundary", ["select", "abandon", "applied", "retire", "settle", "undelivered"])
def test_one_shot_delivery_recovery_boundaries(monkeypatch, boundary):
    """Every tested mutation keeps the exact primary and retryable journal."""
    from tests.unit.test_topsailai_ai_base_llm_control_control_wait import scope
    from topsailai.ai_base.llm_control import control_wait as wait
    primary = KeyboardInterrupt("boundary " + boundary)
    saved = {}
    with pytest.raises(KeyboardInterrupt) as caught:
        with scope(0) as (_, owner, context):
            lease = context[2]["lease"]
            saved["lease"] = lease
            proposal = REQUEST_CONTROL.submit(lease.target, uuid4().hex, "force_retry").proposal
            saved["proposal"] = proposal
            method = "settle_undelivered" if boundary == "undelivered" else boundary
            receiver = owner if boundary == "abandon" else REQUEST_CONTROL
            original = getattr(receiver, method)

            def interrupted(*args, **kwargs):
                """Disarm before raising after the real mutation has occurred."""
                monkeypatch.setattr(receiver, method, original)
                result = original(*args, **kwargs)
                raise primary

            monkeypatch.setattr(receiver, method, interrupted)
            if boundary in ("select", "abandon"):
                wait._tick(context, owner)
            else:
                try:
                    wait._tick(context, owner)
                except runtime.LLMRequestedRetryError as signal:
                    if boundary != "undelivered":
                        recovery.acknowledge_control(signal)
                    if boundary in ("settle", "retire", "undelivered"):
                        lease.active = False
                        lease.superseded = boundary == "undelivered"
                        lease.reconcile()
                    raise primary
    assert caught.value is primary
    lease = saved["lease"]
    lease.active = False
    if not lease.consumed:
        lease.superseded = True
    assert lease.reconcile()
    status = REQUEST_CONTROL.status(saved["proposal"].command_id)
    assert status.state == ("applied" if lease.consumed else "rejected")
    assert REQUEST_CONTROL.snapshot(lease.target) is None


def test_many_routes_do_not_retain_predecessor_agents(monkeypatch):
    """Finite independent custody replaces recursively retained application routes."""
    import gc
    import weakref
    pool = recovery.RecoveryPool(2)
    monkeypatch.setattr(runtime, "RECOVERY_POOL", pool)

    class Agent:
        """Provide a weak-referenceable application identity."""

    references = []
    for generation in range(1, 21):
        agent = Agent()
        route = runtime.ControlRoute("replacement", os.getpid(), agent, interrupt_supported=True)
        route.generation = generation
        references.append(weakref.ref(agent))
        with runtime.application_control_scope(route), response_ownership_scope():
            token = runtime._INVOCATION.set(uuid4().hex)
            try:
                with runtime.attempt_control_scope(None, False) as context:
                    assert context[1].target.generation == generation
            finally:
                runtime._INVOCATION.reset(token)
        if pool.worker is not None:
            pool.worker.join(2)
        pool.maintain()
        assert not pool.leases
        del agent, route, context
    gc.collect()
    assert all(reference() is None for reference in references)


def test_interrupted_reservation_return_retains_recoverable_lease(monkeypatch):
    """An interrupted reservation handoff cannot leave a permanently active slot."""
    pool = recovery.RecoveryPool(1)
    original = pool.reserve
    primary = KeyboardInterrupt("reserve return")
    route = runtime.ControlRoute("reserve", os.getpid(), object(), interrupt_supported=True)
    monkeypatch.setattr(runtime, "RECOVERY_POOL", pool)

    def reserve(*args):
        """Publish the lease, then interrupt before returning it to the adapter."""
        original(*args)
        raise primary

    monkeypatch.setattr(pool, "reserve", reserve)
    token = runtime._ROUTE.set(route)
    invocation = runtime._INVOCATION.set("reserve")
    try:
        with response_ownership_scope():
            with pytest.raises(KeyboardInterrupt) as caught:
                with runtime.attempt_control_scope(None, False):
                    pytest.fail("interrupted admission entered")
        assert caught.value is primary
        assert len(pool.leases) == 1
        pool.maintain()
        assert not pool.leases
    finally:
        runtime._INVOCATION.reset(invocation)
        runtime._ROUTE.reset(token)


def test_consumer_interruption_after_application_scope(monkeypatch):
    """An interrupted late consumer settles without an enclosing route scope."""
    pool = recovery.RecoveryPool(1)
    lease = pool.reserve(target(), AttemptResponseOwner())
    lease.authority = REQUEST_CONTROL.bind(lease.target)
    lease.proposal = REQUEST_CONTROL.submit(lease.target, uuid4().hex, "hard_interrupt").proposal
    signal = runtime.LLMControlledInterruptError("late consumer", attempts=1)
    lease.signal = signal
    signal._control_lease = lease
    REQUEST_CONTROL.select(lease.target, lease.proposal)
    lease.active = False
    primary = KeyboardInterrupt("before consumption")
    original = lease.authority.selected

    def interrupted(proposal):
        """Disarm before interrupting acknowledgment validation."""
        monkeypatch.setattr(lease.authority, "selected", original)
        raise primary

    monkeypatch.setattr(lease.authority, "selected", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        recovery.acknowledge_control(signal)
    assert caught.value is primary
    assert lease.superseded and not lease.consumed
    pool.maintain()
    assert not pool.leases
    assert REQUEST_CONTROL.status(lease.proposal.command_id).reason == "interrupted_before_delivery"
