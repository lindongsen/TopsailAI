"""U4 exact original-capture summary preparation regressions. Author: DawsonLin."""

import pytest
from pathlib import Path

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, ConfiguredTrustPolicy, HookSettings
from topsailai.hooks.configured_contracts import SummaryPreparationRequest
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.configured_preparation import prepare_private
from topsailai.hooks.configured_runtime import register_summary_prepared
from tests.summary_catalog_support import SUMMARY_CATALOG, PHASE_ONE_DECLARATIONS, PHASE_TWO_DECLARATIONS
from topsailai.tests.unit.test_topsailai_hooks.test_configured_preparation import secure_test_root, _runtime, _assertion


def _configuration(point, folder):
    """Build one explicit catalog-correlated configuration."""
    return ConfiguredHooks((ConfiguredHookPoint(point.name, point.definition, module_folder=folder),), HookSettings())


def _trust(runtime, source):
    """Pin the exact test-owned module content in deployment authority."""
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        closure_assertions=(_assertion(source, source.stem),), python_runtime=trust.python_runtime)


def test_real_original_capture_registration_and_retirement(secure_test_root, monkeypatch):
    """A real managed probe publishes original captures and fresh-budget retirement."""
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main(context):\n    return {'ok': True}\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    point = PHASE_ONE_DECLARATIONS[0]
    try:
        monkeypatch.setattr(runtime, "register_configured", lambda *a, **k: pytest.fail("legacy registration"))
        registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope,
            SummaryPreparationRequest(_configuration(point, sources), SUMMARY_CATALOG))
        assert registrar.dispositions[0].kind == "registered", registrar.dispositions
        assert registrar.ensure_registered(point.name).ready
        _, owner = runtime._registry.configured_plan(scope.scope_id, point.name)
        aggregate = owner._candidate._capture_owner._ownership
        aggregate.deadline = 0
        assert runtime.retire_configured(point.name, scope)
        assert aggregate.state == "closed"
    finally:
        runtime.close()


@pytest.mark.parametrize("point", PHASE_TWO_DECLARATIONS)
def test_phase_two_rejected_before_discovery(secure_test_root, monkeypatch, point):
    """Inactive metadata never authorizes filesystem work."""
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)
    monkeypatch.setattr("topsailai.hooks.configured_preparation._build_work_sequence",
        lambda *a: pytest.fail("discovery"))
    try:
        result = register_summary_prepared(runtime,
            SummaryPreparationRequest(_configuration(point, sources), SUMMARY_CATALOG), scope)
        assert result.dispositions[0].reason == "catalog_rejected"
    finally:
        runtime.close()


