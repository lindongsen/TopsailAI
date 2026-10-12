"""Application summary owner and passive injection regressions. Author: DawsonLin."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, ConfiguredTrustPolicy, HookSettings
from topsailai.hooks.configured_contracts import SummaryPreparationRequest
from topsailai.hooks.points.catalog import SUMMARY_CATALOG, PHASE_ONE_DECLARATIONS
from topsailai.hooks.process_state import CleanupDebt
from topsailai.hooks.runtime import CloseReport
from topsailai.workspace import summary_hooks_owner as module
from topsailai.tests.unit.test_topsailai_hooks.test_configured_preparation import secure_test_root, _runtime, _assertion


@pytest.fixture
def inputs(tmp_path):
    """Provide explicit detached deployment inputs with no enabled point I/O."""
    return dict(request=SummaryPreparationRequest(ConfiguredHooks((), HookSettings()), SUMMARY_CATALOG),
        trust_policy=ConfiguredTrustPolicy((tmp_path,)), temp_root=str(tmp_path))


@pytest.fixture(autouse=True)
def isolated_factory(monkeypatch):
    """Isolate only the factory reference and close exactly the test-owned owner."""
    monkeypatch.setattr(module, "_owner", None)
    yield
    if module._owner is not None:
        module._owner.close()


def test_singleflight_equivalent_and_conflicting_acquisition(inputs):
    """Concurrent equivalent callers share one owner; conflicts never replace it."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        owners = list(pool.map(lambda _: module.acquire_summary_hooks_owner(**inputs), range(16)))
    owner = owners[0]
    assert all(item is owner for item in owners)
    assert owner.startup_report.ready and owner.startup_report.dispositions == ()
    for change in ({"temp_root": inputs["temp_root"] + "/different"},
            {"trust_policy": ConfiguredTrustPolicy((Path(inputs["temp_root"]) / "different",))},
            {"request": replace(inputs["request"], disabled_hook_names=frozenset({PHASE_ONE_DECLARATIONS[0].name}))}):
        with pytest.raises(RuntimeError, match="conflicting"):
            module.acquire_summary_hooks_owner(**(inputs | change))
        assert module._owner is owner and not owner.closing
    result = owner.close()
    assert result.fully_closed
    assert owner.close() is result
    with pytest.raises(RuntimeError, match="closing"):
        module.acquire_summary_hooks_owner(**inputs)


@pytest.mark.parametrize("change", [{"request": {}}, {"trust_policy": {}}, {"temp_root": "relative"},
    {"temp_root": None}])
def test_invalid_inputs_precede_allocation(inputs, change, monkeypatch):
    """Reject malformed authority without creating Runtime or publishing a cache."""
    runtime = Mock(side_effect=AssertionError("allocation"))
    monkeypatch.setattr(module, "HookRuntime", runtime)
    with pytest.raises(ValueError):
        module.acquire_summary_hooks_owner(**(inputs | change))
    runtime.assert_not_called()
    assert module._owner is None


def test_failed_initialization_never_cached_and_forwards_authority(inputs, monkeypatch):
    """Failed startup settles its own Runtime and permits a later first acquisition."""
    original = module.HookRuntime
    runtime = original(inputs["request"].configuration.settings,
        temp_root=inputs["temp_root"], configured_trust=inputs["trust_policy"])
    spy = Mock(return_value=runtime)
    monkeypatch.setattr(module, "HookRuntime", spy)
    original_prepared = module.ConfiguredHookRegistrar.from_prepared
    primary = RuntimeError("secret /private/source")
    monkeypatch.setattr(module.ConfiguredHookRegistrar, "from_prepared", Mock(side_effect=primary))
    with pytest.raises(RuntimeError) as raised:
        module.acquire_summary_hooks_owner(**inputs)
    assert raised.value is primary and primary.summary_hooks_owner.close_result.fully_closed
    assert module._owner is None
    spy.assert_called_once_with(inputs["request"].configuration.settings,
        temp_root=inputs["temp_root"], configured_trust=inputs["trust_policy"])
    monkeypatch.setattr(module, "HookRuntime", original)
    monkeypatch.setattr(module.ConfiguredHookRegistrar, "from_prepared", original_prepared)
    assert module.acquire_summary_hooks_owner(**inputs).startup_report.ready


