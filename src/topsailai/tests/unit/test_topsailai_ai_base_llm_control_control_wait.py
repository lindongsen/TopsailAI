"""Controlled waiting boundaries and exact route tests. Author: DawsonLin."""
from contextlib import contextmanager
from dataclasses import asdict
import os
from types import SimpleNamespace
import threading

import pytest

from topsailai.ai_base.llm_control import control_runtime as runtime
from topsailai.ai_base.llm_control import control_wait as wait
from topsailai.ai_base.llm_control.control_recovery import acknowledge_control
from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget, first_byte_budget_scope
from topsailai.ai_base.llm_control.first_byte_timeout import FirstByteTimeoutMixin
from topsailai.ai_base.llm_control.request_control import REQUEST_CONTROL
from topsailai.ai_base.llm_control.response_ownership import response_ownership_scope
from topsailai.workspace.control_handlers.llm_control import LLMControlHandler
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest


class Host(FirstByteTimeoutMixin):
    """Provide deterministic request/iterator and bookkeeping seams."""

    def __init__(self, response):
        """Retain a provider operation and exact timing observations."""
        self.response = response
        self.calls = []
        self.warnings = []
        self.finished = []

    def _build_first_byte_request_parameters(self, messages, **kwargs):
        """Detach supplied request data for the provider worker."""
        return (messages, kwargs)

    def _create_first_byte_response(self, params):
        """Invoke the test provider without replacing control coordination."""
        self.calls.append(params)
        return self.response()

    def _start_first_byte_request(self):
        """Return one distinct timing identity."""
        return object()

    def _finish_first_byte_request(self, ticket):
        """Record exact finishing without sleep or process-global state."""
        self.finished.append(ticket)

    def _publish_first_byte_request_ticket(self, ticket):
        """Retain the accepted ticket."""
        self.ticket = ticket

    def _complete_first_byte_request(self, ticket, *, stream):
        """Match production pause-versus-finish accounting."""
        if not stream:
            self.finished.append(ticket)

    def _get_llm_request_timing_ticket(self):
        """Expose accepted ticket for the first fetch."""
        return getattr(self, "ticket", None)

    def _resume_llm_request(self, ticket):
        """Accept an exact timing resume."""

    def _make_first_byte_timeout_error(self, timeout):
        """Create a recognizable domain timeout."""
        return TimeoutError("controlled deadline")

    def _log_first_byte_timeout(self, elapsed, timeout):
        """Record warning cardinality."""
        self.warnings.append((elapsed, timeout))


@contextmanager
def scope(timeout=1, raising=False, retry=True, interrupt=True):
    """Install real canonical routing with task-owned exact response custody."""
    route = runtime.ControlRoute("unit", os.getpid(), object(), interrupt_supported=interrupt)
    budget = FirstByteBudget.create(timeout) if timeout > 0 else None
    with runtime.application_control_scope(route):
        token = runtime._INVOCATION.set("unit-invocation")
        runtime.set_retry_available(retry)
        try:
            with response_ownership_scope() as owner, first_byte_budget_scope(budget):
                with runtime.attempt_control_scope(budget, raising) as context:
                    yield route, owner, context
        finally:
            runtime._INVOCATION.reset(token)
            with runtime.RECOVERY_POOL.lock:
                leases = tuple(runtime.RECOVERY_POOL.leases.values())
            for lease in leases:
                if lease.target.binding_id != route.binding_id or lease.owner is None:
                    continue
                owner = lease.owner
                for thread in (owner.create_thread, owner.fetch_thread, owner.cleanup_thread):
                    if thread is not None:
                        thread.join(2)
            route.reconcile()


@pytest.mark.parametrize("timeout", [0, -1, 1])
@pytest.mark.parametrize("stream", [False, True])
def test_no_command_payload_and_eof(timeout, stream):
    """Controlled calls preserve values and empty first records without commands."""
    host = Host(lambda: iter(["", "body"]) if stream else "body")
    with scope(timeout) as (route, owner, context):
        result = host._create_with_first_byte_timeout(["same"], stream=stream, first_byte_timeout=timeout)
        if stream:
            assert list(host.iter_stream_with_first_byte_timeout(result[0], timeout)) == ["", "body"]
        else:
            assert result == "body"
        assert context[1].snapshot().outcome == "value"
        assert len(host.calls) == 1


