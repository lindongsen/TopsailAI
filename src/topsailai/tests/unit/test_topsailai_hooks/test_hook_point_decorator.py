"""Tests for sync and async Hook-point decorators."""
from __future__ import annotations
import asyncio
import inspect
import traceback
import pytest
from topsailai.hooks.configured_executor import HookPointBlockedError
from topsailai.hooks.contracts import DispatchReport, EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration
from topsailai.hooks.hook_point_decorator import HookInvocationView, hook_point

def _point(name, phase, mode="sync", policy="report", success_block=False, **kwargs):
    return HookPointDeclaration(name,EventDefinition(f"test.{name}",1,{"type":"object"}),phase,mode,"tests",failure_policy=policy,security_critical=policy=="block",allow_post_success_block=success_block,**kwargs)

class _Executor:
    def __init__(self, failures=()): self.calls=[]; self.failures=set(failures)
    def dispatch(self,point,*,payload,operation=None):
        self.calls.append((point.phase,payload,operation))
        if point.phase in self.failures: raise HookPointBlockedError(point.name,"blocked")
        return DispatchReport(str(len(self.calls)),1)
    async def adispatch(self,point,*,payload,operation=None): return self.dispatch(point,payload=payload,operation=operation)

def _builder(view: HookInvocationView):
    return {"phase":view.phase}

def test_sync_cardinality_success_and_error_preserve_result_and_exception():
    before=_point("hook_before","before"); success=_point("hook_success","success"); error=_point("hook_error","error"); executor=_Executor()
    @hook_point(before=before,success=success,error=error,executor_provider=lambda:executor,payload_builder=_builder)
    def operation(fail=False):
        if fail: raise LookupError("boom")
        return marker
    marker=object()
    assert operation() is marker
    assert [x[0] for x in executor.calls]==["before","success"]
    executor.calls.clear()
    original=LookupError("original")
    @hook_point(before=before,success=success,error=error,executor_provider=lambda:executor,payload_builder=_builder)
    def failing(): raise original
    with pytest.raises(LookupError) as caught: failing()
    assert caught.value is original
    assert "failing" in [frame.name for frame in traceback.extract_tb(caught.value.__traceback__)]
    assert [x[0] for x in executor.calls]==["before","error"]

def test_error_hook_failure_never_replaces_business_exception():
    error=_point("hook_error","error",policy="block"); executor=_Executor({"error"}); original=RuntimeError("business")
    @hook_point(error=error,executor_provider=lambda:executor)
    def failing(): raise original
    with pytest.raises(RuntimeError) as caught: failing()
    assert caught.value is original and caught.value.__context__ is None

def test_before_block_prevents_entry_and_success_block_follows_business_work():
    before=_point("hook_before","before",policy="block"); success=_point("hook_success","success",policy="block",success_block=True)
    entered=[]
    @hook_point(before=before,executor_provider=lambda:_Executor({"before"}))
    def blocked(): entered.append(True)
    with pytest.raises(HookPointBlockedError): blocked()
    assert entered==[]
    executor=_Executor({"success"})
    @hook_point(success=success,executor_provider=lambda:executor)
    def completed(): entered.append(True); return 1
    with pytest.raises(HookPointBlockedError): completed()
    assert entered==[True]

def test_async_cardinality_and_method_metadata_signature():
    points=[_point("hook_async_before","before","async"),_point("hook_async_success","success","async"),_point("hook_async_error","error","async")]; executor=_Executor()
    class Service:
        hook_executor=executor
        @hook_point(before=points[0],success=points[1],error=points[2],executor_attribute="hook_executor",payload_builder=_builder)
        async def run(self,value:int)->int:
            """Keep metadata."""
            return value
    method=Service().run
    assert asyncio.run(method(3))==3
    assert method.__name__=="run" and method.__doc__=="Keep metadata."
    assert str(inspect.signature(method))=="(value: 'int') -> 'int'"
    assert [x[0] for x in executor.calls]==["before","success"]

def test_recursive_occurrences_track_parent_and_depth():
    before=_point("hook_before","before"); executor=_Executor()
    @hook_point(before=before,executor_provider=lambda:executor)
    def recurse(value):
        return recurse(value-1) if value else 0
    assert recurse(2)==0
    operations=[x[2] for x in executor.calls]
    assert [x.depth for x in operations]==[0,1,2]
    assert operations[1].parent_operation_id==operations[0].operation_id