@pytest.mark.parametrize("policy", ["fail", "disable"])
def test_real_prepared_dispositions_safe_sibling_isolation(secure_test_root, monkeypatch, caplog, policy):
    """Real U4 capture registers siblings; policy disablement does no point I/O."""
    sources, root, _ = secure_test_root
    valid = sources / "valid"
    broken = sources / "broken"
    valid.mkdir(mode=0o700)
    broken.mkdir(mode=0o700)
    good = valid / "good.py"
    bad = broken / "bad.py"
    good.write_text("def main(context):\n    return None\n")
    bad.write_text("secret = '/private/token'\n")
    seed, _ = _runtime(sources, root)
    trust = replace(seed.configured_trust, closure_assertions=(_assertion(good, "good"), _assertion(bad, "bad")))
    seed.close()
    points = PHASE_ONE_DECLARATIONS[:3]
    folders = (sources / "absent-secret", broken, valid)
    config = ConfiguredHooks(tuple(ConfiguredHookPoint(p.name, p.definition, module_folder=f)
        for p, f in zip(points, folders)), HookSettings())
    request = SummaryPreparationRequest(config, SUMMARY_CATALOG, frozenset({points[0].name}))
    monkeypatch.setenv("TOPSAILAI_CONFIGURED_HOOKS_STARTUP_POLICY", policy)
    monkeypatch.setattr("topsailai.hooks.configured_bootstrap.load_configured_hook_bootstrap",
        Mock(side_effect=AssertionError("bootstrap")))
    owner = module.acquire_summary_hooks_owner(request=request, trust_policy=trust, temp_root=str(root))
    outcomes = owner.startup_report.dispositions
    assert [item.kind for item in outcomes] == ["disabled_by_configuration", "unavailable_preparation_failure", "registered"]
    assert owner.registrar.ensure_registered(points[2].name).ready
    with pytest.raises(FrozenInstanceError):
        owner.startup_report.ready = False
    output = repr(owner.startup_report) + caplog.text
    for unsafe in (str(sources), "/private/token", "Traceback", "absent-secret"):
        assert unsafe not in output
    assert owner.startup_report.metrics == tuple((i.hook_name, i.kind, i.reason, 1) for i in outcomes)


@pytest.mark.parametrize("mask", range(1, 7))
def test_factory_partial_inputs_fail_before_allocation(inputs, monkeypatch, mask):
    """All six partial combinations fail before constructing any context/resource."""
    from topsailai.workspace import agent_shell
    args = dict(summary_preparation_request=inputs["request"] if mask & 1 else None,
        summary_trust_policy=inputs["trust_policy"] if mask & 2 else None,
        summary_hooks_temp_root=inputs["temp_root"] if mask & 4 else None)
    constructor = Mock(side_effect=AssertionError("context allocation"))
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", constructor)
    with pytest.raises(ValueError):
        agent_shell._get_agent_chat_impl(**args)
    constructor.assert_not_called()
    assert module._owner is None


def test_factory_unconfigured_then_configured_passive_injection(inputs, monkeypatch):
    """The real factory injects no executor before configuration and an exact shared one later."""
    from topsailai.workspace import agent_shell
    from topsailai.workspace.context.ctx_runtime import ContextRuntimeData
    class Boundary(Exception):
        """Stop factory construction immediately after inspecting its context seam."""
    contexts = []
    def context(**kwargs):
        """Inspect eager acquisition then avoid unrelated session startup effects."""
        contexts.append(ContextRuntimeData(**kwargs))
        raise Boundary()
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", context)
    with pytest.raises(Boundary):
        agent_shell._get_agent_chat_impl(system_prompt="explicit", agent_name="test")
    assert contexts[0].summary_hooks_executor is None and module._owner is None
    args = dict(summary_preparation_request=inputs["request"], summary_trust_policy=inputs["trust_policy"],
        summary_hooks_temp_root=inputs["temp_root"])
    for _ in range(2):
        with pytest.raises(Boundary):
            agent_shell._get_agent_chat_impl(system_prompt="explicit", agent_name="test", **args)
    assert contexts[1].summary_hooks_executor is contexts[2].summary_hooks_executor is module._owner.executor
    executor = Mock(side_effect=AssertionError("dispatch"))
    assert ContextRuntimeData(summary_hooks_executor=executor).summary_hooks_executor is executor
    executor.assert_not_called()