@pytest.mark.parametrize("operation,signal", [
    ("force_retry", runtime.LLMRequestedRetryError),
    ("hard_interrupt", runtime.LLMControlledInterruptError),
])
@pytest.mark.parametrize("phase", ["creating", "first_record"])
@pytest.mark.parametrize("timeout", [0, 0.01, 1])
def test_hook_selected_control(monkeypatch, operation, signal, phase, timeout):
    """Use the real bundled Hook and reject any subsequent provider admission."""
    host = Host(lambda: iter(["body"]))
    with scope(timeout) as (route, owner, context):
        if phase == "first_record":
            response, _ = host._create_with_first_byte_timeout([], stream=True, first_byte_timeout=timeout)
        proposal = REQUEST_CONTROL.submit(context[1].target, "cmd-" + route.binding_id, operation).proposal
        with pytest.raises(signal) as caught:
            if phase == "creating":
                host._create_with_first_byte_timeout([], stream=True, first_byte_timeout=timeout)
            else:
                list(host.iter_stream_with_first_byte_timeout(response, timeout))
        assert REQUEST_CONTROL.status(proposal.command_id).state == "accepted"
        assert acknowledge_control(caught.value)
        assert REQUEST_CONTROL.status(proposal.command_id).state == "recovery"
        assert context[1].selected(proposal)
        assert len(host.calls) == (phase == "first_record")


@pytest.mark.parametrize("operation,retry,interrupt,reason", [
    ("force_retry", False, True, "retry_budget_exhausted"),
    ("hard_interrupt", True, False, "unsupported_exit_scope"),
])
def test_rejected_controls_preserve_result(operation, retry, interrupt, reason):
    """Unsupported controls cannot abandon or alter an ordinary response."""
    host = Host(lambda: "body")
    with scope(retry=retry, interrupt=interrupt) as (route, owner, context):
        command = "reject-" + route.binding_id
        REQUEST_CONTROL.submit(context[1].target, command, operation)
        assert host._create_with_first_byte_timeout([], stream=False) == "body"
        assert REQUEST_CONTROL.status(command).reason == reason


def test_foreign_hook_value_cannot_select(monkeypatch):
    """A fabricated plugin mapping has no authority."""
    monkeypatch.setattr(wait.hooks, "hook__llm__before__first_byte_wait_tick", lambda **kw: {"force_retry": True})
    with scope():
        assert Host(lambda: "body")._create_with_first_byte_timeout([]) == "body"


def test_handler_exact_route_projection():
    """Status and receipt expose scalars and require exact authenticated routing."""
    handler = LLMControlHandler()
    with scope() as (route, owner, context):
        agent_chat = SimpleNamespace(ai_agent=route.agent, _llm_control_route=route)
        channel = ControlContext(session_id="unit", pid=os.getpid(), agent_chat=agent_chat)
        status = handler.handle(ControlRequest("status", "llm_control"), channel)
        assert status.result["target"] == asdict(context[1].target)
        request = ControlRequest("handler-" + route.binding_id, "llm_control", {
            "operation": "force_retry", "target": asdict(context[1].target),
        })
        result = handler.handle(request, channel)
        assert result.result["state"] == "queued"
        assert handler.handle(request, channel).result == result.result
        channel.pid = -1
        assert handler.handle(request, channel).error == "unavailable"


@pytest.mark.parametrize("phase", ["create", "fetch", "eof"])
def test_terminal_error_and_eof_identity(phase):
    """Preserve exact provider exceptions and empty-stream termination."""
    error = ValueError("exact provider error")

    def provider():
        """Fail at the selected boundary without timing sleeps."""
        if phase == "create":
            raise error
        return records()

    def records():
        """Produce either EOF or one exact fetch failure."""
        if phase == "fetch":
            raise error
        yield from ()

    host = Host(provider)
    with scope() as (_, owner, context):
        if phase == "eof":
            response, _ = host._create_with_first_byte_timeout([], stream=True)
            assert list(host.iter_stream_with_first_byte_timeout(response)) == []
            assert context[1].snapshot().outcome == "eof"
        else:
            with pytest.raises(ValueError) as caught:
                response, _ = host._create_with_first_byte_timeout([], stream=True)
                list(host.iter_stream_with_first_byte_timeout(response))
            assert caught.value is error
            assert context[1].snapshot().outcome == "error"


def test_expired_deadline_prevents_create():
    """Raising expiry must prevent provider admission before ticket allocation."""
    host = Host(lambda: "late")
    with scope(raising=True) as (_, owner, context):
        budget = FirstByteBudget.create(1, clock=lambda: 10)
        budget.deadline = 9
        context[1]._deadline = 0
        with first_byte_budget_scope(budget), pytest.raises(TimeoutError):
            host._create_with_first_byte_timeout([])
        assert host.calls == []
        assert context[1].snapshot().outcome == "timeout"