def test_disabled_and_invalid_entry_are_distinct(secure_test_root):
    """Explicit disabled input does no work; enabled invalid module fails wholly."""
    sources, root, _ = secure_test_root
    source = sources / "broken.py"
    source.write_text("value = 1\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    first, second = PHASE_ONE_DECLARATIONS[:2]
    config = ConfiguredHooks(tuple(ConfiguredHookPoint(p.name, p.definition, module_folder=sources)
        for p in (first, second)), HookSettings())
    try:
        result = register_summary_prepared(runtime,
            SummaryPreparationRequest(config, SUMMARY_CATALOG, frozenset({first.name})), scope)
        assert [item.kind for item in result.dispositions] == [
            "disabled_by_configuration", "unavailable_preparation_failure"]
        assert result.dispositions[1].reason == "binding_conflict"
        assert runtime._registry.configured_plan(scope.scope_id, second.name)[1] is None
    finally:
        runtime.close()


def test_adoption_is_one_shot(secure_test_root):
    """An old image cannot mint cleanup authority after exact adoption."""
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main(context):\n    return None\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    try:
        image = prepare_private(runtime, _configuration(PHASE_ONE_DECLARATIONS[0], sources), scope, _executable=True)
        candidate = image.adopt(runtime._backend)
        with pytest.raises(RuntimeError):
            image.adopt(runtime._backend)
        assert image.close().accepted
        assert candidate.close().accepted
    finally:
        runtime.close()



def test_real_module_then_script_dispatch(secure_test_root, monkeypatch):
    """Execute captured modules before the terminal script with unchanged identity."""
    import sys
    from topsailai.hooks.configuration import HookLimits
    from topsailai.hooks.configured_contracts import ConfiguredScript
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor, HookOperation
    from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
    from topsailai.hooks.points.context import before_summary_generate_user2agent as selected

    sources, root, _ = secure_test_root
    modules = sources / "modules"
    modules.mkdir(mode=0o700)
    source = modules / "valid.py"
    source.write_text("def main(value):\n    return {'operation_id': value}\n")
    script = sources / "terminal"
    executable = Path(sys.executable).resolve(strict=True)
    script.write_text(f"#!{executable}\n" +
        "import sys, json, os, struct\n"
        "request = json.loads(sys.stdin.buffer.read())\n"
        "result = {key: request[key] for key in ('protocol_version', 'delivery_id', 'invocation_id', 'entry_index')}\n"
        "result['value'] = 'terminal'\n"
        "body = json.dumps(result).encode()\n"
        "os.write(int(os.environ['TOPSAILAI_HOOK_RESULT_FD']), struct.pack('!I', len(body)) + body)\n")
    script.chmod(0o700)
    runtime, scope = _runtime(sources, root,
        settings=HookSettings(limits=HookLimits(dispatch_timeout_ms=4750)))
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        allowed_interpreters=(executable,),
        closure_assertions=(_assertion(source, "valid"), _assertion(script, "terminal", "script")),
        python_runtime=trust.python_runtime)
    config = ConfiguredHooks((ConfiguredHookPoint(selected.NAME, selected.POINT.definition,
        module_folder=modules, module_args=("u4_real",), script=ConfiguredScript(script, ExecutablePlatformPolicy("posix", allowed_interpreters=(str(executable),)))),), HookSettings())
    try:
        registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope,
            SummaryPreparationRequest(config, SUMMARY_CATALOG))
        assert registrar.dispositions[0].kind == "registered", registrar.dispositions
        executor = ConfiguredHookExecutor(runtime, scope, registrar, SUMMARY_CATALOG)
        events = []
        original = runtime.make_event
        def observe(*args, **kwargs):
            """Observe immutable event identity without replacing production transport."""
            event = original(*args, **kwargs)
            events.append(event)
            return event
        monkeypatch.setattr(runtime, "make_event", observe)
        report = executor.dispatch(selected.POINT,
            payload=selected.build_payload(operation_id="u4_real"), operation=HookOperation("u4_real"))
        assert report.rejection_reason is None
        result = report.unified_result
        assert [item.handler.kind for item in result.handlers] == ["module", "default_script_hook"]
        assert result.handlers[0].status == "success", result.handlers[0]
        assert result.handlers[0].returned.value == {'operation_id': 'u4_real'}
        assert (events[0].name, events[0].major_version, events[0].operation_id) == (selected.NAME, 1, 'u4_real')
        assert result.handlers[-1].status == "success"
    finally:
        runtime.close()


def test_valid_sibling_survives_failed_point(secure_test_root):
    """One invalid complete transaction never rolls back a valid sibling."""
    sources, root, _ = secure_test_root
    valid, broken = sources / "valid", sources / "broken"
    valid.mkdir(mode=0o700)
    broken.mkdir(mode=0o700)
    good, bad = valid / "good.py", broken / "bad.py"
    good.write_text("def main(context):\n    return None\n")
    bad.write_text("value = 1\n")
    runtime, scope = _runtime(sources, root)
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        closure_assertions=(_assertion(good, "good"), _assertion(bad, "bad")), python_runtime=trust.python_runtime)
    first, second = PHASE_ONE_DECLARATIONS[:2]
    config = ConfiguredHooks((ConfiguredHookPoint(first.name, first.definition, module_folder=broken),
        ConfiguredHookPoint(second.name, second.definition, module_folder=valid)), HookSettings())
    try:
        result = register_summary_prepared(runtime, SummaryPreparationRequest(config, SUMMARY_CATALOG), scope)
        assert [item.kind for item in result.dispositions] == ["unavailable_preparation_failure", "registered"]
        assert runtime._registry.configured_plan(scope.scope_id, first.name)[1] is None
        assert runtime._registry.configured_plan(scope.scope_id, second.name)[1] is not None
    finally:
        runtime.close()


