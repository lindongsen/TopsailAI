"""Focused tests for application-scoped Hook executor access."""

from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from topsailai.hooks.application_access import (
    HookApplicationAccess,
    bind_hook_application,
    get_hook_executor,
)
from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.contracts import DispatchReport, EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration

class _Scope:
    """Provide mutable scope state for access tests."""

    scope_id = "scope"
    closed = False

class _Registrar:
    """Provide observable registration methods for access-boundary tests."""

    def __init__(self):
        self.ensure_calls = []
        self.aensure_calls = []

    def ensure_registered(self, name, **kwargs):
        self.ensure_calls.append((name, kwargs))
        return type("Result", (), {"ready": True})()

    async def aensure_registered(self, name, **kwargs):
        self.aensure_calls.append((name, kwargs))
        return self.ensure_registered(name, **kwargs)

class _Runtime:
    """Provide observable runtime methods for access-boundary tests."""

    def __init__(self):
        self.make_event_calls = []
        self.dispatch_calls = []
        self.adispatch_calls = []

    def make_event(self, *args, **kwargs):
        self.make_event_calls.append((args, kwargs))
        return object()

    def dispatch_configured(self, *args, **kwargs):
        self.dispatch_calls.append((args, kwargs))
        return DispatchReport("event", 1)

    async def adispatch_configured(self, *args, **kwargs):
        self.adispatch_calls.append((args, kwargs))
        return DispatchReport("event", 1)

def _point(mode="sync", policy="report"):
    """Create a legacy-compatible catalog declaration."""
    return HookPointDeclaration(
        "hook_test_access",
        EventDefinition("test.access", 1, {"type": "object"}),
        "before",
        mode,
        "tests",
        failure_policy=policy,
        security_critical=policy == "block",
    )

def _assert_no_runtime_work(executor):
    """Assert unavailable access never reaches registration or Runtime execution."""
    assert executor._test_registrar.ensure_calls == []
    assert executor._test_registrar.aensure_calls == []
    assert executor._test_runtime.make_event_calls == []
    assert executor._test_runtime.dispatch_calls == []
    assert executor._test_runtime.adispatch_calls == []

def _executor(point):
    """Construct one real executor with side-effect-free doubles."""
    scope = _Scope()
    runtime = _Runtime()
    registrar = _Registrar()
    executor = ConfiguredHookExecutor(
        runtime, scope, registrar, HookPointCatalog((point,))
    )
    executor._test_runtime = runtime
    executor._test_registrar = registrar
    return executor, scope

def test_unbound_disabled_and_nested_bindings_restore_exact_context():
    """Bindings are isolated and nested exits restore the prior token."""
    point = _point()
    assert get_hook_executor().dispatch(point, payload={}).rejection_reason == "application_unbound"
    executor, _ = _executor(point)
    disabled = HookApplicationAccess(None)
    with bind_hook_application(disabled):
        assert get_hook_executor().dispatch(point, payload={}).rejection_reason == "application_disabled"
        facade = get_hook_executor()
        with bind_hook_application(HookApplicationAccess(executor)):
            assert get_hook_executor().dispatch(point, payload={}).rejection_reason is None
        assert get_hook_executor().dispatch(point, payload={}).rejection_reason == "application_disabled"
    assert facade.dispatch(point, payload={}).rejection_reason == "application_context_mismatch"

def test_stop_and_scope_close_reject_new_calls():
    """Stopping admission and closing the Scope never invoke the executor."""
    point = _point()
    executor, scope = _executor(point)
    application = HookApplicationAccess(executor)
    with bind_hook_application(application):
        application.stop_admission()
        assert get_hook_executor().dispatch(point, payload={}).rejection_reason == "application_closed"
        _assert_no_runtime_work(executor)
    application = HookApplicationAccess(executor)
    with bind_hook_application(application):
        scope.closed = True
        assert get_hook_executor().dispatch(point, payload={}).rejection_reason == "application_closed"
        _assert_no_runtime_work(executor)