def test_nested_foreign_model_does_not_inherit_invocation():
    """Only the bound model may acquire an active request-control authority."""
    model = object()
    route = runtime.ControlRoute("nested", os.getpid(), model, interrupt_supported=True)
    seen = []

    @runtime.invocation_control
    def chat(instance):
        """Observe invocation identity across explicit owner boundaries."""
        seen.append(runtime._INVOCATION.get())
        if instance is model:
            chat(object())
            seen.append(runtime._INVOCATION.get())

    with runtime.application_control_scope(route):
        chat(model)
    assert seen[0] is not None
    assert seen[1] is None
    assert seen[2] == seen[0]
    assert runtime._INVOCATION.get() is None


@pytest.mark.parametrize("phase", ["create", "fetch"])
@pytest.mark.parametrize("raising", [False, True])
def test_blocked_deadline_and_warning(monkeypatch, phase, raising):
    """Cross actual blocked worker waits with warning and raising policies."""
    entered = threading.Event()
    release = threading.Event()

    def response():
        """Hold creation or return a held first-record iterator."""
        if phase == "create":
            entered.set()
            assert release.wait(3)
        return records()

    def records():
        """Hold the first record until expiry is observed by the coordinator."""
        if phase == "fetch":
            entered.set()
            assert release.wait(3)
        yield "body"

    host = Host(response)
    original_warning = host._log_first_byte_timeout

    def warning(elapsed, timeout):
        """Release warning-only calls immediately after their one warning."""
        original_warning(elapsed, timeout)
        if not raising:
            release.set()

    host._log_first_byte_timeout = warning
    try:
        with scope(0.02, raising=raising) as (_, owner, context):
            if raising:
                with pytest.raises(TimeoutError):
                    result, _ = host._create_with_first_byte_timeout([], stream=True)
                    list(host.iter_stream_with_first_byte_timeout(result))
                assert context[1].snapshot().outcome == "timeout"
            else:
                result, _ = host._create_with_first_byte_timeout([], stream=True)
                assert list(host.iter_stream_with_first_byte_timeout(result)) == ["body"]
            assert entered.is_set()
            assert len(host.warnings) == 1
            release.set()
            for worker in (owner.create_thread, owner.fetch_thread, owner.cleanup_thread):
                if worker is not None:
                    worker.join(3)
    finally:
        release.set()


@pytest.mark.parametrize("operation", ["force_retry", "hard_interrupt"])
def test_live_control_releases_exact_late_creation(operation):
    """Queue from a concurrent operator while a real owner worker is blocked."""
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class Response:
        """Observe disposal of an otherwise undeliverable provider result."""

        def close(self):
            """Acknowledge exact stale response cleanup."""
            closed.set()

    def response():
        """Publish only after the coordinator has abandoned this worker."""
        entered.set()
        assert release.wait(3)
        return Response()

    host = Host(response)
    with scope() as (route, owner, context):
        def operator():
            """Submit through canonical authority after real provider admission."""
            assert entered.wait(3)
            REQUEST_CONTROL.submit(context[1].target, "live-" + route.binding_id, operation)

        operator_thread = threading.Thread(target=operator)
        operator_thread.start()
        try:
            with pytest.raises((runtime.LLMRequestedRetryError, runtime.LLMControlledInterruptError)):
                host._create_with_first_byte_timeout([], stream=False)
            assert not owner.control_cleanup_settled()
        finally:
            release.set()
            operator_thread.join(3)
            owner.create_thread.join(3)
        assert closed.wait(3)
        if owner.cleanup_thread:
            owner.cleanup_thread.join(3)
        route.reconcile()
        assert owner.control_cleanup_settled()


@pytest.mark.parametrize("payload,error", [
    ({"operation": "invalid"}, "invalid_operation"),
    ({"operation": "force_retry"}, "exact target required"),
    ({"operation": "force_retry", "target": {}}, "AttemptTarget"),
    ({"operation": "status", "command_id": "absent"}, "unknown_command"),
])
def test_handler_malformed_and_unknown(payload, error):
    """Reject malformed commands before allocating or selecting custody."""
    with scope() as (route, owner, context):
        channel = ControlContext(session_id="unit", pid=os.getpid(), agent_chat=SimpleNamespace(
            ai_agent=route.agent, _llm_control_route=route))
        result = LLMControlHandler().handle(ControlRequest("malformed", "llm_control", payload), channel)
        assert error in result.error
        assert context[1].snapshot().outcome is None