def test_public_factory_forwards_explicit_values(inputs, monkeypatch):
    """Public factory forwards unchanged typed dependencies without configuration decoding."""
    from topsailai.workspace import agent_shell
    impl = Mock(return_value=object())
    monkeypatch.setattr(agent_shell, "_get_agent_chat_impl", impl)
    kwargs = dict(summary_preparation_request=inputs["request"], summary_trust_policy=inputs["trust_policy"],
        summary_hooks_temp_root=inputs["temp_root"], need_project_workspace_lock=False)
    assert agent_shell.get_agent_chat(**kwargs) is impl.return_value
    for key, value in kwargs.items():
        assert impl.call_args.kwargs[key] is value


def _close_double(inputs, monkeypatch, *, resolve=False):
    """Substitute lifecycle endpoints after genuine owner composition for exact ordering."""
    owner = module.acquire_summary_hooks_owner(**inputs)
    owner.scope.close()
    owner.runtime.close()
    order = []
    debt = CleanupDebt("exact-debt", "cleanup_pending", None, "pending")
    debts = [debt]
    def retry(debt_id):
        """Record exactly known recovery and optionally settle it."""
        assert debt_id == debt.debt_id
        order.append("retry")
        if resolve:
            debts.clear()
        return resolve
    owner.registrar = SimpleNamespace(stop_admission=lambda: order.append("registrar"))
    owner.scope = SimpleNamespace(close=lambda **k: (order.append("scope") or CloseReport(("scope",))))
    owner.runtime = SimpleNamespace(close=lambda **k: (order.append("runtime") or CloseReport(cleanup_debts=(debt,))),
        cleanup_debts=lambda: tuple(debts), retry_cleanup=retry)
    return owner, order


@pytest.mark.parametrize("resolve", [True, False])
def test_ordered_close_exact_bounded_debt_and_honest_result(inputs, monkeypatch, resolve):
    """Only exact known debts are retried twice; unresolved debt forbids full closure."""
    owner, order = _close_double(inputs, monkeypatch, resolve=resolve)
    result = owner.close()
    assert order[:3] == ["registrar", "scope", "runtime"]
    assert order.count("retry") == (1 if resolve else 2)
    assert result.fully_closed is resolve
    assert result.runtime_report.cleanup_debts and result.scope_report.closed_scope_ids == ("scope",)
    assert bool(result.unresolved_debts) is not resolve
    assert owner.close() is result


@pytest.mark.parametrize("stage", ["registrar", "scope", "runtime", "retry"])
@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_host_interrupt_retains_custody_and_propagates(inputs, monkeypatch, stage, kind):
    """Host interruption identity survives every close/recovery boundary and allows resumption."""
    owner, order = _close_double(inputs, monkeypatch, resolve=True)
    target, attr = {"registrar": (owner.registrar, "stop_admission"), "scope": (owner.scope, "close"),
        "runtime": (owner.runtime, "close"), "retry": (owner.runtime, "retry_cleanup")}[stage]
    original = getattr(target, attr)
    primary = kind()
    def once(*a, **k):
        """Interrupt exactly once while leaving reconciliation reachable."""
        setattr(target, attr, original)
        raise primary
    setattr(target, attr, once)
    with pytest.raises(kind) as raised:
        owner.close()
    assert raised.value is primary and owner.closing and not owner.close_result.fully_closed
    assert owner.close_result.unresolved_debts
    assert owner.close().fully_closed


def test_ordinary_close_failure_is_reported_and_later_stages_run(inputs, monkeypatch, caplog):
    """Safe failure tokens remain visible; unsafe raw failure text is not exported."""
    owner, order = _close_double(inputs, monkeypatch, resolve=True)
    owner.scope.close = Mock(side_effect=ValueError("secret /private"))
    result = owner.close()
    assert result.failed_stages == ("scope",) and not result.fully_closed
    assert "runtime" in order and "secret" not in caplog.text