def test_duplicate_and_replacement_settle_exact_aggregates(secure_test_root):
    """Identical publication disposes only the loser; replacement retires old custody."""
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main(context):\n    return 1\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    point = PHASE_ONE_DECLARATIONS[0]
    request = SummaryPreparationRequest(_configuration(point, sources), SUMMARY_CATALOG)
    try:
        assert register_summary_prepared(runtime, request, scope).dispositions[0].kind == "registered"
        _, first = runtime._registry.configured_plan(scope.scope_id, point.name)
        aggregate = first._candidate._capture_owner._ownership
        assert register_summary_prepared(runtime, request, scope).dispositions[0].kind == "registered"
        assert runtime._registry.configured_plan(scope.scope_id, point.name)[1] is first
        assert aggregate.state == "transferred"
        source.write_text("def main(context):\n    return 2\n")
        _trust(runtime, source)
        assert register_summary_prepared(runtime, request, scope).dispositions[0].kind == "registered"
        assert runtime._registry.configured_plan(scope.scope_id, point.name)[1] is not first
        assert aggregate.state == "closed"
    finally:
        runtime.close()


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_publication_interrupt_retains_candidate(secure_test_root, monkeypatch, interrupt_type):
    """Host interruption retains the exact candidate in runtime recovery custody."""
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main(context):\n    return None\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    interruption = interrupt_type()
    def interrupt(*args, **kwargs):
        """Inject once at the real publication boundary."""
        raise interruption
    monkeypatch.setattr(runtime._registry, "publish_hook_point", interrupt)
    try:
        with pytest.raises(interrupt_type) as caught:
            register_summary_prepared(runtime,
                SummaryPreparationRequest(_configuration(PHASE_ONE_DECLARATIONS[0], sources), SUMMARY_CATALOG), scope)
        assert caught.value is interruption
        candidate = caught.value.recovery_owner
        assert candidate._capture_owner._ownership.state == "transferred"
        debts = runtime._publication_recovery.cleanup_debts()
        assert debts
        assert runtime._publication_recovery.retry_cleanup(debts[0].debt_id)
        assert candidate._capture_owner._ownership.state == "closed"
    finally:
        runtime.close()


def test_rejected_publication_pending_cleanup_is_recoverable(secure_test_root, monkeypatch):
    """A rejected candidate remains journaled until exact fresh-budget cleanup succeeds."""
    from types import SimpleNamespace
    from topsailai.hooks.configured_preparation import _PreparedCaptureOwner
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main(context):\n    return None\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    monkeypatch.setattr(runtime._registry, "publish_hook_point",
        lambda *a, **k: SimpleNamespace(accepted=False, changed=False))
    original = _PreparedCaptureOwner.close
    def pending(owner):
        """Retain original custody while forcing one bounded cleanup failure."""
        from topsailai.hooks.artifact_contracts import ArtifactDisposeResult
        return ArtifactDisposeResult(False, False, True, ("cleanup_pending",))
    monkeypatch.setattr(_PreparedCaptureOwner, "close", pending)
    try:
        result = register_summary_prepared(runtime,
            SummaryPreparationRequest(_configuration(PHASE_ONE_DECLARATIONS[0], sources), SUMMARY_CATALOG), scope)
        assert result.dispositions[0].reason == "cleanup_pending"
        debts = runtime._publication_recovery.cleanup_debts()
        assert debts
        monkeypatch.setattr(_PreparedCaptureOwner, "close", original)
        assert runtime._publication_recovery.retry_cleanup(debts[0].debt_id)
        assert not runtime._publication_recovery.cleanup_debts()
    finally:
        runtime.close()



@pytest.mark.parametrize("kind", ["unknown", "event", "version"])
def test_identity_rejection_performs_no_discovery(secure_test_root, monkeypatch, kind):
    """Unknown names and mismatched identity are rejected before filesystem I/O."""
    from topsailai.hooks import EventDefinition
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)
    point = PHASE_ONE_DECLARATIONS[0]
    name = "hook__context__before__unknown" if kind == "unknown" else point.name
    definition = EventDefinition("hook__context__before__other" if kind == "event" else name,
        2 if kind == "version" else 1)
    config = ConfiguredHooks((ConfiguredHookPoint(name, definition, module_folder=sources),), HookSettings())
    monkeypatch.setattr("topsailai.hooks.configured_preparation._build_work_sequence",
        lambda *args: pytest.fail("discovery"))
    try:
        result = register_summary_prepared(runtime, SummaryPreparationRequest(config, SUMMARY_CATALOG), scope)
        assert result.dispositions[0].reason == "catalog_rejected"
    finally:
        runtime.close()


def test_disabled_point_performs_zero_work(secure_test_root, monkeypatch):
    """Explicit disabled membership prevents even discovery of absent resources."""
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)
    point = PHASE_ONE_DECLARATIONS[0]
    monkeypatch.setattr("topsailai.hooks.configured_preparation._build_work_sequence",
        lambda *args: pytest.fail("discovery"))
    try:
        result = register_summary_prepared(runtime, SummaryPreparationRequest(
            _configuration(point, sources / "absent"), SUMMARY_CATALOG, frozenset({point.name})), scope)
        assert result.dispositions[0].kind == "disabled_by_configuration"
    finally:
        runtime.close()


