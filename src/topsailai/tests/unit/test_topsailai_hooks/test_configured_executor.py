"""Tests for the configured Hook execution facade."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from topsailai.hooks.configured_executor import (
    ConfiguredHookExecutor,
    HookOperation,
    HookPointBlockedError,
)
from topsailai.hooks.configured_registration import (
    RegistrationEnsureResult,
    RegistrationState,
)
from topsailai.hooks.contracts import (
    DeliveryReceipt,
    DispatchReport,
    EventDefinition,
    HookOutcome,
    HookStatus,
)
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration


@dataclass
class _Scope:
    """Provide one application Scope identity."""

    scope_id: str = "scope"


class _Registrar:
    """Return controlled registration states without filesystem work."""

    def __init__(self, state: RegistrationState = RegistrationState.READY) -> None:
        self.state_value = state
        self.sync_calls = 0
        self.async_calls = 0

    def ensure_registered(self, name: str) -> RegistrationEnsureResult:
        """Record one synchronous registration request."""
        del name
        self.sync_calls += 1
        error = "registration_rejected" if self.state_value.name.startswith("FAILED") else None
        return RegistrationEnsureResult(self.state_value, error)

    async def aensure_registered(self, name: str) -> RegistrationEnsureResult:
        """Record one asynchronous registration request."""
        del name
        self.async_calls += 1
        return RegistrationEnsureResult(self.state_value)


class _Runtime:
    """Record low-level configured Runtime calls."""

    def __init__(self) -> None:
        self.events = []

    def make_event(self, scope, name, version, payload, **metadata):
        """Create a stable immutable test event."""
        from topsailai.hooks.contracts import HookEvent

        event = HookEvent(
            str(len(self.events) + 1),
            name,
            version,
            "owner",
            scope.scope_id,
            metadata["operation_id"],
            metadata.get("parent_operation_id"),
            len(self.events) + 1,
            "now",
            metadata["layer"],
            metadata["purpose"],
            payload,
        )
        self.events.append(event)
        return event

    def dispatch_configured(self, name, event):
        """Return one successful synchronous report."""
        del name
        return DispatchReport(event.event_id, 1)

    async def adispatch_configured(self, name, event):
        """Return one successful asynchronous report."""
        del name
        return DispatchReport(event.event_id, 1)

    def emit_configured(self, name, event):
        """Return one admitted background Receipt."""
        del name
        return DeliveryReceipt(True, event.event_id)


def _point(
    name: str = "hook_test_before",
    mode: str = "sync",
    policy: str = "report",
) -> HookPointDeclaration:
    """Build one declaration with a unique event identity."""
    return HookPointDeclaration(
        name,
        EventDefinition(f"test.{name}", 1, {"type": "object"}),
        "before",
        mode,
        "tests",
        failure_policy=policy,
        security_critical=policy == "block",
    )


def test_sync_dispatch_constructs_catalog_event_and_uses_registrar() -> None:
    """Sync execution must validate, ensure, construct, and delegate once."""
    point = _point()
    runtime = _Runtime()
    registrar = _Registrar()
    executor = ConfiguredHookExecutor(
        runtime, _Scope(), registrar, HookPointCatalog((point,))
    )

    report = executor.dispatch(
        point,
        payload={},
        operation=HookOperation("op", "parent", 2),
    )

    assert report.rejection_reason is None
    assert registrar.sync_calls == 1
    assert runtime.events[0].operation_id == "op"
    assert runtime.events[0].parent_operation_id == "parent"


def test_async_dispatch_and_background_admission_use_async_registration() -> None:
    """Async execution and lazy-safe admission must share async ensure."""
    async_point = _point("hook_test_async", "async")
    background = _point("hook_test_background", "background")
    runtime = _Runtime()
    registrar = _Registrar()
    executor = ConfiguredHookExecutor(
        runtime,
        _Scope(),
        registrar,
        HookPointCatalog((async_point, background)),
    )

    async def run():
        report = await executor.adispatch(async_point, payload={})
        receipt = await executor.aemit(background, payload={})
        return report, receipt

    report, receipt = asyncio.run(run())

    assert report.rejection_reason is None
    assert receipt.admitted
    assert registrar.async_calls == 2


def test_unconfigured_report_is_stable_noop_and_block_raises() -> None:
    """Report preserves flow while an authorized block stops the caller."""
    ordinary = _point()
    blocked = _point("hook_test_block", policy="block")
    runtime = _Runtime()
    registrar = _Registrar(RegistrationState.UNCONFIGURED)
    executor = ConfiguredHookExecutor(
        runtime,
        _Scope(),
        registrar,
        HookPointCatalog((ordinary, blocked)),
    )

    assert executor.dispatch(ordinary, payload={}).rejection_reason == "unconfigured"
    with pytest.raises(HookPointBlockedError) as caught:
        executor.dispatch(blocked, payload={})
    assert caught.value.point_name == blocked.name


def test_block_raises_for_failed_hook_outcome_and_modes_are_exact() -> None:
    """A failed blocking outcome raises while execution modes remain explicit."""
    point = _point(policy="block")
    runtime = _Runtime()
    registrar = _Registrar()
    runtime.dispatch_configured = lambda name, event: DispatchReport(
        event.event_id,
        1,
        (HookOutcome("delivery", "binding", HookStatus.ERROR),),
    )
    executor = ConfiguredHookExecutor(
        runtime, _Scope(), registrar, HookPointCatalog((point,))
    )

    with pytest.raises(HookPointBlockedError):
        executor.dispatch(point, payload={})
    with pytest.raises(ValueError, match="execution mode"):
        asyncio.run(executor.adispatch(point, payload={}))


def test_executor_rejects_invalid_dependencies_points_and_operations() -> None:
    """Facade construction and catalog ownership must fail before dispatch."""
    point = _point()
    catalog = HookPointCatalog((point,))
    runtime = _Runtime()
    registrar = _Registrar()

    with pytest.raises(ValueError, match="invalid configured Hook Executor"):
        ConfiguredHookExecutor(object(), _Scope(), registrar, catalog)

    executor = ConfiguredHookExecutor(runtime, _Scope(), registrar, catalog)
    with pytest.raises(ValueError, match="invalid Hook-point declaration"):
        executor.dispatch(object(), payload={})
    foreign = _point(point.name, policy="block")
    with pytest.raises(ValueError, match="not catalog-owned"):
        executor.dispatch(foreign, payload={})
    with pytest.raises(ValueError, match="invalid Hook operation"):
        executor.dispatch(point, payload={}, operation=object())
    with pytest.raises(ValueError, match="invalid Hook operation"):
        HookOperation("", depth=-1)


def test_async_rejection_and_background_block_are_enforced() -> None:
    """Async and background points must preserve typed registration rejection."""
    async_point = _point("hook_test_async_rejected", "async")
    background = _point("hook_test_background_block", "background", "block")
    runtime = _Runtime()
    registrar = _Registrar(RegistrationState.UNCONFIGURED)
    executor = ConfiguredHookExecutor(
        runtime,
        _Scope(),
        registrar,
        HookPointCatalog((async_point, background)),
    )

    async def run() -> None:
        report = await executor.adispatch(async_point, payload={})
        assert report.rejection_reason == "unconfigured"
        with pytest.raises(HookPointBlockedError):
            await executor.aemit(background, payload={})

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["success", "unavailable", "cancel"])
def test_real_async_facade_shared_budget(tmp_path, monkeypatch, mode):
    """Registration and execution share a signal and deadline with local cancellation."""
    import threading
    import time
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import _runtime
    from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
    from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy
    from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
    runtime, scope = _runtime(tmp_path)
    point = _point(mode="async")
    catalog = HookPointCatalog((point,))
    folder = tmp_path / "sources"
    folder.mkdir()
    bootstrap = ConfiguredHookBootstrap(True, registration_mode="lazy", hooks=(
        ConfiguredHookBinding(point.name, folder=folder),), trust=ConfiguredTrustPolicy((tmp_path,)),
        trust_identity="a" * 64)
    registrar = ConfiguredHookRegistrar(runtime, scope, bootstrap, catalog)
    seen = []
    started = threading.Event()
    stopped = threading.Event()
    original = registrar.ensure_registered

    def ensure(name, **kwargs):
        """Observe async preparation off the loop and its caller-local stop signal."""
        seen.append(kwargs)
        started.set()
        try:
            if mode == "cancel":
                assert kwargs["cancellation"].wait(1)
                return RegistrationEnsureResult(RegistrationState.REGISTERING, "cancelled")
            if mode == "unavailable":
                return RegistrationEnsureResult(RegistrationState.FAILED_DETERMINISTIC, "registration_rejected")
            return original(name, **kwargs)
        finally:
            stopped.set()

    monkeypatch.setattr(registrar, "ensure_registered", ensure)
    original_submit = runtime._scheduler.submit
    def submit(*args, **kwargs):
        """Require the unchanged preparation deadline at execution admission."""
        assert kwargs["deadline_seconds"] == seen[0]["deadline"]
        return original_submit(*args, **kwargs)
    monkeypatch.setattr(runtime._scheduler, "submit", submit)

    async def exercise():
        """Keep host progress observable while registration runs elsewhere."""
        facade = ConfiguredHookExecutor(runtime, scope, registrar, catalog)
        task = asyncio.create_task(facade.adispatch(point, payload={}))
        assert await asyncio.to_thread(started.wait, 1)
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await asyncio.to_thread(stopped.wait, 1)
            assert seen[0]["cancellation"].is_set()
        else:
            report = await task
            if mode == "success":
                assert report.unified_result.status == "success"
            else:
                assert report.rejection_reason == "registration_rejected"
        assert seen[0]["deadline"] <= time.monotonic() + 2
    try:
        asyncio.run(exercise())
    finally:
        registrar.close()
        runtime.close()