def test_valid_sync_context_mismatch_does_no_runtime_work():
    """A valid declaration is rejected before work on a cached cross-context facade."""
    point = _point()
    executor, _ = _executor(point)
    original = HookApplicationAccess(executor)
    other = HookApplicationAccess(executor)
    with bind_hook_application(original):
        cached = get_hook_executor()
    with bind_hook_application(other):
        report = cached.dispatch(point, payload={})
    assert report.rejection_reason == "application_context_mismatch"
    _assert_no_runtime_work(executor)

@pytest.mark.asyncio
async def test_valid_async_scope_closed_does_no_runtime_work():
    """A valid declaration is rejected before work after the Scope closes."""
    point = _point("async")
    executor, scope = _executor(point)
    application = HookApplicationAccess(executor)
    scope.closed = True
    with bind_hook_application(application):
        report = await get_hook_executor().adispatch(point, payload={})
    assert report.rejection_reason == "application_closed"
    _assert_no_runtime_work(executor)

def test_async_context_isolation_and_execution_time_stop():
    """Async tasks inherit their own binding and observe stop when they run."""
    point = _point("async")
    executor, _ = _executor(point)
    application = HookApplicationAccess(executor)

    async def run():
        with bind_hook_application(application):
            facade = get_hook_executor()
            application.stop_admission()
            return (await facade.adispatch(point, payload={})).rejection_reason

    assert asyncio.run(run()) == "application_closed"

def test_copied_context_cannot_cross_thread_and_explicit_binding_can():
    """A copied parent context cannot authorize another thread."""
    point = _point()
    executor, _ = _executor(point)
    application = HookApplicationAccess(executor)
    result = []
    parent_context = contextvars.copy_context()
    ready = threading.Event()
    finished = threading.Event()

    def worker():
        ready.wait()
        result.append(
            parent_context.run(
                lambda: get_hook_executor().dispatch(
                    point, payload={}
                ).rejection_reason
            )
        )
        with bind_hook_application(application):
            result.append(get_hook_executor().dispatch(point, payload={}).rejection_reason)
        finished.set()

    with bind_hook_application(application):
        parent_context = contextvars.copy_context()
        thread = threading.Thread(target=worker)
        thread.start()
        ready.set()
        assert finished.wait(2)
        thread.join()
    assert result == ["application_context_mismatch", None]

def test_invalid_application_and_mode_are_rejected_and_block_is_fail_closed():
    """Invalid owners fail early and authorized blocking cannot be bypassed."""
    with pytest.raises(ValueError, match="invalid Hook application access"):
        HookApplicationAccess(object())
    point = _point(policy="block")
    executor, _ = _executor(point)
    application = HookApplicationAccess(executor)
    application.stop_admission()
    with bind_hook_application(application):
        with pytest.raises(RuntimeError):
            get_hook_executor().dispatch(point, payload={})
    async_point = _point("async")
    with bind_hook_application(application):
        with pytest.raises(ValueError, match="execution mode mismatch"):
            get_hook_executor().dispatch(async_point, payload={})

def test_exception_identity_and_forwarded_operation_are_preserved():
    """Forwarding preserves the existing executor result and raised exception."""
    point = _point()
    executor, _ = _executor(point)
    marker = object()
    executor.dispatch = lambda *args, **kwargs: marker
    application = HookApplicationAccess(executor)
    with bind_hook_application(application):
        assert get_hook_executor().dispatch(point, payload={}, operation="op") is marker
    error = RuntimeError("same")
    executor.dispatch = lambda *args, **kwargs: (_ for _ in ()).throw(error)
    with bind_hook_application(application):
        with pytest.raises(RuntimeError) as caught:
            get_hook_executor().dispatch(point, payload={})
    assert caught.value is error