def test_handler_retained_status_and_stale_generation():
    """Expose detached retained receipts but never accept a foreign generation."""
    with scope() as (route, owner, context):
        channel = ControlContext(session_id="unit", pid=os.getpid(), agent_chat=SimpleNamespace(
            ai_agent=route.agent, _llm_control_route=route))
        handler = LLMControlHandler()
        command = "retained-" + route.binding_id
        REQUEST_CONTROL.submit(context[1].target, command, "force_retry")
        result = handler.handle(ControlRequest("status", "llm_control", {
            "command_id": command}), channel)
        assert result.result["state"] == "queued"
        target = asdict(context[1].target)
        target["generation"] += 1
        rejected = handler.handle(ControlRequest("stale", "llm_control", {
            "operation": "force_retry", "target": target}), channel)
        assert rejected.error == "stale_target"
        assert context[1].snapshot().outcome is None


def test_terminal_tick_and_expired_terminal_mapping():
    """Already published terminal facts prevent further Hook observations."""
    host = Host(lambda: "body")
    with scope() as (_, owner, context):
        assert context[1].publish("value")
        wait._tick(context, owner)
        wait._raise_terminal(context[1], owner, host, 1)


def test_worker_ticket_allocation_expiry():
    """Ticket setup may cross the original deadline but cannot admit provider I/O."""
    host = Host(lambda: "forbidden")
    with scope(raising=True) as (_, owner, context):
        budget = wait.current_first_byte_budget()

        def start():
            """Expire the same budget at the exact ticket admission boundary."""
            budget.deadline = 0
            context[1]._deadline = 0
            return object()

        host._start_first_byte_request = start
        with pytest.raises(TimeoutError):
            host._create_with_first_byte_timeout([])
        owner.create_thread.join(3)
        assert host.calls == []
        assert len(host.finished) == 1


def test_unrouted_attempt_scope():
    """No route leaves the legacy path unbound."""
    with runtime.attempt_control_scope(None, False) as context:
        assert context is None


@pytest.mark.parametrize("phase", ["create", "fetch"])
def test_late_error_cannot_replace_control(phase):
    """The original selected signal survives late worker exception diagnostics."""
    entered = threading.Event()
    release = threading.Event()
    error = ValueError("late owned failure")

    def provider():
        """Delay creation or expose the delayed fetch."""
        if phase == "create":
            entered.set()
            assert release.wait(3)
            raise error
        return records()

    def records():
        """Fail after control wins rather than producing stale content."""
        entered.set()
        assert release.wait(3)
        raise error
        yield

    host = Host(provider)
    with scope() as (route, owner, context):
        def operator():
            """Queue after the provider worker is definitely blocked."""
            assert entered.wait(3)
            REQUEST_CONTROL.submit(context[1].target, "late-error-" + route.binding_id, "hard_interrupt")

        operator_thread = threading.Thread(target=operator)
        operator_thread.start()
        try:
            with pytest.raises(runtime.LLMControlledInterruptError):
                response, _ = host._create_with_first_byte_timeout([], stream=True)
                list(host.iter_stream_with_first_byte_timeout(response))
        finally:
            release.set()
            operator_thread.join(3)
            for worker in (owner.create_thread, owner.fetch_thread):
                if worker:
                    worker.join(3)
        assert context[1].snapshot().outcome == "hard_interrupt"
        assert owner.primary_error is not error


def test_early_publication_does_not_warn_after_delayed_observation():
    """An already committed early result must not acquire a late warning."""
    host = Host(lambda: "body")
    budget = FirstByteBudget(10, 1, clock=lambda: 20)
    wait._warn_completed(host, budget, published_at=9)
    assert host.warnings == []
    wait._warn_completed(host, budget, published_at=10)
    wait._warn_completed(host, budget, published_at=11)
    assert host.warnings == [(1, 1)]


