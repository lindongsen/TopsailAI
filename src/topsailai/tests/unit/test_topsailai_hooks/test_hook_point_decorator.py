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