@pytest.mark.asyncio
async def test_async_unbound_and_context_mismatch_are_reported():
    """Async validation runs when the coroutine is executed."""
    point = _point("async")
    facade = get_hook_executor()
    assert (await facade.adispatch(point, payload={})).rejection_reason == "application_unbound"
    executor, _ = _executor(point)
    with bind_hook_application(HookApplicationAccess(executor)):
        cached = get_hook_executor()
    assert (await cached.adispatch(point, payload={})).rejection_reason == "application_context_mismatch"
    _assert_no_runtime_work(executor)

    stopped = HookApplicationAccess(executor)
    stopped.stop_admission()
    with bind_hook_application(stopped):
        assert (await get_hook_executor().adispatch(point, payload={})).rejection_reason == "application_closed"
    _assert_no_runtime_work(executor)

def test_invalid_point_and_binding_are_rejected():
    """Malformed declarations and bindings fail without forwarding."""
    point = _point()
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        get_hook_executor().dispatch(object(), payload={})
    with pytest.raises(ValueError, match="invalid Hook application access"):
        with bind_hook_application(object()):
            pass
    executor, _ = _executor(point)
    with bind_hook_application(HookApplicationAccess(executor)):
        with pytest.raises(ValueError, match="invalid Hook-point declaration"):
            get_hook_executor().dispatch(object(), payload={})

def test_admitted_async_call_preserves_result_and_releases_admission():
    """An async call forwards and remains usable after the first call settles."""
    point = _point("async")
    executor, _ = _executor(point)
    application = HookApplicationAccess(executor)
    with bind_hook_application(application):
        facade = get_hook_executor()
        first = asyncio.run(facade.adispatch(point, payload={}))
        second = asyncio.run(facade.adispatch(point, payload={}))
    assert first.event_id == second.event_id == "event"

def test_forwarding_preserves_payload_operation_cancellation_and_releases_admission():
    """Forwarding preserves every supported synchronous argument."""
    point = _point()
    executor, _ = _executor(point)
    calls = []
    marker = object()
    operation = object()
    signal = threading.Event()

    def dispatch(*args, **kwargs):
        calls.append((args, kwargs))
        return marker

    executor.dispatch = dispatch
    application = HookApplicationAccess(executor)
    payload = {"value": 1}
    with bind_hook_application(application):
        assert get_hook_executor().dispatch(
            point, payload=payload, operation=operation, cancellation=signal
        ) is marker
    assert len(calls) == 1
    assert calls[0][0] == (point,)
    assert calls[0][1]["payload"] is payload
    assert calls[0][1]["operation"] is operation
    assert calls[0][1]["cancellation"] is signal
    assert application._in_flight == 0

def test_exception_and_keyboard_interrupt_release_admission():
    """All executor exits release admission without replacing host exceptions."""
    point = _point()
    executor, _ = _executor(point)
    application = HookApplicationAccess(executor)
    errors = (RuntimeError("ordinary"), KeyboardInterrupt())
    for error in errors:
        def raise_error(*args, error=error, **kwargs):
            del args, kwargs
            raise error

        executor.dispatch = raise_error
        with bind_hook_application(application):
            with pytest.raises(type(error)) as caught:
                get_hook_executor().dispatch(point, payload={})
        assert caught.value is error
        assert application._in_flight == 0

def test_async_tasks_keep_application_bindings_isolated():
    """Concurrent tasks retain independently bound applications and arguments."""
    point = _point("async")
    executor_a, _ = _executor(point)
    executor_b, _ = _executor(point)
    application_a = HookApplicationAccess(executor_a)
    application_b = HookApplicationAccess(executor_b)
    payload_a, payload_b = object(), object()
    operation_a, operation_b = object(), object()
    calls = []

    async def dispatch(*args, **kwargs):
        calls.append((args[0], kwargs["payload"], kwargs["operation"]))
        return DispatchReport("A" if kwargs["payload"] is payload_a else "B", 1)

    executor_a.adispatch = dispatch
    executor_b.adispatch = dispatch

    async def run(application, payload, operation):
        with bind_hook_application(application):
            return await get_hook_executor().adispatch(
                point, payload=payload, operation=operation
            )

    async def main():
        return await asyncio.gather(
            run(application_a, payload_a, operation_a),
            run(application_b, payload_b, operation_b),
        )

    reports = asyncio.run(main())
    assert [report.event_id for report in reports] == ["A", "B"]
    assert calls[0][1] is payload_a and calls[0][2] is operation_a
    assert calls[1][1] is payload_b and calls[1][2] is operation_b