def test_idempotence_conflict_and_generator_rejection():
    before=_point("hook_before","before")
    decorator=hook_point(before=before,executor_provider=lambda:executor)
    executor=_Executor()
    def plain(): return 1
    wrapped=decorator(plain)
    assert decorator(wrapped) is wrapped
    with pytest.raises(ValueError,match="conflicting"):
        hook_point(success=_point("hook_success","success"),executor_provider=lambda:executor)(wrapped)
    def generator(): yield 1
    async def async_generator(): yield 1
    with pytest.raises(TypeError,match="generator"): decorator(generator)
    with pytest.raises(TypeError,match="generator"): decorator(async_generator)


def test_async_error_hook_failure_preserves_original_exception_and_traceback():
    error = _point("hook_async_error", "error", "async", policy="block")
    executor = _Executor({"error"})
    original = RuntimeError("async business")

    @hook_point(error=error, executor_provider=lambda: executor)
    async def failing():
        raise original

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(failing())
    assert caught.value is original
    assert caught.value.__context__ is None
    assert "failing" in [
        frame.name for frame in traceback.extract_tb(caught.value.__traceback__)
    ]
    assert [item[0] for item in executor.calls] == ["error"]


def test_decorator_definition_and_executor_dependency_validation():
    before = _point("hook_before", "before")
    async_success = _point("hook_async_success", "success", "async")
    executor = _Executor()

    with pytest.raises(ValueError, match="at least one"):
        hook_point(executor_provider=lambda: executor)
    with pytest.raises(ValueError, match="phase mismatch"):
        hook_point(before=_point("hook_wrong", "success"), executor_provider=lambda: executor)
    with pytest.raises(ValueError, match="execution mode"):
        hook_point(before=before, success=async_success, executor_provider=lambda: executor)
    with pytest.raises(ValueError, match="exactly one"):
        hook_point(before=before)
    with pytest.raises(ValueError, match="exactly one"):
        hook_point(before=before, executor_attribute="hooks", executor_provider=lambda: executor)
    with pytest.raises(ValueError, match="payload builder"):
        hook_point(before=before, executor_provider=lambda: executor, payload_builder=object())

    decorator = hook_point(before=before, executor_provider=lambda: executor)
    with pytest.raises(TypeError, match="ordinary function"):
        decorator(object())

    @hook_point(before=before, executor_provider=lambda: object())
    def unavailable():
        return None

    with pytest.raises(ValueError, match="dependency is unavailable"):
        unavailable()


def test_builder_sees_only_detached_declared_argument_and_result_fields():
    """Builders cannot observe denied credentials or live mutable business values."""
    before = _point(
        "hook_safe_before", "before", argument_fields=("record",),
        sensitive_fields=("password",),
    )
    success = _point(
        "hook_safe_success", "success", argument_fields=("record",),
        result_fields=("status",),
    )
    executor = _Executor()
    seen = []

    def builder(view):
        seen.append(view)
        assert "password" not in view.arguments
        assert "hidden" not in view.arguments
        if view.phase == "before":
            view.arguments["record"]["items"].append("builder")
            return {"record": view.arguments["record"]}
        view.result["status"]["items"].append("builder")
        return {"status": view.result["status"]}

    @hook_point(
        before=before, success=success, executor_provider=lambda: executor,
        payload_builder=builder,
    )
    def operation(record, password, hidden):
        record["items"].append("business")
        return {"status": {"items": ["result"]}, "credential": password}

    record = {"items": ["caller"]}
    result = operation(record, "secret", {"live": []})
    assert record == {"items": ["caller", "business"]}
    assert result == {"status": {"items": ["result"]}, "credential": "secret"}
    assert seen[0].arguments == {"record": {"items": ["caller", "builder"]}}
    assert seen[0].result == {}
    assert seen[1].arguments == {"record": {"items": ["caller", "business"]}}
    assert seen[1].result == {"status": {"items": ["result", "builder"]}}


def test_default_deny_hides_raw_values_and_error_metadata_requires_authority():
    """Default views exclude raw arguments, results, exceptions, and tracebacks."""
    success = _point("hook_default_success", "success")
    error = _point("hook_safe_error", "error", error_fields=("type",))
    executor = _Executor()
    views = []

    def builder(view):
        views.append(view)
        assert not hasattr(view, "exception")
        assert not hasattr(view, "traceback")
        return {}

    @hook_point(
        success=success, error=error, executor_provider=lambda: executor,
        payload_builder=builder,
    )
    def operation(token, fail=False):
        if fail:
            raise RuntimeError(token)
        return {"token": token}

    assert operation("credential") == {"token": "credential"}
    assert views[-1].arguments == {} and views[-1].result == {}
    original = RuntimeError("secret message")

    @hook_point(error=error, executor_provider=lambda: executor, payload_builder=builder)
    def failing():
        raise original

    with pytest.raises(RuntimeError) as caught:
        failing()
    assert caught.value is original
    assert views[-1].error == {"type": "RuntimeError"}
    assert "failing" in [frame.name for frame in traceback.extract_tb(caught.value.__traceback__)]


