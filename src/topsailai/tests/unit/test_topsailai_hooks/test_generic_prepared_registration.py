"""Domain-independent prepared registration regressions. Author: DawsonLin."""

import ast
import builtins
from pathlib import Path
from unittest.mock import Mock

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition, HookSettings
from topsailai.hooks import configured_contracts, configured_preparation, configured_registration, configured_runtime
from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy, ConfiguredPreparationRequest
from topsailai.hooks.configured_executor import ConfiguredHookExecutor, HookOperation
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.tests.unit.test_topsailai_hooks import test_configured_preparation as helpers
from topsailai.tests.unit.test_topsailai_hooks.test_configured_preparation import secure_test_root

POINT = HookPointDeclaration("hook__inventory__before__refresh", EventDefinition(
    "hook__inventory__before__refresh", 1, {"type": "object", "properties": {"count": {"type": "integer"}}}), "before", "sync", "inventory")
CATALOG = HookPointCatalog((POINT,))


@pytest.fixture(autouse=True)
def task_temp_root(monkeypatch):
    """Confine reused source and worker fixtures to the current task root."""
    monkeypatch.setattr(helpers, "_PHASE_B_ROOT", Path(__file__).resolve().parents[3] / ".tmp/unit3/fixtures")


@pytest.fixture
def no_business_imports(monkeypatch):
    """Reject even cached point-layer imports during generic preparation."""
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        """Forward infrastructure imports but prohibit business dependencies."""
        if name.startswith("topsailai.hooks.points"):
            pytest.fail("generic prepared path imported business points")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.mark.parametrize("module", [configured_contracts, configured_runtime,
    configured_preparation, configured_registration])
def test_core_has_no_business_imports(module):
    """Inspect imports including function-local imports in every scoped core file."""
    tree = ast.parse(Path(module.__file__).read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    assert not any(name.startswith("topsailai.hooks.points") for name in names)


def configuration(folder, *, name=POINT.name, definition=POINT.definition):
    """Select one generic captured Module using the stable injected contract."""
    return ConfiguredHooks((ConfiguredHookPoint(name, definition, module_folder=folder,
        inject_hook_context=True),), HookSettings())


def test_real_generic_registration_and_dispatch(secure_test_root, no_business_imports):
    """Prepare and execute an authorized non-summary Module without point imports."""
    sources, root, _ = secure_test_root
    source = sources / "inventory.py"
    source.write_text("def main(*, hook_context):\n    result = dict(hook_context)\n"
        "    result['payload'] = dict(hook_context['payload'])\n    return result\n")
    runtime, scope = helpers._runtime(sources, root)
    trust = runtime.configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        closure_assertions=(helpers._assertion(source, "inventory"),), python_runtime=trust.python_runtime)
    try:
        request = ConfiguredPreparationRequest(configuration(sources), CATALOG)
        registrar = configured_registration.ConfiguredHookRegistrar.from_prepared(runtime, scope, request)
        assert registrar.dispositions[0].kind == "registered", registrar.dispositions
        assert registrar.ensure_registered(POINT.name).ready
        executor = ConfiguredHookExecutor(runtime, scope, registrar, CATALOG)
        report = executor.dispatch(POINT, payload={"count": 3}, operation=HookOperation("inventory-1"))
        assert report.rejection_reason is None
        handlers = report.unified_result.handlers
        assert [item.handler.kind for item in handlers] == ["module", "default_script_hook"]
        assert all(item.status == "success" and item.cleanup.state == "safe" for item in handlers)
        assert handlers[0].returned.value == {"event_name": POINT.name, "event_version": 1,
            "operation_id": "inventory-1", "payload": {"count": 3}}
        assert runtime.retire_configured(POINT.name, scope)
        assert not runtime.cleanup_debts()
    finally:
        runtime.close()


@pytest.mark.parametrize("kind", ["disabled", "unknown", "event", "version"])
def test_generic_catalog_decisions_before_io(secure_test_root, monkeypatch, no_business_imports, kind):
    """Retain Catalog identity rejection and configured disablement before discovery."""
    sources, root, _ = secure_test_root
    runtime, scope = helpers._runtime(sources, root)
    name = "hook__inventory__before__unknown" if kind == "unknown" else POINT.name
    definition = EventDefinition("hook__inventory__before__other" if kind == "event" else name,
        2 if kind == "version" else 1)
    monkeypatch.setattr(configured_preparation, "_build_work_sequence",
        Mock(side_effect=AssertionError("unexpected discovery")))
    try:
        request = ConfiguredPreparationRequest(configuration(sources / "absent", name=name,
            definition=definition), CATALOG, frozenset({POINT.name}) if kind == "disabled" else frozenset())
        result = runtime.prepare_configured(request, scope)
        assert result.dispositions[0].reason == (
            "disabled_by_configuration" if kind == "disabled" else "catalog_rejected")
        configured_preparation._build_work_sequence.assert_not_called()
        assert runtime._registry.configured_plan(scope.scope_id, name)[1] is None
    finally:
        runtime.close()