class _BlockingDispatch:
    """Coordinate one admitted synchronous dispatch without timing sleeps."""

    def __init__(self, result=None, error=None):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.result = result
        self.error = error

    def __call__(self, *args, **kwargs):
        del args, kwargs
        self.calls += 1
        self.started.set()
        assert self.release.wait(2)
        if self.error is not None:
            raise self.error
        return self.result

def test_stop_admission_does_not_wait_for_admitted_sync_work():
    """Stopping admission returns while admitted work remains outside the lock."""
    point = _point()
    executor, _ = _executor(point)
    marker = object()
    blocking = _BlockingDispatch(result=marker)
    executor.dispatch = blocking
    application = HookApplicationAccess(executor)
    result = []

    def call():
        with bind_hook_application(application):
            result.append(get_hook_executor().dispatch(point, payload={}))

    thread = threading.Thread(target=call)
    thread.start()
    assert blocking.started.wait(2)
    application.stop_admission()
    with bind_hook_application(application):
        rejected = get_hook_executor().dispatch(point, payload={})
    assert rejected.rejection_reason == "application_closed"
    assert blocking.calls == 1
    assert application._in_flight == 1
    blocking.release.set()
    thread.join(2)
    assert result == [marker]
    assert application._in_flight == 0

def test_stop_admission_sync_admitted_exception_settles_exactly():
    """An admitted exception survives stop and releases its admission slot."""
    point = _point()
    executor, _ = _executor(point)
    error = RuntimeError("admitted")
    blocking = _BlockingDispatch(error=error)
    executor.dispatch = blocking
    application = HookApplicationAccess(executor)
    result = []

    def call():
        with bind_hook_application(application):
            with pytest.raises(RuntimeError) as caught:
                get_hook_executor().dispatch(point, payload={})
            result.append(caught.value)

    thread = threading.Thread(target=call)
    thread.start()
    assert blocking.started.wait(2)
    application.stop_admission()
    blocking.release.set()
    thread.join(2)
    assert result == [error]
    assert application._in_flight == 0

@pytest.mark.asyncio
async def test_async_tasks_route_to_distinct_applications_with_suspension():
    """Interleaved tasks retain distinct application routing across an await."""
    point = _point("async")
    executor_a, _ = _executor(point)
    executor_b, _ = _executor(point)
    application_a = HookApplicationAccess(executor_a)
    application_b = HookApplicationAccess(executor_b)
    entered = {"A": asyncio.Event(), "B": asyncio.Event()}
    release = {"A": asyncio.Event(), "B": asyncio.Event()}
    calls = []

    async def dispatch_a(*args, **kwargs):
        del args, kwargs
        calls.append("A")
        entered["A"].set()
        await release["A"].wait()
        return DispatchReport("A", 1)

    async def dispatch_b(*args, **kwargs):
        del args, kwargs
        calls.append("B")
        entered["B"].set()
        await release["B"].wait()
        return DispatchReport("B", 1)

    executor_a.adispatch = dispatch_a
    executor_b.adispatch = dispatch_b

    async def run(application):
        with bind_hook_application(application):
            return await get_hook_executor().adispatch(point, payload={})

    task_a = asyncio.create_task(run(application_a))
    task_b = asyncio.create_task(run(application_b))
    await entered["A"].wait()
    await entered["B"].wait()
    assert calls == ["A", "B"]
    release["B"].set()
    release["A"].set()
    reports = await asyncio.gather(task_a, task_b)
    assert [report.event_id for report in reports] == ["A", "B"]
    assert application_a._in_flight == application_b._in_flight == 0