def test_async_builder_receives_detached_authorized_values():
    """Async decorators apply the same detached allowlist boundary."""
    success = _point(
        "hook_async_safe_success", "success", "async",
        argument_fields=("value",), result_fields=("value",),
    )
    executor = _Executor()

    def builder(view):
        view.arguments["value"]["items"].append("hook")
        view.result["value"]["items"].append("hook")
        return {}

    @hook_point(success=success, executor_provider=lambda: executor, payload_builder=builder)
    async def operation(value, credential):
        return {"value": value, "credential": credential}

    value = {"items": ["business"]}
    result = asyncio.run(operation(value, "secret"))
    assert value == {"items": ["business"]}
    assert result == {"value": value, "credential": "secret"}


def test_error_metadata_never_invokes_exception_string_conversion():
    """Authorized error tokens avoid arbitrary exception formatting code."""
    error = _point(
        "hook_safe_error_message", "error", error_fields=("type", "message"),
    )
    executor = _Executor()
    views = []

    class HostileError(RuntimeError):
        def __str__(self):
            raise AssertionError("exception string conversion must not run")

    @hook_point(
        error=error, executor_provider=lambda: executor,
        payload_builder=lambda view: views.append(view) or {},
    )
    def failing():
        raise HostileError("detached message")

    with pytest.raises(HostileError):
        failing()
    assert views[-1].error == {
        "type": "HostileError",
        "message": "detached message",
    }
    assert [item[0] for item in executor.calls] == ["error"]


def test_declaration_rejects_ambiguous_or_unauthorized_exposure():
    """Phase policy cannot expose unavailable or explicitly sensitive fields."""
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_bad_before", "before", result_fields=("value",))
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_bad_success", "success", error_fields=("type",))
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point(
            "hook_bad_sensitive", "before", argument_fields=("password",),
            sensitive_fields=("password",),
        )
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        _point("hook_bad_error", "error", error_fields=("traceback",))


class _PolicyRuntime:
    """Supply execution facts while leaving Catalog enforcement to the real facade."""

    def __init__(self, status, cleanup="safe", interrupt=False):
        """Track exact dispatch cardinality and immutable reports."""
        self.status = status
        self.cleanup = cleanup
        self.interrupt = interrupt
        self.calls = []
        self.reports = []

    def make_event(self, scope, name, version, payload, **metadata):
        """Create a real event with the wrapper's occurrence metadata."""
        from topsailai.hooks.contracts import HookEvent

        return HookEvent("event", name, version, "owner", scope.scope_id,
            metadata["operation_id"], metadata.get("parent_operation_id"),
            1, "now", metadata["layer"], metadata["purpose"], payload)

    def dispatch_configured(self, name, event):
        """Return controlled unified facts without simulating policy enforcement."""
        from topsailai.hooks.result_contracts import (
            HandlerIdentity, HandlerResult, HookPointResult, ResultCleanup,
            ResultDecision, ReturnedValue,
        )

        self.calls.append((name, event))
        if self.interrupt:
            raise asyncio.CancelledError("host cancellation")
        handlers = () if self.status == "unavailable" else (
            HandlerResult("execution", name, 1,
                HandlerIdentity("default", "default", "default_script_hook"),
                returned=ReturnedValue(True, "direct", {"decision": "block"}),
                decision=ResultDecision("block", "catalog")),
        )
        result = HookPointResult("execution", name, 1, self.status, handlers,
            cleanup=ResultCleanup(self.cleanup),
            decision=ResultDecision("block", "catalog")
            if self.status == "blocked" else ResultDecision())
        report = DispatchReport(event.event_id, 1, unified_result=result)
        self.reports.append(report)
        return report

    async def adispatch_configured(self, name, event):
        """Drive the same fact source through the facade's asynchronous boundary."""
        return self.dispatch_configured(name, event)

    def emit_configured(self, name, event):
        """Reject accidental non-waiting execution in wrapper regressions."""
        raise AssertionError("wrapper must await execution, not emit")


class _PolicyRegistrar:
    """Record registration requests without owning external resources."""

    def __init__(self):
        """Start one exact registration ledger."""
        self.calls = []

    def ensure_registered(self, name):
        """Authorize an already prepared configuration, not a block decision."""
        from topsailai.hooks.configured_registration import RegistrationEnsureResult, RegistrationState

        self.calls.append(name)
        return RegistrationEnsureResult(RegistrationState.READY)

    async def aensure_registered(self, name):
        """Expose registration over the actual async facade path."""
        return self.ensure_registered(name)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("phase", ["before", "success", "error"])
