"""Per-point file membership through real prepared workers. Author: DawsonLin."""

from pathlib import Path

import pytest

from topsailai.hooks import ConfiguredTrustPolicy
from topsailai.hooks.points.catalog import PHASE_ONE_DECLARATIONS, PHASE_TWO_DECLARATIONS
from topsailai.tests.unit.test_topsailai_hooks.test_configured_preparation import _assertion, _runtime
from topsailai.tests.unit.test_topsailai_hooks.test_summary_events_observer_lifecycle import emit, ACTIVE, report_evidence, FUNCTIONAL_SETTINGS
from tests.legacy_prepared_support import build_summary_preparation_request, prepared_graph


def test_default_directories_are_point_local_and_phase_one_only():
    """Composition binds directories, never a fixed Module member inventory."""
    request = build_summary_preparation_request()
    points = request.configuration.hook_points
    assert tuple(p.hook_name for p in points) == tuple(p.name for p in PHASE_ONE_DECLARATIONS)
    assert not {p.name for p in PHASE_TWO_DECLARATIONS} & {p.hook_name for p in points}
    assert len({p.module_folder for p in points}) == 8
    for point in points:
        assert point.module_folder.is_dir()
        assert point.module_folder.name == "modules"
        assert point.module_folder.parent.name == point.hook_name.removeprefix("hook__context__").replace("__", "_")
        assert point.inject_hook_context and not point.module_args and not point.module_kwargs
        assert point.script is None


@pytest.mark.parametrize("root", ["relative", Path("relative")])
def test_relative_directory_root_rejected(root):
    """Invalid composition input is rejected without directory probing."""
    with pytest.raises(ValueError, match="absolute"):
        build_summary_preparation_request(points_root=root)


@pytest.fixture
def tree(tmp_path):
    """Create isolated point directories with stable generic entry functions."""
    points = tmp_path / "points"
    points.mkdir(mode=0o700)
    request = build_summary_preparation_request(points_root=points, settings=FUNCTIONAL_SETTINGS)
    for point in request.configuration.hook_points:
        point.module_folder.mkdir(parents=True, mode=0o700)
        (point.module_folder / "zeta.py").write_text(
            'def main(*, hook_context):\n    return {"point": hook_context["event_name"], "member": "zeta"}\n')
    return points, request, tmp_path


def start(tree, *, unauthorized=None):
    """Model deployment authorization plus restart, not runtime self-authorization."""
    points, request, temporary = tree
    root = temporary / "runtime"
    root.mkdir(mode=0o700, exist_ok=True)
    probe, _ = _runtime(points, root, settings=request.configuration.settings)
    authority = probe._configured_trust.python_runtime
    probe.close()
    assert not probe.cleanup_debts()
    assertions = tuple(_assertion(source, source.stem)
        for point in request.configuration.hook_points
        for source in sorted(point.module_folder.glob("*.py")) if source != unauthorized)
    trust = ConfiguredTrustPolicy((points,), closure_assertions=assertions, python_runtime=authority)
    return prepared_graph(request=request, trust_policy=trust, temp_root=str(root))


def members(owner, point, identity):
    """Assert actual ordered execution and terminal custody through the application owner."""
    from topsailai.hooks.points.context import SummaryHookAdapter
    result = emit(SummaryHookAdapter(owner.executor), point, identity)
    assert result.report.rejection_reason is None, (identity, report_evidence(result.report))
    handlers = result.report.unified_result.handlers
    assert handlers[-1].handler.name == "hook_script", (identity, report_evidence(result.report))
    assert handlers[-1].status == "success", (identity, report_evidence(result.report))
    assert all(item.status == "success" for item in handlers), (identity, report_evidence(result.report))
    modules = handlers[:-1]
    for item in modules:
        assert item.returned.value["point"] == point.name, (identity, report_evidence(result.report))
    return tuple(item.returned.value["member"] for item in modules)


def test_file_add_remove_and_last_member_only_change_one_point(tree):
    """New startup reflects authorized files without changing configuration or siblings."""
    original = tree[1]
    point, sibling = ACTIVE[:2]
    folder = next(p.module_folder for p in original.configuration.hook_points if p.hook_name == point.name)
    owner = start(tree)
    try:
        assert members(owner, point, "initial") == ("zeta",)
        added = folder / "alpha.py"
        added.write_text('def main(*, hook_context):\n    return {"point": hook_context["event_name"], "member": "alpha"}\n')
        assert members(owner, point, "captured") == ("zeta",)
    finally:
        assert owner.close().fully_closed
    owner = start(tree)
    try:
        assert members(owner, point, "added") == ("alpha", "zeta")
        assert members(owner, sibling, "sibling") == ("zeta",)
    finally:
        assert owner.close().fully_closed
    print(f"Deleted test-owned Module: {added}")
    added.unlink()
    owner = start(tree)
    try:
        assert members(owner, point, "removed") == ("zeta",)
    finally:
        assert owner.close().fully_closed
    last = folder / "zeta.py"
    print(f"Deleted test-owned Module: {last}")
    last.unlink()
    owner = start(tree)
    try:
        assert members(owner, point, "empty") == ()
        assert members(owner, sibling, "still-sibling") == ("zeta",)
        assert tree[1] is original
    finally:
        assert owner.close().fully_closed


def test_unauthorized_addition_rejects_whole_point_not_sibling(tree):
    """Discovery never silently skips an unauthorized candidate to publish a partial plan."""
    point, sibling = ACTIVE[:2]
    folder = next(p.module_folder for p in tree[1].configuration.hook_points if p.hook_name == point.name)
    source = folder / "unauthorized.py"
    marker = tree[2] / "unauthorized-execution"
    source.write_text(f"from pathlib import Path\ndef main(*, hook_context):\n    Path({str(marker)!r}).write_text('executed')\n")
    owner = start(tree, unauthorized=source)
    try:
        dispositions = {item.hook_name: item for item in owner.startup_report.dispositions}
        assert dispositions[point.name].kind == "unavailable_preparation_failure"
        assert dispositions[sibling.name].kind == "registered"
        from topsailai.hooks.points.context import SummaryHookAdapter
        result = emit(SummaryHookAdapter(owner.executor), point, "unavailable")
        assert result.report.rejection_reason is not None
        assert not result.report.outcomes
        assert not marker.exists()
        assert members(owner, sibling, "authorized") == ("zeta",)
    finally:
        assert owner.close().fully_closed


def test_missing_directory_is_unavailable_not_empty(tree):
    """The valid empty-directory case does not mask a missing point source root."""
    point = ACTIVE[0]
    folder = next(p.module_folder for p in tree[1].configuration.hook_points if p.hook_name == point.name)
    source = folder / "zeta.py"
    print(f"Deleted test-owned Module: {source}")
    source.unlink()
    print(f"Deleted test-owned directory: {folder}")
    folder.rmdir()
    owner = start(tree)
    try:
        disposition = next(item for item in owner.startup_report.dispositions if item.hook_name == point.name)
        assert disposition.kind == "unavailable_preparation_failure"
    finally:
        assert owner.close().fully_closed