@pytest.mark.asyncio
async def test_async_stop_rejects_later_call_and_cancellation_releases_admission():
    """Pending async work settles across stop and host cancellation releases accounting."""
    point = _point("async")
    executor, _ = _executor(point)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def dispatch(*args, **kwargs):
        del args, kwargs
        entered.set()
        await release.wait()
        return DispatchReport("admitted", 1)

    executor.adispatch = dispatch
    application = HookApplicationAccess(executor)
    with bind_hook_application(application):
        facade = get_hook_executor()
        admitted = asyncio.create_task(facade.adispatch(point, payload={}))
        await entered.wait()
        application.stop_admission()
        rejected = await facade.adispatch(point, payload={})
        assert rejected.rejection_reason == "application_closed"
        assert application._in_flight == 1
        release.set()
        assert (await admitted).event_id == "admitted"
        assert application._in_flight == 0

    active = HookApplicationAccess(executor)
    entered.clear()
    release.clear()
    with bind_hook_application(active):
        facade = get_hook_executor()
        cancelled = asyncio.create_task(facade.adispatch(point, payload={}))
        await entered.wait()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
    assert active._in_flight == 0

def test_forged_declarations_are_rejected_before_unavailable_paths():
    """Catalog ownership precedes stopped, closed, and context-mismatch reports."""
    point = _point()
    forged = HookPointDeclaration(
        point.name,
        EventDefinition("forged.access", 1, {"type": "object"}),
        point.phase,
        point.mode,
        point.owner,
    )
    executor, scope = _executor(point)

    stopped = HookApplicationAccess(executor)
    stopped.stop_admission()
    with bind_hook_application(stopped):
        with pytest.raises(ValueError, match="catalog-owned"):
            get_hook_executor().dispatch(forged, payload={})
    _assert_no_runtime_work(executor)

    closed = HookApplicationAccess(executor)
    scope.closed = True
    with bind_hook_application(closed):
        with pytest.raises(ValueError, match="catalog-owned"):
            get_hook_executor().dispatch(forged, payload={})
    _assert_no_runtime_work(executor)
    scope.closed = False

    original = HookApplicationAccess(executor)
    other = HookApplicationAccess(executor)
    with bind_hook_application(original):
        cached = get_hook_executor()
    with bind_hook_application(other):
        with pytest.raises(ValueError, match="catalog-owned"):
            cached.dispatch(forged, payload={})
    _assert_no_runtime_work(executor)

@pytest.mark.asyncio
async def test_forged_async_declarations_rejected_on_all_unavailable_paths():
    """Async unavailable paths reject forged declarations before reporting."""
    point = _point("async")
    forged = HookPointDeclaration(
        point.name,
        EventDefinition("forged.async", 1, {"type": "object"}),
        point.phase,
        point.mode,
        point.owner,
    )
    executor, scope = _executor(point)

    stopped = HookApplicationAccess(executor)
    stopped.stop_admission()
    with bind_hook_application(stopped):
        with pytest.raises(ValueError, match="catalog-owned"):
            await get_hook_executor().adispatch(forged, payload={})
    _assert_no_runtime_work(executor)

    closed = HookApplicationAccess(executor)
    scope.closed = True
    with bind_hook_application(closed):
        with pytest.raises(ValueError, match="catalog-owned"):
            await get_hook_executor().adispatch(forged, payload={})
    _assert_no_runtime_work(executor)
    scope.closed = False

    original = HookApplicationAccess(executor)
    other = HookApplicationAccess(executor)
    with bind_hook_application(original):
        cached = get_hook_executor()
    with bind_hook_application(other):
        with pytest.raises(ValueError, match="catalog-owned"):
            await cached.adispatch(forged, payload={})
    _assert_no_runtime_work(executor)