@pytest.mark.parametrize("policy", ["report", "block"])
@pytest.mark.parametrize("status", ["success", "completed_with_errors", "blocked", "timeout", "cancelled", "unavailable"])
def test_real_executor_wrapper_policy_matrix(mode, phase, policy, status):
    """Verify Catalog blocking, exactly-once work and original error preservation."""
    from types import SimpleNamespace
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor
    from topsailai.hooks.hook_point_catalog import HookPointCatalog

    point = _point("hook_real_" + phase, phase, mode, policy,
        success_block=phase == "success" and policy == "block")
    runtime = _PolicyRuntime(status)
    registrar = _PolicyRegistrar()
    executor = ConfiguredHookExecutor(runtime, SimpleNamespace(scope_id="scope"),
        registrar, HookPointCatalog((point,)))
    entered = []
    marker = object()
    original = LookupError("original business failure")

    def business():
        """Publish the business side effect before returning or raising."""
        entered.append("completed mutation")
        if phase == "error":
            raise original
        return marker

    async def async_business():
        """Preserve the same business behavior under an asynchronous callable."""
        return business()

    wrapped = hook_point(**{phase: point}, executor_provider=lambda: executor)(
        business if mode == "sync" else async_business)

    def invoke():
        """Call the wrapper in its declared mode without replacing the facade."""
        return wrapped() if mode == "sync" else asyncio.run(wrapped())

    blocked = policy == "block" and status != "success"
    if phase == "error":
        with pytest.raises(LookupError) as caught:
            invoke()
        assert caught.value is original
        assert caught.value.__context__ is None
        assert "business" in [frame.name for frame in traceback.extract_tb(original.__traceback__)]
    elif blocked:
        with pytest.raises(HookPointBlockedError) as caught:
            invoke()
        assert caught.value.point_name == point.name
        assert caught.value.reason == status
    else:
        assert invoke() is marker
    assert entered == ([] if phase == "before" and blocked else ["completed mutation"])
    assert registrar.calls == [point.name]
    assert len(runtime.calls) == len(runtime.reports) == 1
    assert runtime.calls[0][1].purpose == phase
    assert runtime.reports[0].unified_result.status == status


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("cleanup", ["pending", "failed"])
def test_real_executor_success_cleanup_does_not_rollback_or_block(mode, cleanup):
    """Cleanup-only facts do not authorize a post-success business block."""
    from types import SimpleNamespace
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor
    from topsailai.hooks.hook_point_catalog import HookPointCatalog

    point = _point("hook_real_success", "success", mode, "block", success_block=True)
    runtime = _PolicyRuntime("success", cleanup)
    registrar = _PolicyRegistrar()
    executor = ConfiguredHookExecutor(runtime, SimpleNamespace(scope_id="scope"),
        registrar, HookPointCatalog((point,)))
    mutations = []
    marker = object()

    def business():
        """Keep completed mutations independently of cleanup observations."""
        mutations.append("committed")
        return marker

    async def async_business():
        """Run the same mutation once in async mode."""
        return business()

    wrapped = hook_point(success=point, executor_provider=lambda: executor)(
        business if mode == "sync" else async_business)
    result = wrapped() if mode == "sync" else asyncio.run(wrapped())
    assert result is marker
    assert mutations == ["committed"]
    assert registrar.calls == [point.name]
    assert len(runtime.calls) == len(runtime.reports) == 1
    assert runtime.reports[0].unified_result.cleanup.state == cleanup
    assert runtime.reports[0].unified_result.decision.action == "continue"


@pytest.mark.parametrize("phase", ["before", "success", "error"])
def test_real_executor_async_host_cancellation_propagates(phase):
    """Host interrupts propagate without replay or ordinary completion behavior."""
    from types import SimpleNamespace
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor
    from topsailai.hooks.hook_point_catalog import HookPointCatalog

    point = _point("hook_real_" + phase, phase, "async")
    runtime = _PolicyRuntime("success", interrupt=True)
    registrar = _PolicyRegistrar()
    executor = ConfiguredHookExecutor(runtime, SimpleNamespace(scope_id="scope"),
        registrar, HookPointCatalog((point,)))
    entered = []

    @hook_point(**{phase: point}, executor_provider=lambda: executor)
    async def business():
        """Observe business entry separately from cancellation at Hook dispatch."""
        entered.append(True)
        if phase == "error":
            raise LookupError("business failure before host interrupt")
        return "result"

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(business())
    assert entered == ([] if phase == "before" else [True])
    assert registrar.calls == [point.name]
    assert len(runtime.calls) == 1
    assert runtime.reports == []