@pytest.mark.parametrize("boundary", ["bind", "retire"])
def test_setup_and_retirement_reconcile_once(monkeypatch, boundary):
    """An interrupted adapter retains exact retirement authority for retry."""
    route = runtime.ControlRoute("repair", os.getpid(), object(), interrupt_supported=True)
    error = KeyboardInterrupt("one-shot " + boundary)
    original = getattr(REQUEST_CONTROL, boundary)
    armed = [True]
    targets = []

    def interrupted(target, **kwargs):
        """Disarm before interruption so reconciliation uses the real operation."""
        targets.append(target)
        if armed[0]:
            armed[0] = False
            if boundary == "bind":
                original(target, **kwargs)
            raise error
        return original(target, **kwargs)

    monkeypatch.setattr(REQUEST_CONTROL, boundary, interrupted)
    with runtime.application_control_scope(route):
        token = runtime._INVOCATION.set("repair-invocation")
        try:
            with pytest.raises(KeyboardInterrupt) as caught:
                with runtime.attempt_control_scope(None, False):
                    pass
            assert caught.value is error
            route.reconcile()
            assert REQUEST_CONTROL.snapshot(targets[0]) is None
            assert route.target is None
            assert runtime.current_attempt_control() is None
            with runtime.attempt_control_scope(None, False) as context:
                assert context[1].target != targets[0]
            assert REQUEST_CONTROL.snapshot(targets[0]) is None
        finally:
            runtime._INVOCATION.reset(token)


@pytest.mark.parametrize("phase", ["create", "first_fetch"])
@pytest.mark.parametrize("control_first", [True, False])
def test_admission_linearization(phase, control_first):
    """Control forbids unadmitted work but cannot undo a prior admission."""
    with scope() as (route, owner, context):
        host = Host(lambda: "body")
        proposal = REQUEST_CONTROL.submit(
            context[1].target, "admit-" + route.binding_id, "hard_interrupt",
        ).proposal
        if control_first:
            with route.lock:
                assert REQUEST_CONTROL.select(context[1].target, proposal).state == "accepted"
            assert not wait._claim_operation(context, owner, host, 1, phase)
        else:
            assert wait._claim_operation(context, owner, host, 1, phase)
            with route.lock:
                assert REQUEST_CONTROL.select(context[1].target, proposal).state == "accepted"
            assert context[2]["admitted"] == phase
        assert not wait._claim_operation(context, owner, host, 1, "next")
        REQUEST_CONTROL.applied(proposal)
        REQUEST_CONTROL.settle(proposal)


def test_creation_error_publishes_exact_started_ticket():
    """Caller bookkeeping sees the started ticket even on provider failure."""
    error = ValueError("provider failure with accounting")

    def provider():
        """Raise after the worker has allocated its exact ticket."""
        raise error

    host = Host(provider)
    with scope() as (_, owner, context):
        with pytest.raises(ValueError) as caught:
            host._create_with_first_byte_timeout([])
        assert caught.value is error
        assert host.ticket is host.finished[0]
        assert len(host.finished) == 1


def test_retirement_failure_preserves_primary_and_journal(monkeypatch):
    """Teardown cannot replace a host interruption or discard exact retry authority."""
    route = runtime.ControlRoute("primary", os.getpid(), object(), interrupt_supported=True)
    primary = KeyboardInterrupt("primary")
    original = REQUEST_CONTROL.retire
    armed = [True]

    def retire(target):
        """Interrupt retirement once without repeating the injected failure."""
        if armed[0]:
            armed[0] = False
            raise RuntimeError("retirement interrupted")
        return original(target)

    monkeypatch.setattr(REQUEST_CONTROL, "retire", retire)
    with runtime.application_control_scope(route):
        token = runtime._INVOCATION.set("primary-invocation")
        try:
            with pytest.raises(KeyboardInterrupt) as caught:
                with runtime.attempt_control_scope(None, False) as context:
                    target = context[1].target
                    raise primary
            assert caught.value is primary
            # Recovery may already have retried on its independent worker.
            route.reconcile()
            assert REQUEST_CONTROL.snapshot(target) is None
            assert REQUEST_CONTROL.snapshot(target) is None
        finally:
            runtime._INVOCATION.reset(token)


def test_reconcile_does_not_acknowledge_undelivered_command():
    """Selected custody is not proof of delivery, even after route retirement."""
    with scope() as (route, owner, context):
        proposal = REQUEST_CONTROL.submit(
            context[1].target, "undelivered-" + route.binding_id, "hard_interrupt",
        ).proposal
        lease = context[2]["lease"]
        lease.proposal = proposal
        lease.signal = runtime.LLMControlledInterruptError("test", attempts=1)
        assert REQUEST_CONTROL.select(context[1].target, proposal).state == "accepted"
        route.reconcile()
        assert REQUEST_CONTROL.status(proposal.command_id).state == "accepted"
        lease.superseded = True
    route.reconcile()
    assert REQUEST_CONTROL.status(proposal.command_id).state == "rejected"
    assert REQUEST_CONTROL.status(proposal.command_id).reason == "interrupted_before_delivery"
