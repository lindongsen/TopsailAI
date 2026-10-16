"""Composed summary Script process acceptance. Author: DawsonLin."""

import os

import pytest

from tests.bdd.summary_script_membership_harness import MixedDeployment
from topsailai.hooks.configured_executor import HookOperation
from topsailai.hooks.points.context import SummaryHookAdapter
from topsailai.hooks.points.catalog import PHASE_ONE_DECLARATIONS


@pytest.fixture
def deployment(tmp_path, request):
    """Register cleanup before real capture, startup or dispatch."""
    tree = MixedDeployment(tmp_path)
    request.addfinalizer(tree.close)
    return tree


def emit(owner, identity="integration", layer="user2agent"):
    """Use the real adapter's checkpoint custody and configured executor."""
    operation = SummaryHookAdapter(owner.executor).begin(layer, operation=HookOperation(identity))
    return operation, operation.emit("before_summary_generate")


def test_real_order_and_checkpoint_custody(deployment):
    """Two Modules precede two Scripts once, and distinct operations stay independent."""
    owner = deployment.start()
    operation, result = emit(owner)
    assert not result.already_handled
    handlers = result.report.unified_result.handlers
    assert [h.handler.kind for h in handlers] == ["module", "module", "default_script_hook"]
    assert [h.handler.name.rsplit(":", 1)[-1] for h in handlers] == ["Alpha", "zeta", "hook_script"]
    assert [h.handler.name for h in handlers[-1].children] == ["A", "z"]
    assert all(h.status == "success" and h.cleanup.state == "safe" for h in handlers)
    assert [r["name"] for r in deployment.rows()] == ["Alpha", "zeta", "A", "z"]
    assert operation.emit("before_summary_generate").already_handled
    assert len(deployment.rows()) == 4
    emit(owner, "second-session")
    rows = deployment.rows()
    assert len(rows) == 8
    assert {r["payload"]["operation_id"] for r in rows} == {"integration", "second-session"}
    assert all(r["pid"] != os.getpid() for r in rows)


def test_immutable_capture_and_stale_sibling_isolation(deployment, caplog):
    """Old snapshots remain exact; stale new membership disables only its point."""
    trust = deployment.authorize()
    owner = deployment.start(trust)
    point = deployment.request().configuration.hook_points[0]
    deployment.add_script(point, "new")
    emit(owner)
    assert [r["name"] for r in deployment.rows()] == ["Alpha", "zeta", "A", "z"]
    assert owner.close().fully_closed
    stale = deployment.start(trust)
    disposition = next(d for d in stale.startup_report.dispositions if d.hook_name == point.hook_name)
    assert disposition.kind == "unavailable_preparation_failure"
    assert (point.hook_name, disposition.kind, disposition.reason, 1) in stale.startup_report.metrics
    assert point.hook_name in caplog.text
    before = len(deployment.rows())
    assert emit(stale)[1].report.rejection_reason is not None
    assert len(deployment.rows()) == before
    emit(stale, "healthy", "agent2llm")
    assert len(deployment.rows()) == before + 4
    assert stale.close().fully_closed
    fresh = deployment.start()
    emit(fresh, "new-lifetime")
    assert [r["name"] for r in deployment.rows()[-5:]] == ["Alpha", "zeta", "A", "new", "z"]


def test_settled_script_error_allows_safe_successor(tmp_path, request):
    """A real Script exception remains report-only and does not suppress its sibling."""
    tree = MixedDeployment(tmp_path, "script_failure")
    request.addfinalizer(tree.close)
    result = emit(tree.start())[1].report
    children = result.unified_result.handlers[-1].children
    assert children[0].status != "success"
    assert children[1].status == "success" and children[1].cleanup.state == "safe"
    assert [r["name"] for r in tree.rows()] == ["Alpha", "zeta", "A", "z"]


def test_real_deadline_stops_worker_and_unsafe_successor(tmp_path, request):
    """Real blocked process expires under the production deadline and is settled."""
    tree = MixedDeployment(tmp_path, "blocked")
    request.addfinalizer(tree.close)
    owner = tree.start()
    result = emit(owner)[1].report
    children = result.unified_result.handlers[-1].children
    assert any(child.status in ("timeout", "not_run") for child in children)
    assert [r["name"] for r in tree.rows()] == ["Alpha", "zeta", "A"]
    tree.close()