def test_nested_exception_restores_outer_binding():
    """Exceptional nested exits restore the exact outer application."""
    point = _point()
    executor_a, _ = _executor(point)
    executor_b, _ = _executor(point)
    outer = HookApplicationAccess(executor_a)
    inner = HookApplicationAccess(executor_b)
    with bind_hook_application(outer):
        with pytest.raises(ValueError):
            with bind_hook_application(inner):
                assert get_hook_executor()._binding.application is inner
                raise ValueError("nested")
        assert get_hook_executor()._binding.application is outer

def test_to_thread_copied_context_requires_explicit_rebinding():
    """Context propagation to a worker thread is rejected until explicitly rebound."""
    point = _point()
    executor, _ = _executor(point)
    application = HookApplicationAccess(executor)

    async def run():
        with bind_hook_application(application):
            copied = await asyncio.to_thread(
                lambda: get_hook_executor().dispatch(point, payload={})
            )
            explicit = await asyncio.to_thread(
                lambda: _explicit_thread_bind(application, point)
            )
            return copied, explicit

    copied, explicit = asyncio.run(run())
    assert copied.rejection_reason == "application_context_mismatch"
    assert explicit.rejection_reason is None

def _explicit_thread_bind(application, point):
    """Bind explicitly in a worker thread for the propagation regression."""
    with bind_hook_application(application):
        return get_hook_executor().dispatch(point, payload={})

def test_application_access_has_no_external_side_effects(monkeypatch):
    """Guard application-access construction and unavailable dispatch boundaries."""
    import builtins
    import os
    from pathlib import Path

    point = _point()
    executor, _ = _executor(point)
    touched = []

    def forbidden(*args, **kwargs):
        touched.append((args, kwargs))
        raise AssertionError("unexpected external access")

    class _EnvironmentGuard:
        def get(self, *args, **kwargs):
            return forbidden(*args, **kwargs)

        def __getitem__(self, key):
            return forbidden(key)

    with monkeypatch.context() as patch:
        patch.setattr(os, "environ", _EnvironmentGuard())
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(os, "stat", forbidden)
        patch.setattr(Path, "exists", forbidden)
        patch.setattr(Path, "stat", forbidden)
        patch.setattr("topsailai.hooks.configured_executor.HookRuntime", forbidden)
        application = HookApplicationAccess(executor)
        application.stop_admission()
        with bind_hook_application(application):
            report = get_hook_executor().dispatch(point, payload={})
    assert report.rejection_reason == "application_closed"
    assert touched == []

def test_decorator_provider_uses_accessor_and_preserves_phase_cardinality():
    """A decorator can obtain the accessor while retaining return and exception semantics."""
    from topsailai.hooks.hook_point_decorator import hook_point

    before = _point("sync")
    success = HookPointDeclaration(
        "hook_test_success", EventDefinition("test.success", 1, {"type": "object"}),
        "success", "sync", "tests"
    )
    error = HookPointDeclaration(
        "hook_test_error", EventDefinition("test.error", 1, {"type": "object"}),
        "error", "sync", "tests"
    )
    scope = _Scope()
    executor = ConfiguredHookExecutor(
        _Runtime(), scope, _Registrar(), HookPointCatalog((before, success, error))
    )
    calls = []

    def dispatch(point, **kwargs):
        calls.append((point.name, kwargs))
        return DispatchReport("event", 1)

    executor.dispatch = dispatch
    application = HookApplicationAccess(executor)

    returned = object()

    @hook_point(before=before, success=success, error=error,
                executor_provider=get_hook_executor)
    def successful():
        return returned

    with bind_hook_application(application):
        assert successful() is returned
    assert [name for name, _ in calls] == [before.name, success.name]

    calls.clear()
    expected = RuntimeError("business")

    @hook_point(before=before, success=success, error=error,
                executor_provider=get_hook_executor)
    def failing():
        raise expected

    with bind_hook_application(application):
        with pytest.raises(RuntimeError) as caught:
            failing()
    assert caught.value is expected
    assert [name for name, _ in calls] == [before.name, error.name]
