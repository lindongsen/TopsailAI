"""Behavioral tests for application-owned Hook lifecycle composition."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from topsailai.hooks.application_access import get_hook_executor
from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy, SummaryPreparationRequest
from topsailai.hooks.hook_point_catalog import HookPointCatalog
from topsailai.hooks.runtime import CloseReport
from topsailai.workspace import hooks_application as module


def _valid_types(monkeypatch):
    """Provide exact typed constructor inputs without filesystem access."""
    request = object.__new__(SummaryPreparationRequest)
    object.__setattr__(request, "configuration", SimpleNamespace(
        settings=SimpleNamespace(limits=SimpleNamespace(shutdown_timeout_ms=100)),
    ))
    object.__setattr__(request, "catalog", HookPointCatalog(()))
    object.__setattr__(request, "disabled_hook_names", frozenset())
    trust = object.__new__(ConfiguredTrustPolicy)
    object.__setattr__(trust, "source_roots", ())
    return request, trust


def _open_shell():
    """Create a manually owned shell for exercising close-stage transitions."""
    app = module.HooksApplication()
    app._close_result = module.HooksCloseResult()
    app._closed = False
    app._shutdown_ms = 100
    return app


def test_disabled_application_allocates_only_access(monkeypatch):
    """Disabled construction performs no runtime allocation or environment read."""
    monkeypatch.setattr(module, "HookRuntime", Mock(side_effect=AssertionError("runtime")))
    monkeypatch.setattr(module.os, "getenv", Mock(side_effect=AssertionError("environment")))
    app = module.HooksApplication()
    assert app.startup_report == module.HooksStartupReport(False)
    assert app.runtime is None and app.scope is None and app.registrar is None
    assert app.executor is None and app.close_result.fully_closed
    with app.bind():
        assert get_hook_executor()._binding.application is app.access


def test_partial_and_invalid_inputs_fail_before_allocation(monkeypatch, tmp_path):
    """Partial, type, catalog, and path errors precede resource construction."""
    runtime = Mock(side_effect=AssertionError("allocated"))
    monkeypatch.setattr(module, "HookRuntime", runtime)
    with pytest.raises(ValueError):
        module.HooksApplication(request=object())
    with pytest.raises(ValueError):
        module.HooksApplication(request=object(), trust_policy=object(), temp_root=str(tmp_path))
    request, trust = _valid_types(monkeypatch)
    with pytest.raises(ValueError):
        module.HooksApplication(request=request, trust_policy=trust, temp_root="relative")
    bad_request = object.__new__(SummaryPreparationRequest)
    object.__setattr__(bad_request, "catalog", object())
    with pytest.raises(ValueError):
        module.HooksApplication(request=bad_request, trust_policy=trust, temp_root=str(tmp_path))
    assert not runtime.called


def test_enabled_prepares_before_binding_and_reports_siblings(monkeypatch, tmp_path):
    """Prepared registration is eager and preserves bounded point dispositions."""
    request, trust = _valid_types(monkeypatch)
    order = []
    runtime = SimpleNamespace(
        open_scope=lambda **kwargs: order.append("scope") or object(),
        cleanup_debts=lambda: (),
        close=lambda deadline_ms: order.append("runtime") or CloseReport(),
    )
    registrar = SimpleNamespace(
        dispositions=(
            SimpleNamespace(hook_name="hook__context__before__summary_generate_user2agent", kind="registered", reason="registered"),
            SimpleNamespace(hook_name="hook__context__after__summary_apply_user2agent", kind="unavailable_preparation_failure", reason="discovery_rejected"),
        ),
        stop_admission=lambda: order.append("registrar"),
    )
    executor = object.__new__(module.ConfiguredHookExecutor)
    monkeypatch.setattr(module, "HookRuntime", lambda *a, **k: order.append("runtime-create") or runtime)
    monkeypatch.setattr(module.ConfiguredHookRegistrar, "from_prepared", lambda *a, **k: order.append("prepared") or registrar)
    monkeypatch.setattr(module, "ConfiguredHookExecutor", lambda *a, **k: order.append("executor") or executor)
    monkeypatch.setattr(module, "HookApplicationAccess", lambda value: order.append("access") or SimpleNamespace(stop_admission=lambda: order.append("access-stop")))
    app = module.HooksApplication(request=request, trust_policy=trust, temp_root=str(tmp_path))
    assert order == ["runtime-create", "scope", "prepared", "executor", "access"]
    assert app.startup_report.enabled and len(app.startup_report.dispositions) == 2


def test_nested_binding_restores_exact_outer_binding():
    """Nested bindings restore the prior ContextVar binding exactly."""
    outer, inner = module.HooksApplication(), module.HooksApplication()
    with outer.bind():
        binding = get_hook_executor()._binding
        with inner.bind():
            assert get_hook_executor()._binding.application is inner.access
        assert get_hook_executor()._binding is binding
    assert get_hook_executor()._binding is None


def test_close_order_budget_failures_debts_and_idempotence():
    """Close stops each owned stage, reports debt, and resumes later."""
    calls = []
    app = _open_shell()
    app._shutdown_ms = 100
    app.access.stop_admission = lambda: calls.append(("access",))
    app.registrar = SimpleNamespace(stop_admission=lambda: calls.append(("registrar",)))
    app.scope = SimpleNamespace(close=lambda deadline_ms: calls.append(("scope", deadline_ms)) or CloseReport())
    debts = [(SimpleNamespace(debt_id="debt-1"),)]
    app.runtime = SimpleNamespace(
        cleanup_debts=lambda: debts.pop(0) if debts else (),
        close=lambda deadline_ms: calls.append(("runtime", deadline_ms)) or CloseReport(),
    )
    first = app.close()
    assert [item[0] for item in calls] == ["access", "registrar", "scope", "runtime"]
    assert first.unresolved_debts[0].debt_id == "debt-1"
    assert not first.fully_closed
    second = app.close()
    assert second.fully_closed
    assert app.close() is second


def test_close_continues_after_stage_failure():
    """A cleanup failure does not suppress later independent cleanup stages."""
    calls = []
    app = _open_shell()
    app._shutdown_ms = 100
    app.access.stop_admission = lambda: calls.append("access")
    app.registrar = SimpleNamespace(stop_admission=lambda: calls.append("registrar"))
    app.scope = SimpleNamespace(close=lambda deadline_ms: calls.append("scope") or (_ for _ in ()).throw(RuntimeError("scope")))
    app.runtime = SimpleNamespace(cleanup_debts=lambda: (), close=lambda deadline_ms: calls.append("runtime") or CloseReport())
    result = app.close()
    assert calls == ["access", "registrar", "scope", "runtime"]
    assert result.failed_stages == ("scope",) and not result.fully_closed


def test_context_manager_restores_binding_when_business_raises():
    """Business exception identity survives close and binding restoration."""
    error = RuntimeError("business")
    app = module.HooksApplication()
    with pytest.raises(RuntimeError) as raised:
        with app:
            raise error
    assert raised.value is error
    assert get_hook_executor()._binding is None


def test_validation_and_disabled_binding_edges(monkeypatch, tmp_path):
    """Exercise invalid trust, closing state, and access-less binding paths."""
    request, trust = _valid_types(monkeypatch)
    with pytest.raises(ValueError):
        module.HooksApplication(request=request, trust_policy=object(), temp_root=str(tmp_path))
    app = module.HooksApplication()
    assert app.closing
    app.access = None
    with app.bind():
        assert app.closing


def test_close_records_registrar_and_runtime_failures():
    """Registrar and Runtime failures are reported without skipping later cleanup."""
    calls = []
    app = _open_shell()
    app._shutdown_ms = 100
    app.access.stop_admission = lambda: calls.append("access")
    app.registrar = SimpleNamespace(stop_admission=lambda: (_ for _ in ()).throw(RuntimeError("registrar")))
    app.scope = SimpleNamespace(close=lambda deadline_ms: calls.append("scope") or CloseReport())
    app.runtime = SimpleNamespace(
        cleanup_debts=lambda: (),
        close=lambda deadline_ms: calls.append("runtime") or (_ for _ in ()).throw(RuntimeError("runtime")),
    )
    result = app.close()
    assert calls == ["access", "scope", "runtime"]
    assert result.failed_stages == ("registrar", "runtime")


def test_close_propagates_interrupts_from_scope_and_runtime():
    """Host interruption remains visible and later stages are attempted when possible."""
    app = _open_shell()
    app._shutdown_ms = 100
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: (_ for _ in ()).throw(KeyboardInterrupt()))
    app.runtime = SimpleNamespace(cleanup_debts=lambda: (), close=lambda deadline_ms: CloseReport())
    with pytest.raises(KeyboardInterrupt):
        app.close()


def test_context_manager_does_not_replace_business_exception_on_cleanup_failure(monkeypatch):
    """Cleanup failures cannot replace a business exception."""
    app = module.HooksApplication()
    app.close = Mock(side_effect=RuntimeError("cleanup"))
    business = ValueError("business")
    with pytest.raises(ValueError) as raised:
        with app:
            raise business
    assert raised.value is business


def test_context_manager_propagates_cleanup_failure_without_business_error():
    """A cleanup failure is raised when no business exception is active."""
    app = module.HooksApplication()
    app.close = Mock(side_effect=RuntimeError("cleanup"))
    with pytest.raises(RuntimeError, match="cleanup"):
        with app:
            pass


def test_startup_failure_preserves_primary_exception_and_attempts_cleanup(monkeypatch, tmp_path):
    """A preparation failure remains primary while partial cleanup is attempted."""
    request, trust = _valid_types(monkeypatch)
    primary = RuntimeError("prepare")
    monkeypatch.setattr(module, "HookRuntime", Mock(side_effect=primary))
    with pytest.raises(RuntimeError) as raised:
        module.HooksApplication(request=request, trust_policy=trust, temp_root=str(tmp_path))
    assert raised.value is primary




def test_constructor_cleanup_failure_preserves_startup_exception(monkeypatch, tmp_path):
    """A cleanup failure during construction cannot replace startup failure identity."""
    request, trust = _valid_types(monkeypatch)
    startup = RuntimeError("startup")
    cleanup = RuntimeError("cleanup")
    monkeypatch.setattr(module, "HookRuntime", Mock(side_effect=startup))
    original_close = module.HooksApplication.close
    monkeypatch.setattr(module.HooksApplication, "close", Mock(side_effect=cleanup))
    with pytest.raises(RuntimeError) as raised:
        module.HooksApplication(request=request, trust_policy=trust, temp_root=str(tmp_path))
    assert raised.value is startup
    module.HooksApplication.close = original_close


def test_close_interrupts_after_interrupt_and_still_runs_later_stages():
    """The first host interrupt is retained while independent cleanup continues."""
    calls = []
    app = _open_shell()
    app._shutdown_ms = 100
    interrupt_one = KeyboardInterrupt("first")
    interrupt_two = SystemExit("second")
    app.access.stop_admission = lambda: calls.append("access")
    app.registrar = SimpleNamespace(
        stop_admission=lambda: (_ for _ in ()).throw(interrupt_one)
    )
    app.scope = SimpleNamespace(
        close=lambda deadline_ms: (_ for _ in ()).throw(interrupt_two)
    )
    app.runtime = SimpleNamespace(
        cleanup_debts=lambda: calls.append("observe"),
        close=lambda deadline_ms: calls.append("runtime") or CloseReport(),
    )
    with pytest.raises(KeyboardInterrupt) as raised:
        app.close()
    assert raised.value is interrupt_one
    assert calls == ["access", "runtime", "observe"]
    assert app.close_result.interrupted_stages == ("registrar", "scope")


def test_debt_observation_failure_retains_prior_custody_without_false_close():
    """Debt-observation failure is visible and cannot produce a false settled result."""
    app = _open_shell()
    app._shutdown_ms = 100
    debt = SimpleNamespace(debt_id="owned-debt")
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: CloseReport())
    app.runtime = SimpleNamespace(
        close=lambda deadline_ms: CloseReport(cleanup_debts=(debt,)),
        cleanup_debts=lambda: (_ for _ in ()).throw(RuntimeError("observation")),
    )
    result = app.close()
    assert not result.fully_closed
    assert result.failed_stages == ("debt_observation",)
    assert result.unresolved_debts == (debt,)
    assert result.attempted_debt_ids == ()


def test_debt_identity_observation_is_bounded():
    """Debt identity extraction accepts only exact string identities."""
    assert module.HooksApplication._debt_id(SimpleNamespace(debt_id="debt")) == "debt"
    assert module.HooksApplication._debt_id(SimpleNamespace(debt_id=1)) is None
    assert module.HooksApplication._debt_id(object()) is None
def test_direct_exit_without_enter_closes_application():
    """Direct exit remains safe when no binding context was entered."""
    app = module.HooksApplication()
    app.__exit__(None, None, None)
    assert app.close_result.fully_closed


def test_recovered_cleanup_stage_is_not_permanently_failed():
    """A one-shot stage failure is cleared after a successful close retry."""
    app = _open_shell()
    calls = {"registrar": 0}
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(
        stop_admission=lambda: (
            calls.__setitem__("registrar", calls["registrar"] + 1),
            (_ for _ in ()).throw(RuntimeError("once"))
            if calls["registrar"] == 1 else None
        )[-1]
    )
    app.scope = SimpleNamespace(close=lambda deadline_ms: CloseReport())
    app.runtime = SimpleNamespace(cleanup_debts=lambda: (), close=lambda deadline_ms: CloseReport())
    first = app.close()
    assert first.failed_stages == ("registrar",)
    second = app.close()
    assert second.fully_closed and second.failed_stages == ()


def test_cancelled_cleanup_is_rethrown_after_later_stages():
    """Host cancellation keeps identity while independent cleanup still runs."""
    app = _open_shell()
    calls = []
    cancellation = __import__("asyncio").CancelledError("cancel")
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: (_ for _ in ()).throw(cancellation))
    app.runtime = SimpleNamespace(
        close=lambda deadline_ms: calls.append("runtime") or CloseReport(),
        cleanup_debts=lambda: calls.append("observe") or (),
    )
    with pytest.raises(__import__("asyncio").CancelledError) as raised:
        app.close()
    assert raised.value is cancellation
    assert calls == ["runtime", "observe"]
    assert app.close_result.interrupted_stages == ("scope",)


def test_report_carried_debt_is_retained_when_observation_fails():
    """A close report remains custody evidence when observation is unavailable."""
    app = _open_shell()
    debt = SimpleNamespace(debt_id="report-debt")
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: CloseReport(cleanup_debts=(debt,)))
    app.runtime = SimpleNamespace(
        close=lambda deadline_ms: CloseReport(),
        cleanup_debts=lambda: (_ for _ in ()).throw(RuntimeError("observe")),
    )
    result = app.close()
    assert result.unresolved_debts == (debt,)
    assert result.attempted_debt_ids == ()


def test_business_exception_wins_over_cancelled_cleanup():
    """An active business exception takes precedence over host cancellation."""
    app = module.HooksApplication()
    cancellation = __import__("asyncio").CancelledError("cancel")
    app.close = Mock(side_effect=cancellation)
    business = ValueError("business")
    with pytest.raises(ValueError) as raised:
        with app:
            raise business
    assert raised.value is business


def test_close_deduplicates_repeated_stage_diagnostics():
    """Repeated failures and interruptions remain bounded to one stage token."""
    app = _open_shell()
    app._close_result = module.HooksCloseResult(
        failed_stages=("scope", "scope"), interrupted_stages=("scope", "scope")
    )
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: (_ for _ in ()).throw(RuntimeError("scope")))
    app.runtime = SimpleNamespace(close=lambda deadline_ms: CloseReport(), cleanup_debts=lambda: ())
    result = app.close()
    assert result.failed_stages == ("scope",)
    assert result.interrupted_stages == ("scope",)


def test_close_observation_failure_without_existing_debt_keeps_empty_inventory():
    """An observation failure with no custody evidence does not invent debt."""
    app = _open_shell()
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: CloseReport())
    app.runtime = SimpleNamespace(
        close=lambda deadline_ms: CloseReport(),
        cleanup_debts=lambda: (_ for _ in ()).throw(RuntimeError("observe")),
    )
    result = app.close()
    assert result.unresolved_debts == ()
    assert result.failed_stages == ("debt_observation",)


@pytest.mark.parametrize("stage", ["access", "registrar", "scope", "runtime", "debt_observation"])
def test_one_shot_recovery_matrix_preserves_settled_stages_and_history(stage):
    """Each close stage recovers once without repeating settled work or losing history."""
    app = _open_shell()
    calls = {name: 0 for name in ("access", "registrar", "scope", "runtime", "debt_observation")}
    debt = SimpleNamespace(debt_id="matrix-debt")
    for name in calls:
        calls[name] = 0

    def access():
        calls["access"] += 1
        if stage == "access" and calls["access"] == 1:
            raise RuntimeError("access once")

    def registrar():
        calls["registrar"] += 1
        if stage == "registrar" and calls["registrar"] == 1:
            raise RuntimeError("registrar once")

    def scope(deadline_ms):
        calls["scope"] += 1
        if stage == "scope" and calls["scope"] == 1:
            raise RuntimeError("scope once")
        return CloseReport()

    def runtime(deadline_ms):
        calls["runtime"] += 1
        if stage == "runtime" and calls["runtime"] == 1:
            raise RuntimeError("runtime once")
        return CloseReport(cleanup_debts=(debt,) if stage == "debt_observation" else ())

    def observe():
        calls["debt_observation"] += 1
        if stage == "debt_observation" and calls["debt_observation"] == 1:
            raise RuntimeError("observation once")
        return ()

    app.access.stop_admission = access
    app.registrar = SimpleNamespace(stop_admission=registrar)
    app.scope = SimpleNamespace(close=scope)
    app.runtime = SimpleNamespace(close=runtime, cleanup_debts=observe)
    first = app.close()
    assert not first.fully_closed
    assert stage in first.failed_stages
    assert stage in first.historical_failed_stages
    second = app.close()
    assert second.fully_closed
    assert second.failed_stages == ()
    assert stage in second.historical_failed_stages
    third = app.close()
    assert third is second
    assert calls["access"] == (2 if stage == "access" else 1)
    assert calls["registrar"] == (2 if stage == "registrar" else 1)
    assert calls["scope"] == (2 if stage == "scope" else 1)
    assert calls["runtime"] == (2 if stage == "runtime" else 1)
    expected_observation_calls = 2 if stage in {"runtime", "debt_observation"} else 1
    assert calls["debt_observation"] == expected_observation_calls

def test_report_debt_identity_is_replaced_by_authoritative_observation():
    """Report debt custody is retained, then replaced by authoritative debt identity."""
    app = _open_shell()
    report_debt = SimpleNamespace(debt_id="report-debt")
    observed_debt = SimpleNamespace(debt_id="observed-debt")
    observations = [RuntimeError("temporary"), (observed_debt,), ()]
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: CloseReport(cleanup_debts=(report_debt,)))
    app.runtime = SimpleNamespace(
        close=lambda deadline_ms: CloseReport(cleanup_debts=(report_debt,)),
        cleanup_debts=lambda: (_ for _ in ()).throw(observations.pop(0))
        if isinstance(observations[0], BaseException)
        else observations.pop(0),
    )
    first = app.close()
    assert first.unresolved_debts == (report_debt,)
    assert first.unresolved_debts[0] is report_debt
    assert first.attempted_debt_ids == ()
    second = app.close()
    assert not second.fully_closed
    assert second.unresolved_debts == (observed_debt,)
    assert second.unresolved_debts[0] is observed_debt
    third = app.close()
    assert third.fully_closed
    assert third.unresolved_debts == ()
    assert app.close() is third


def test_failed_debt_observation_never_caches_completion_or_fabricates_ids():
    """Failed observation stays retryable and exposes no synthetic debt identity."""
    app = _open_shell()
    app.access.stop_admission = lambda: None
    app.registrar = SimpleNamespace(stop_admission=lambda: None)
    app.scope = SimpleNamespace(close=lambda deadline_ms: CloseReport())
    app.runtime = SimpleNamespace(
        close=lambda deadline_ms: CloseReport(),
        cleanup_debts=lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    first = app.close()
    assert not first.fully_closed
    assert first.unresolved_debts == ()
    assert first.attempted_debt_ids == ()
    assert first.debt_observation_succeeded is False
    assert app.close() is not first