def test_retired_owner_retries_expired_cleanup_epoch(secure_test_root, monkeypatch):
    """A first expired retirement budget preserves exact owner retry custody."""
    import time
    from topsailai.hooks.artifact_leases import ArtifactLeaseManager
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main():\n    return None\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    point = PHASE_ONE_DECLARATIONS[0]
    try:
        result = register_summary_prepared(runtime,
            SummaryPreparationRequest(_configuration(point, sources), SUMMARY_CATALOG), scope)
        assert result.dispositions[0].kind == "registered"
        _, owner = runtime._registry.configured_plan(scope.scope_id, point.name)
        aggregate = owner._candidate._capture_owner._ownership
        original = ArtifactLeaseManager.close
        def expire(manager, *, deadline):
            """Fail the first close at the real bounded manager boundary."""
            return original(manager, deadline=time.monotonic() - 1)
        monkeypatch.setattr(ArtifactLeaseManager, "close", expire)
        runtime.retire_configured(point.name, scope)
        assert not owner.settled
        assert aggregate.state == "cleanup_pending"
        monkeypatch.setattr(ArtifactLeaseManager, "close", original)
        # A synthetic publication debt keeps exact owner recovery reachable when
        # expiry preceded physical debt creation.
        debts = runtime._publication_recovery.cleanup_debts()
        assert debts
        assert runtime._publication_recovery.retry_cleanup(debts[0].debt_id)
        assert owner.settled and aggregate.state == "closed"
    finally:
        runtime.close()


@pytest.mark.parametrize("disabled", [set(), frozenset({"hook__context__after__summary_generate_user2agent"}), frozenset({1})])
def test_disabled_membership_validation(disabled):
    """Disablement rejects mutable, inactive, or malformed memberships."""
    with pytest.raises(ValueError):
        SummaryPreparationRequest(ConfiguredHooks((), HookSettings()), SUMMARY_CATALOG, disabled)



def test_two_valid_points_share_runtime_without_shared_capture(secure_test_root):
    """Independent point transactions produce two active exact owners."""
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main():\n    return None\n")
    runtime, scope = _runtime(sources, root)
    _trust(runtime, source)
    points = PHASE_ONE_DECLARATIONS[:2]
    config = ConfiguredHooks(tuple(ConfiguredHookPoint(p.name, p.definition, module_folder=sources)
        for p in points), HookSettings())
    try:
        result = runtime.prepare_configured(SummaryPreparationRequest(config, SUMMARY_CATALOG), scope)
        assert all(item.kind == "registered" for item in result.dispositions)
        owners = [runtime._registry.configured_plan(scope.scope_id, p.name)[1] for p in points]
        assert owners[0] is not owners[1]
        assert owners[0].snapshot.plan.modules[0].captured_path != owners[1].snapshot.plan.modules[0].captured_path
    finally:
        runtime.close()


@pytest.mark.parametrize("failure", ["trust", "capture", "script"])
def test_failed_resource_never_publishes_partial_point(secure_test_root, monkeypatch, failure):
    """Resource-level failures yield safe tokens rather than partial active plans."""
    from topsailai.hooks.configured_contracts import ConfiguredScript
    from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
    from topsailai.hooks.artifact_leases import ArtifactLeaseManager
    from types import SimpleNamespace
    sources, root, _ = secure_test_root
    source = sources / "valid.py"
    source.write_text("def main():\n    return None\n")
    runtime, scope = _runtime(sources, root)
    point = PHASE_ONE_DECLARATIONS[0]
    if failure != "trust":
        _trust(runtime, source)
    if failure == "capture":
        monkeypatch.setattr(ArtifactLeaseManager, "capture", lambda *a, **k:
            SimpleNamespace(accepted=False, lease=None, errors=("private-secret-source",)))
    script = ConfiguredScript(sources / "absent", ExecutablePlatformPolicy("posix")) if failure == "script" else None
    config = ConfiguredHooks((ConfiguredHookPoint(point.name, point.definition,
        module_folder=sources, script=script),), HookSettings())
    try:
        result = register_summary_prepared(runtime, SummaryPreparationRequest(config, SUMMARY_CATALOG), scope)
        disposition = result.dispositions[0]
        assert disposition.kind == "unavailable_preparation_failure"
        assert disposition.reason in {"artifact_rejected", "trust_rejected"}
        assert "private-secret-source" not in repr(result)
        assert str(sources) not in repr(result)
        assert runtime._registry.configured_plan(scope.scope_id, point.name)[1] is None
    finally:
        runtime.close()