def test_session_run_finalizer_leaves_shared_owner_available(inputs, monkeypatch):
    """Execute the existing real session finalizer without transferring shared custody."""
    from topsailai.workspace.agent import agent_shell_base
    owner = module.acquire_summary_hooks_owner(**inputs)
    run = agent_shell_base.AgentChat.run
    # The existing tee decorator does not use functools.wraps; retrieve its body.
    body = next(cell.cell_contents for cell in run.__closure__ if callable(cell.cell_contents))
    session = SimpleNamespace(_run=Mock(return_value="done"),
        ctx_runtime_data=SimpleNamespace(session_id=""), _stop_control_server=Mock(),
        ai_agent=SimpleNamespace(close=Mock()), summary_hooks_executor=owner.executor)
    monkeypatch.setattr(agent_shell_base, "update_session_meta_status", Mock())
    assert body(session) == "done"
    session.ai_agent.close.assert_called_once()
    assert not owner.closing and not owner.scope.closed
    assert module.acquire_summary_hooks_owner(**inputs).executor is owner.executor
    point = PHASE_ONE_DECLARATIONS[0]
    assert not owner.registrar.ensure_registered(point.name).ready
    assert owner.close().fully_closed


def test_expired_shutdown_budget_admits_no_retry(inputs, monkeypatch):
    """An expired owner budget must not authorize even the first debt retry."""
    owner, order = _close_double(inputs, monkeypatch)
    class Clock:
        """Expose one injected monotonic deadline without changing the shared time module."""
        calls = 0
        @classmethod
        def monotonic(cls):
            """Advance beyond the owner budget before recovery admission."""
            cls.calls += 1
            return 0 if cls.calls == 1 else 100
    monkeypatch.setattr(module, "time", Clock)
    result = owner.close()
    assert "retry" not in order and not result.fully_closed


def test_retry_ordinary_failure_is_safe_and_bounded(inputs, monkeypatch, caplog):
    """Recovery failures keep exact debt visible and never export unsafe exception text."""
    owner, order = _close_double(inputs, monkeypatch)
    owner.runtime.retry_cleanup = Mock(side_effect=ValueError("secret/private"))
    result = owner.close()
    assert owner.runtime.retry_cleanup.call_count == 2
    assert not result.fully_closed and result.unresolved_debts
    assert "cleanup" in result.failed_stages and "secret/private" not in caplog.text


def test_phase_two_catalog_rejected_before_allocation(inputs, monkeypatch):
    """Owner composition cannot accidentally activate phase-two declarations."""
    from topsailai.hooks.hook_point_catalog import HookPointCatalog
    from topsailai.hooks.points.catalog import PHASE_TWO_DECLARATIONS
    request = replace(inputs["request"], catalog=HookPointCatalog(PHASE_ONE_DECLARATIONS + PHASE_TWO_DECLARATIONS))
    runtime = Mock(side_effect=AssertionError("allocation"))
    monkeypatch.setattr(module, "HookRuntime", runtime)
    with pytest.raises(ValueError):
        module.acquire_summary_hooks_owner(**(inputs | {"request": request}))
    runtime.assert_not_called()


def test_public_partial_input_rejected_before_project_lock(inputs, monkeypatch):
    """Public validation precedes every resource allocation including workspace locking."""
    from topsailai.workspace import agent_shell
    lock = Mock(side_effect=AssertionError("lock allocation"))
    monkeypatch.setattr(agent_shell, "ctxm_project_workspace_lock", lock)
    with pytest.raises(ValueError):
        agent_shell.get_agent_chat(summary_preparation_request=inputs["request"])
    lock.assert_not_called()


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, ValueError])
def test_failed_startup_cleanup_preserves_recovery_custody(inputs, monkeypatch, kind):
    """Failed initialization never caches; cleanup interruption retains exact owner authority."""
    primary = RuntimeError("startup")
    cleanup = kind()
    monkeypatch.setattr(module.ConfiguredHookRegistrar, "from_prepared", Mock(side_effect=primary))
    original = module.SummaryHooksOwner.close
    def interrupt(owner):
        """Expose interrupted cleanup without losing the acquired Runtime owner."""
        monkeypatch.setattr(module.SummaryHooksOwner, "close", original)
        raise cleanup
    monkeypatch.setattr(module.SummaryHooksOwner, "close", interrupt)
    expected = cleanup if isinstance(cleanup, (KeyboardInterrupt, SystemExit)) else primary
    with pytest.raises(type(expected)) as raised:
        module.acquire_summary_hooks_owner(**inputs)
    assert raised.value is expected and module._owner is None
    assert expected.summary_hooks_owner is primary.summary_hooks_owner
    assert expected.summary_hooks_owner.close().fully_closed