@pytest.mark.parametrize("layer", ["user2agent", "agent2llm"])
def test_local_owner_empty_result_branch(tmp_path, request, monkeypatch, layer):
    """Local owner branch evidence only: no claim of empty-provider acceptance."""
    from tests.bdd.summary_script_membership_harness import SummaryScriptScenario
    scenario = SummaryScriptScenario(monkeypatch, request, layer, "local_empty", "sse", tmp_path)
    observe = scenario._observe
    calls = []

    def observe_and_inject(runtime):
        """Keep real generation bracketing and managed observers around the local seam."""
        observe(runtime)

        def empty(*args, **kwargs):
            """Return empty only at this selected owner instance's generation call."""
            calls.append(1)
            return ""

        monkeypatch.setattr(runtime, "_chat_for_summary", empty)

    monkeypatch.setattr(scenario, "_observe", observe_and_inject)
    scenario.exercise()
    assert calls == [1, 1]  # One enabled call and one equivalent disabled call.
    assert scenario.result is None and scenario.error is None
    assert scenario.observed_state["total_requests"] == 0
    assert scenario.observed_history == scenario.original_messages
    assert not scenario.application_checked
    assert [event[0] for event in scenario.events] == [
        "hook__context__before__summary_generate_" + layer]
    assert [row["name"] for row in scenario.deployment.rows()] == ["Alpha", "zeta", "A", "z"]
    from topsailai.hooks.point_entry import pending_cleanup
    assert all(r.status == "success" for r in scenario.reports[0])
    assert pending_cleanup() == ()


@pytest.mark.parametrize("layer", ["user2agent", "agent2llm"])
def test_direct_order_and_checkpoint_custody(tmp_path, request, monkeypatch, layer):
    """Actual direct workers preserve order and consume each operation checkpoint once."""
    import topsailai.hooks as hooks
    from tests.bdd.summary_script_membership_harness import DirectDeployment
    from topsailai.hooks.points.context.summary_adapter import DirectSummaryOperation
    tree = DirectDeployment(tmp_path)
    request.addfinalizer(tree.close)
    monkeypatch.setattr(hooks, "_point_configuration", ())
    hooks.initialize_hook_points(tree.config)
    operation = DirectSummaryOperation(layer)
    result = operation.emit("before_summary_generate")
    assert [(r.kind, r.name, r.status) for r in result] == [
        ("module", "Alpha.py", "success"), ("module", "observer.py", "success"),
        ("module", "zeta.py", "success"), ("script", "A", "success"),
        ("script", "z", "success")]
    assert operation.emit("before_summary_generate").already_handled
    assert [r["name"] for r in tree.rows()] == ["Alpha", "zeta", "A", "z"]
    second = DirectSummaryOperation(layer)
    second.emit("before_summary_generate")
    rows = tree.rows()
    assert len(rows) == 8
    assert {r["payload"]["operation_id"] for r in rows if "payload" in r} == {
        operation.operation.operation_id, second.operation.operation_id}
    assert all("payload" not in r for r in rows if r["name"] in ("A", "z"))


@pytest.mark.parametrize("fault", ["script_failure", "blocked"])
def test_direct_error_and_deadline_settlement(tmp_path, request, monkeypatch, fault):
    """Direct Script errors allow siblings while real deadline expiration stops them."""
    import topsailai.hooks as hooks
    from tests.bdd.summary_script_membership_harness import DirectDeployment
    from topsailai.hooks.points.context.summary_adapter import DirectSummaryOperation
    tree = DirectDeployment(tmp_path, fault)
    request.addfinalizer(tree.close)
    monkeypatch.setattr(hooks, "_point_configuration", ())
    hooks.initialize_hook_points(tree.config)
    result = DirectSummaryOperation("user2agent").emit("before_summary_generate")
    assert next(r for r in result if r.name == "A").status == (
        "timeout" if fault == "blocked" else "error")
    assert [r["name"] for r in tree.rows()] == (
        ["Alpha", "zeta", "A"] if fault == "blocked" else ["Alpha", "zeta", "A", "z"])
    tree.close()