@pytest.mark.parametrize("disabled", [set(), frozenset({1}), frozenset({"hook_unknown"})])
def test_generic_disabled_membership_rejected(disabled, no_business_imports):
    """Only immutable names present in the supplied Catalog may be disabled."""
    with pytest.raises(ValueError):
        ConfiguredPreparationRequest(ConfiguredHooks((), HookSettings()), CATALOG, disabled)


def test_generic_unauthorized_module_rejects_whole_plan(secure_test_root, no_business_imports):
    """Discovery is not authority even when a non-summary Catalog owns the point."""
    sources, root, _ = secure_test_root
    (sources / "untrusted.py").write_text("def main(*, hook_context):\n    return None\n")
    runtime, scope = helpers._runtime(sources, root)
    try:
        result = configured_runtime.register_prepared_points(runtime,
            ConfiguredPreparationRequest(configuration(sources), CATALOG), scope)
        assert result.dispositions[0].kind == "unavailable_preparation_failure"
        assert result.dispositions[0].reason == "artifact_rejected"
        assert runtime._registry.configured_plan(scope.scope_id, POINT.name)[1] is None
    finally:
        runtime.close()


def test_generic_prepared_api_names(no_business_imports):
    """Expose generic names only, without compatibility aliases or point imports."""
    assert configured_contracts.ConfiguredPreparationRequest is ConfiguredPreparationRequest
    assert configured_contracts.ConfiguredPointDisposition
    assert configured_contracts.ConfiguredPreparationResult
    assert callable(configured_runtime.register_prepared_points)
    for suffix in ("PreparationRequest", "PointDisposition", "PreparationResult"):
        assert not hasattr(configured_contracts, "Summary" + suffix)
    assert not hasattr(configured_contracts, "_SUMMARY" + "_REASONS")
    assert not hasattr(configured_runtime, "register_summary" + "_prepared")
    assert not hasattr(configured_runtime, "_prepare_summary" + "_point")


@pytest.mark.parametrize("route", ["direct", "runtime", "registrar"])
def test_generic_empty_request_entry_routes(secure_test_root, no_business_imports, route):
    """All retained preparation entry routes accept the exact generic request."""
    sources, root, _ = secure_test_root
    runtime, scope = helpers._runtime(sources, root)
    request = ConfiguredPreparationRequest(ConfiguredHooks((), HookSettings()), CATALOG)
    try:
        if route == "direct":
            result = configured_runtime.register_prepared_points(runtime, request, scope)
        elif route == "runtime":
            result = runtime.prepare_configured(request, scope)
        else:
            result = configured_registration.ConfiguredHookRegistrar.from_prepared(runtime, scope, request)
        assert result.dispositions == ()
        assert not runtime.cleanup_debts()
    finally:
        runtime.close()


@pytest.mark.parametrize("case", ["request", "disabled", "disposition", "result"])
def test_generic_contract_error_text(case, no_business_imports):
    """Keep exact validation boundaries while exposing domain-neutral errors."""
    errors = {"request": "preparation request", "disabled": "disabled point",
        "disposition": "point disposition", "result": "preparation result"}
    with pytest.raises(ValueError, match="^invalid configured " + errors[case] + "$"):
        if case == "request":
            ConfiguredPreparationRequest(None, CATALOG)
        elif case == "disabled":
            ConfiguredPreparationRequest(ConfiguredHooks((), HookSettings()), CATALOG,
                frozenset({"hook_unknown"}))
        elif case == "disposition":
            configured_contracts.ConfiguredPointDisposition(POINT.name, "registered", "unknown")
        else:
            configured_contracts.ConfiguredPreparationResult([])


@pytest.mark.parametrize("route", ["direct", "registrar"])
def test_generic_entry_rejects_invalid_request(route, no_business_imports):
    """Reject invalid request shapes before touching runtime or scope state."""
    entry = (configured_runtime.register_prepared_points if route == "direct"
        else configured_registration.ConfiguredHookRegistrar.from_prepared)
    with pytest.raises(ValueError, match="^invalid configured preparation request$"):
        entry(None, None, None)


def test_generic_legacy_configuration_remains_fail_closed(secure_test_root, no_business_imports):
    """Non-request input retains the legacy invalid-configuration result."""
    sources, root, _ = secure_test_root
    runtime, scope = helpers._runtime(sources, root)
    try:
        result = runtime.prepare_configured(None, scope)
        assert not result.accepted
        assert result.errors == ("invalid_configuration",)
    finally:
        runtime.close()


def test_generic_unknown_preparation_reason_is_bounded(monkeypatch, tmp_path, no_business_imports):
    """Unknown internal preparation diagnostics never escape in dispositions."""
    monkeypatch.setattr(configured_runtime, "_prepare_configured_point",
        lambda *args: "unbounded-diagnostic")
    request = ConfiguredPreparationRequest(configuration(tmp_path), CATALOG)
    result = configured_runtime.register_prepared_points(None, request, None)
    assert result.dispositions[0].reason == "internal_error"
    assert result.dispositions[0].kind == "unavailable_preparation_failure"
