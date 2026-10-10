"""BDD steps for configured registration and callable Hook points."""

from __future__ import annotations

import traceback
from pathlib import Path

import pytest
from pytest_bdd import given, then, when

from topsailai.hooks import (
    ConfiguredHookBinding,
    ConfiguredHookBootstrap,
    ConfiguredHookRegistrar,
    ConfiguredRegistrationResult,
    ConfiguredTrustPolicy,
    EventDefinition,
    HookPointCatalog,
    HookPointDeclaration,
    RegistrationState,
    hook_point,
)


class _Scope:
    """Minimal application Scope used at the BDD registration boundary."""

    scope_id = "bdd-application-scope"

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        """Record lifecycle closure."""
        self.closed = True


class _RegistrationRuntime:
    """Observe calls made through the unchanged registration boundary."""

    def __init__(self) -> None:
        self.calls = 0

    def register_configured(self, hook_name, scope, *, scripts=None, folder=None):
        """Accept one configured registration and count it."""
        self.calls += 1
        return ConfiguredRegistrationResult(True, changed=True)

    def retire_configured(self, hook_name, scope):
        """Accept retirement for lifecycle completeness."""
        return True


class _DecoratorExecutor:
    """Observe decorator dispatch without duplicating Executor policy logic."""

    def __init__(self) -> None:
        self.points: list[str] = []

    def dispatch(self, point, *, payload, operation=None):
        """Record one synchronous declaration."""
        self.points.append(point.phase)
        return object()

    async def adispatch(self, point, *, payload, operation=None):
        """Record one asynchronous declaration."""
        self.points.append(point.phase)
        return object()


def _point(name: str, phase: str) -> HookPointDeclaration:
    """Create one distinct synchronous declaration."""
    return HookPointDeclaration(
        name,
        EventDefinition(f"bdd.{phase}", 1, {"type": "object"}),
        phase,
        "sync",
        "tests.bdd",
    )


def _registrar(mode: str):
    """Build one configured Registrar using immutable public contracts."""
    point = _point("hook_bdd_registration", "before")
    catalog = HookPointCatalog((point,))
    trust = ConfiguredTrustPolicy(source_roots=(Path("/bdd"),))
    bootstrap = ConfiguredHookBootstrap(
        True,
        registration_mode=mode,
        hooks=(ConfiguredHookBinding(point.name, scripts=(Path("/bdd/hook.py"),)),),
        trust=trust,
        trust_identity="a" * 64,
    )
    runtime = _RegistrationRuntime()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), bootstrap, catalog)
    return registrar, runtime, point


@pytest.fixture
def hook_readiness_ctx():
    """Hold one BDD scenario's observations."""
    return {}


@given("a startup configured Hook Registrar")
def given_startup_registrar(hook_readiness_ctx):
    """Create a startup-mode Registrar."""
    registrar, runtime, point = _registrar("startup")
    hook_readiness_ctx.update(registrar=registrar, runtime=runtime, point=point)


@given("a lazy configured Hook Registrar")
def given_lazy_registrar(hook_readiness_ctx):
    """Create a lazy-mode Registrar."""
    registrar, runtime, point = _registrar("lazy")
    hook_readiness_ctx.update(registrar=registrar, runtime=runtime, point=point)


@when("the application starts configured Hooks")
def when_start(hook_readiness_ctx):
    """Run eager application startup registration."""
    hook_readiness_ctx["results"] = [hook_readiness_ctx["registrar"].start()]


@when("the configured Hook is ensured twice")
def when_ensure_twice(hook_readiness_ctx):
    """Exercise lazy registration and its stable ready path."""
    registrar = hook_readiness_ctx["registrar"]
    name = hook_readiness_ctx["point"].name
    hook_readiness_ctx["results"] = [
        registrar.ensure_registered(name),
        registrar.ensure_registered(name),
    ]


@then("the configured Hook is registered exactly once and ready")
def then_registered_once(hook_readiness_ctx):
    """Verify single publication and stable readiness."""
    assert hook_readiness_ctx["runtime"].calls == 1
    assert all(result.state is RegistrationState.READY for result in hook_readiness_ctx["results"])


@given("a callable decorated with distinct before success and error Hook points")
def given_decorated_callable(hook_readiness_ctx):
    """Create one callable whose three phases are independent declarations."""
    executor = _DecoratorExecutor()
    result = object()
    business_error = RuntimeError("business failure")
    before = _point("hook_bdd_before", "before")
    success = _point("hook_bdd_success", "success")
    error = _point("hook_bdd_error", "error")

    @hook_point(
        before=before,
        success=success,
        error=error,
        executor_provider=lambda: executor,
    )
    def operation(fail: bool):
        """Return one object or raise one stable business exception."""
        if fail:
            raise business_error
        return result

    hook_readiness_ctx.update(
        executor=executor,
        operation=operation,
        expected_result=result,
        business_error=business_error,
    )


@when("the decorated callable returns normally")
def when_callable_returns(hook_readiness_ctx):
    """Execute the normal callable path."""
    hook_readiness_ctx["actual_result"] = hook_readiness_ctx["operation"](False)


@when("the decorated callable raises its business exception")
def when_callable_raises(hook_readiness_ctx):
    """Capture exception identity and traceback from the error path."""
    try:
        hook_readiness_ctx["operation"](True)
    except RuntimeError as error:
        hook_readiness_ctx["actual_error"] = error
        hook_readiness_ctx["traceback_names"] = [frame.name for frame in traceback.extract_tb(error.__traceback__)]


@then("before and success run once and error does not run")
def then_success_cardinality(hook_readiness_ctx):
    """Verify normal-path cardinality."""
    assert hook_readiness_ctx["executor"].points == ["before", "success"]


@then("the exact business result object is returned")
def then_result_identity(hook_readiness_ctx):
    """Verify ordinary result identity is unchanged."""
    assert hook_readiness_ctx["actual_result"] is hook_readiness_ctx["expected_result"]


@then("before and error run once and success does not run")
def then_error_cardinality(hook_readiness_ctx):
    """Verify error-path cardinality."""
    assert hook_readiness_ctx["executor"].points == ["before", "error"]


@then("the exact business exception and traceback are preserved")
def then_error_identity(hook_readiness_ctx):
    """Verify bare-raise behavior preserves identity and the business frame."""
    assert hook_readiness_ctx["actual_error"] is hook_readiness_ctx["business_error"]
    assert "operation" in hook_readiness_ctx["traceback_names"]