def test_bad_module_disallows_script_only_fallback(secure_test_root):
    """An invalid module fails before any terminal-only plan is published."""
    from topsailai.hooks.configured_contracts import ConfiguredScript
    from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
    import sys
    sources, root, _ = secure_test_root
    modules = sources / "modules"
    modules.mkdir(mode=0o700)
    source = modules / "broken.py"
    source.write_text("value = 1\n")
    executable = Path(sys.executable).resolve(strict=True)
    script = sources / "terminal"
    script.write_text(f"#!{executable}\npass\n")
    script.chmod(0o700)
    runtime, scope = _runtime(sources, root)
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        allowed_interpreters=(executable,), closure_assertions=(_assertion(source, "broken"),
            _assertion(script, "terminal", "script")), python_runtime=trust.python_runtime)
    point = PHASE_ONE_DECLARATIONS[0]
    config = ConfiguredHooks((ConfiguredHookPoint(point.name, point.definition, module_folder=modules,
        script=ConfiguredScript(script, ExecutablePlatformPolicy("posix", (str(executable),)))),), HookSettings())
    try:
        result = register_summary_prepared(runtime, SummaryPreparationRequest(config, SUMMARY_CATALOG), scope)
        assert result.dispositions[0].reason == "binding_conflict"
        assert runtime._registry.configured_plan(scope.scope_id, point.name)[1] is None
    finally:
        runtime.close()



def test_prepared_registrar_close_and_reload_are_not_legacy(secure_test_root):
    """Prepared readiness closes with its scope and cannot reload legacy sources."""
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)
    point = PHASE_ONE_DECLARATIONS[0]
    try:
        registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope,
            SummaryPreparationRequest(_configuration(point, sources), SUMMARY_CATALOG,
                frozenset({point.name})))
        assert not registrar.ensure_registered(point.name).ready
        with pytest.raises(ValueError, match="explicit replacement"):
            registrar.reload(None)
        registrar.close()
        assert not registrar.start().ready
        assert not registrar.ensure_registered(point.name).ready
    finally:
        runtime.close()



@pytest.mark.parametrize("condition,reason", [("cancelled", "cancelled"), ("closed", "scope_closed")])
def test_public_boundary_failures_are_safe(secure_test_root, condition, reason):
    """Cancelled preparation and closed runtime admit no executable plan."""
    import threading
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)
    cancellation = threading.Event()
    if condition == "cancelled":
        cancellation.set()
    else:
        runtime.close()
    try:
        result = register_summary_prepared(runtime,
            SummaryPreparationRequest(_configuration(PHASE_ONE_DECLARATIONS[0], sources), SUMMARY_CATALOG),
            scope, cancellation=cancellation)
        assert result.dispositions[0].reason == reason
        assert result.dispositions[0].kind == "unavailable_preparation_failure"
    finally:
        runtime.close()



def test_summary_contract_rejects_unsafe_results():
    """Detached reports reject raw reasons, wrong shapes, and duplicate points."""
    from topsailai.hooks.configured_contracts import SummaryPointDisposition, SummaryPreparationResult
    point = PHASE_ONE_DECLARATIONS[0]
    with pytest.raises(ValueError):
        SummaryPreparationRequest(None, SUMMARY_CATALOG)
    with pytest.raises(ValueError):
        SummaryPointDisposition(point.name, "registered", "raw-secret-path")
    valid = SummaryPointDisposition(point.name, "registered", "registered")
    with pytest.raises(ValueError):
        SummaryPreparationResult((valid, valid))
    with pytest.raises(ValueError):
        SummaryPreparationResult([valid])


def test_summary_recovery_capacity_is_checked_before_preparation(secure_test_root, monkeypatch):
    """Full recovery journal prevents creating unowned preparation resources."""
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)
    monkeypatch.setattr(runtime._publication_recovery, "reserve", lambda *args: None)
    monkeypatch.setattr("topsailai.hooks.configured_preparation.prepare_private",
        lambda *args, **kwargs: pytest.fail("preparation"))
    try:
        result = register_summary_prepared(runtime,
            SummaryPreparationRequest(_configuration(PHASE_ONE_DECLARATIONS[0], sources), SUMMARY_CATALOG), scope)
        assert result.dispositions[0].reason == "publication_capacity_exceeded"
    finally:
        runtime.close()
