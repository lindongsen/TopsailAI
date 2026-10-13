"""Registration report facts across all facade branches. Author: DawsonLin."""
import asyncio
from types import SimpleNamespace
import pytest
from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar, RegistrationEnsureResult, RegistrationState
from topsailai.hooks.runtime import HookRuntime
from topsailai.hooks.hook_point_catalog import HookPointCatalog
from topsailai.tests.unit.test_topsailai_hooks.test_configured_executor import _Runtime, _Registrar, _Scope, _point


@pytest.mark.parametrize("branch", ["sync", "async_double", "async_native"])
@pytest.mark.parametrize("reason", ["deadline", "cancelled", "registration_rejected", "deadline_extra"])
def test_registration_rejection_preserves_exact_deadline_fact(monkeypatch, branch, reason):
    """Every ensure failure maps only the exact existing deadline category."""
    point = _point(mode="sync" if branch == "sync" else "async")
    result = RegistrationEnsureResult(RegistrationState.FAILED_TRANSIENT, reason)
    calls = []
    if branch == "async_native":
        runtime = object.__new__(HookRuntime)
        runtime._settings = SimpleNamespace(limits=SimpleNamespace(dispatch_timeout_ms=1000))
        runtime.make_event = _Runtime().make_event
        registrar = object.__new__(ConfiguredHookRegistrar)
    else:
        runtime, registrar = _Runtime(), _Registrar()

    def ensure(*args, **kwargs):
        """Record one ensure call without changing policy or touching files."""
        calls.append(kwargs)
        return result

    async def aensure(*args, **kwargs):
        """Return the same failure through the async-double branch."""
        return ensure(*args, **kwargs)

    monkeypatch.setattr(registrar, "ensure_registered", ensure)
    monkeypatch.setattr(registrar, "aensure_registered", aensure)
    executor = ConfiguredHookExecutor(runtime, _Scope(), registrar, HookPointCatalog((point,)))
    report = executor.dispatch(point, payload={}) if branch == "sync" else asyncio.run(executor.adispatch(point, payload={}))
    assert report.rejection_reason == reason and report.outcomes == ()
    assert report.deadline_exhausted is (reason == "deadline")
    assert len(calls) == 1
    if branch == "async_native":
        assert calls[0]["deadline"] > 0 and not calls[0]["cancellation"].is_set()


def test_native_async_registration_host_cancellation_propagates(monkeypatch):
    """Host cancellation remains control flow rather than a terminal report."""
    point = _point(mode="async")
    runtime = object.__new__(HookRuntime)
    runtime._settings = SimpleNamespace(limits=SimpleNamespace(dispatch_timeout_ms=1000))
    runtime.make_event = _Runtime().make_event
    registrar = object.__new__(ConfiguredHookRegistrar)
    signals = []

    async def cancelled(function, *args, **kwargs):
        """Inject host cancellation at the awaited registration boundary."""
        signals.append(kwargs["cancellation"])
        raise asyncio.CancelledError

    import topsailai.hooks.configured_executor as module
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(to_thread=cancelled, CancelledError=asyncio.CancelledError))
    executor = ConfiguredHookExecutor(runtime, _Scope(), registrar, HookPointCatalog((point,)))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor.adispatch(point, payload={}))
    assert len(signals) == 1 and signals[0].is_set()
