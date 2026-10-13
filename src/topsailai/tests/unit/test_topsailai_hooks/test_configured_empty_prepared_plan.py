"""Zero-resource executable preparation regressions. Author: DawsonLin."""

from types import SimpleNamespace

import pytest

from topsailai.hooks.artifact_leases import ArtifactLeaseManager
from topsailai.hooks.configured_contracts import SummaryPreparationRequest
from topsailai.hooks.configured_executor import ConfiguredHookExecutor, HookOperation
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.configured_runtime import register_summary_prepared
from topsailai.hooks.points.catalog import SUMMARY_CATALOG, PHASE_ONE_DECLARATIONS
from topsailai.tests.unit.test_topsailai_hooks.test_configured_preparation import (
    secure_test_root, _runtime,
)
from topsailai.tests.unit.test_topsailai_hooks.test_summary_prepared_registration import (
    _configuration, _trust,
)


@pytest.mark.parametrize("point", PHASE_ONE_DECLARATIONS)
def test_empty_point_registers_dispatches_and_retires(secure_test_root, monkeypatch, point):
    """An empty inventory retains exactly one successful terminal and owned cleanup."""
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)

    def unexpected_work(*args, **kwargs):
        """Reject any attempt to capture or probe nonexistent executable resources."""
        pytest.fail("empty point attempted executable work")

    monkeypatch.setattr(ArtifactLeaseManager, "capture", unexpected_work)
    monkeypatch.setattr(
        "topsailai.hooks.configured_preparation._run_with_module_probe_session",
        unexpected_work,
    )
    try:
        registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope,
            SummaryPreparationRequest(_configuration(point, sources), SUMMARY_CATALOG))
        assert registrar.dispositions[0].kind == "registered", registrar.dispositions
        _, owner = runtime._registry.configured_plan(scope.scope_id, point.name)
        plan = owner.snapshot.plan
        assert plan.modules == ()
        assert plan.default_script_hook.scripts == ()
        assert plan.handlers == (plan.default_script_hook,)
        assert plan.capture_policy.max_entries >= 1
        executor = ConfiguredHookExecutor(runtime, scope, registrar, SUMMARY_CATALOG)
        operation = HookOperation("empty_point")
        payload = dict(schema_version=1, operation_id=operation.operation_id,
                       point_name=point.name,
                       outcome={"before": "before", "success": "success", "error": "error"}[point.phase])
        if point.phase == "error":
            payload.update(error_category="unknown",
                failed_stage="generation_unknown" if "summary_generate" in point.name
                else "application_unknown")
            if "summary_apply" in point.name:
                payload["partial_apply_possible"] = False
        report = executor.dispatch(point, payload=payload, operation=operation)
        assert report.rejection_reason is None
        result = report.unified_result
        assert result.status == "success"
        assert len(result.handlers) == 1
        terminal = result.handlers[0]
        assert (terminal.handler.id, terminal.handler.kind, terminal.status) == (
            "hook_script", "default_script_hook", "success")
        assert terminal.children == ()
        assert terminal.cleanup.state == "safe"
        aggregate = owner._candidate._capture_owner._ownership
        assert runtime.retire_configured(point.name, scope)
        assert aggregate.state == "closed"
        assert not runtime.cleanup_debts()
    finally:
        runtime.close()


@pytest.mark.parametrize("failure", ["missing", "unreadable", "trust", "capture", "probe"])
def test_failed_resource_is_not_an_empty_success(secure_test_root, monkeypatch, failure):
    """Resource errors reject the entire point instead of publishing an empty fallback."""
    sources, root, _ = secure_test_root
    runtime, scope = _runtime(sources, root)
    point = PHASE_ONE_DECLARATIONS[0]
    folder = sources / "missing" if failure == "missing" else sources
    if failure in {"trust", "capture", "probe"}:
        source = sources / "candidate.py"
        source.write_text("value = 1\n" if failure == "probe"
                          else "def main():\n    return None\n")
        if failure != "trust":
            _trust(runtime, source)
    if failure == "capture":
        def reject_capture(*args, **kwargs):
            """Inject a sealed-capture rejection after real candidate discovery."""
            return SimpleNamespace(accepted=False, lease=None, errors=("artifact_rejected",))
        monkeypatch.setattr(ArtifactLeaseManager, "capture", reject_capture)
    if failure == "unreadable":
        def deny_scan(*args, **kwargs):
            """Inject access denial portably even when the test host runs as root."""
            raise PermissionError("test directory access denied")
        monkeypatch.setattr("topsailai.hooks.module_discovery.os.scandir", deny_scan)
    try:
        result = register_summary_prepared(runtime,
            SummaryPreparationRequest(_configuration(point, folder), SUMMARY_CATALOG), scope)
        disposition = result.dispositions[0]
        assert disposition.kind == "unavailable_preparation_failure"
        assert disposition.reason in {"internal_error", "discovery_rejected",
                                      "artifact_rejected", "trust_rejected", "binding_conflict"}
        assert runtime._registry.configured_plan(scope.scope_id, point.name)[1] is None
        assert not runtime.cleanup_debts()
    finally:
        runtime.close()


@pytest.mark.parametrize("identities", [("one",) * 129, ("one", "two")])
def test_nonempty_inventory_constraints_remain_enforced(identities):
    """Empty-plan support must not weaken inventory size or lease correlation."""
    from topsailai.hooks.configured_preparation import (
        _build_executable_plan, _PreparationRejected,
    )

    captured = tuple(SimpleNamespace(lease=SimpleNamespace(identity=value))
                     for value in identities)
    with pytest.raises(_PreparationRejected, match="binding_conflict"):
        _build_executable_plan(SimpleNamespace(), captured)
