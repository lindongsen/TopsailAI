"""Behavioral tests for selected-resource preparation adapters and executable plans."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks.configured_resource_preparation import (
    _ExecutablePlanRejected,
    _ModuleWork,
    _ScriptWork,
    _capture_batches,
    _selected_identity,
    _work_source_path,
    build_executable_plan,
    revalidate_selected_batch,
    script_selection_configured,
    script_settings,
    selected_point_work,
    validate_selected_capture,
)
from topsailai.hooks.configured_resource_sources import (
    SelectedResourceEntry,
    SelectedResourceRejected,
)
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy, HookScriptEntry
from topsailai.hooks.module_discovery import ModuleCandidate
from topsailai.hooks.resource_selection_contracts import (
    HookPointResourceSelection,
    HookResourceSelection,
)


def _entry(path: Path, name: str, kind: str = "script") -> SelectedResourceEntry:
    """Build a selected entry with real filesystem identity evidence."""
    from topsailai.hooks.artifact_validation import file_identity

    return SelectedResourceEntry(kind, name, path, path.parent, file_identity(path.stat()))


def _operation():
    """Return a permissive preparation operation double."""
    return SimpleNamespace(checkpoint=lambda: None)


def _budget():
    """Return a permissive preparation budget double."""
    return SimpleNamespace(
        add_scan=lambda count=1: None,
        add_candidate=lambda count=1: None,
        add_source_bytes=lambda count: None,
    )


def _captured(work, index, lease_identity, *, kind, logical_name, source_path,
              relative_path=None, content="a" * 64, deployment="b" * 64,
              captured_path=None):
    """Build one captured-work double correlated with a lease entry."""
    relative = relative_path or f"entry-{index:06d}/{source_path.name}"
    entry = SimpleNamespace(
        index=index,
        kind=kind,
        logical_name=logical_name,
        relative_path=relative,
        content_sha256=content,
        validation=SimpleNamespace(
            source_path=source_path, deployment_sha256=deployment
        ),
    )
    lease = SimpleNamespace(identity=lease_identity, entries=(entry,))
    return SimpleNamespace(
        work=work,
        lease=lease,
        entry_index=index,
        captured_path=captured_path or (Path("/sealed") / relative),
    )


def test_executable_plan_rejects_oversized_and_mixed_lease_inventory(tmp_path):
    """Executable plan construction rejects oversized or multi-lease inventories."""
    point = SimpleNamespace(hook_name="hook__context__before__summary_generate_user2agent")
    oversized = tuple(
        SimpleNamespace(lease=SimpleNamespace(identity="one")) for _ in range(129)
    )
    with pytest.raises(_ExecutablePlanRejected, match="binding_conflict"):
        build_executable_plan(point, oversized)
    mixed = (
        SimpleNamespace(lease=SimpleNamespace(identity="one")),
        SimpleNamespace(lease=SimpleNamespace(identity="two")),
    )
    with pytest.raises(_ExecutablePlanRejected, match="binding_conflict"):
        build_executable_plan(point, mixed)


def test_executable_plan_rejects_uncorrelated_capture_entry(tmp_path):
    """A captured entry whose kind or name disagrees with its request is rejected."""
    source = tmp_path / "run"
    source.write_text("x")
    selected = _entry(source, "run")
    work = _ScriptWork(0, SimpleNamespace(), HookScriptEntry(source, "run", "run"), selected)
    captured = _captured(
        work, 0, "a" * 64, kind="python_source", logical_name="run", source_path=source
    )
    point = SimpleNamespace(
        hook_name="hook__context__before__summary_generate_user2agent",
        resources=None,
        script=SimpleNamespace(platform_policy=ExecutablePlatformPolicy("posix")),
    )
    with pytest.raises(_ExecutablePlanRejected, match="artifact_rejected"):
        build_executable_plan(point, (captured,))


def test_executable_plan_builds_module_and_script_records(tmp_path):
    """A correlated inventory yields one complete executable plan."""
    module_source = tmp_path / "observer.py"
    module_source.write_text("def main(): return None\n")
    script_source = tmp_path / "run"
    script_source.write_text("#!/bin/sh\nexit 0\n")
    module_work = _ModuleWork(
        0,
        SimpleNamespace(),
        tmp_path,
        ModuleCandidate("observer", module_source, "python_source"),
        _entry(module_source, "observer", "python_source"),
    )
    script_work = _ScriptWork(
        0, SimpleNamespace(), HookScriptEntry(script_source, "run", "run"),
        _entry(script_source, "run"),
    )
    module_captured = _captured(
        module_work, 0, "a" * 64, kind="python_source", logical_name="observer",
        source_path=module_source,
    )
    script_captured = _captured(
        script_work, 1, "a" * 64, kind="script", logical_name="run",
        source_path=script_source,
    )
    shared_lease = SimpleNamespace(
        identity="a" * 64,
        entries=(module_captured.lease.entries[0], script_captured.lease.entries[0]),
    )
    module_captured = SimpleNamespace(
        work=module_work, lease=shared_lease, entry_index=0,
        captured_path=Path("/sealed/entry-000000/observer.py"),
    )
    script_captured = SimpleNamespace(
        work=script_work, lease=shared_lease, entry_index=1,
        captured_path=Path("/sealed/entry-000001/run"),
    )
    point = SimpleNamespace(
        hook_name="hook__context__before__summary_generate_user2agent",
        module_args=(),
        module_kwargs={},
        inject_hook_context=False,
        resources=SimpleNamespace(
            selection=HookPointResourceSelection(
                scripts=HookResourceSelection(files=("/tmp/run",))
            ),
            script_settings=SimpleNamespace(
                platform_policy=ExecutablePlatformPolicy("posix"),
                options=HookScriptExecutionOptions(),
                policy=HookScriptExecutionPolicy(),
            )
        ),
    )
    plan = build_executable_plan(point, (module_captured, script_captured))
    assert [module.source.logical_name for module in plan.modules] == ["observer"]
    assert [script.logical_name for script in plan.default_script_hook.scripts] == ["run"]
    assert plan.default_script_hook.configured is True


def test_selected_identity_rejects_symlink_and_missing_source(tmp_path):
    """Selected identity re-observation rejects symlinks and missing sources."""
    source = tmp_path / "run"
    source.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        _selected_identity(link, _operation())
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        _selected_identity(tmp_path / "missing", _operation())


def test_revalidate_selected_batch_skips_unselected_work(tmp_path):
    """Legacy work without selection evidence is not revalidated."""
    work = _ScriptWork(0, SimpleNamespace(), HookScriptEntry(tmp_path / "run", "run", "run"))
    assert revalidate_selected_batch((work,), _operation()) == (work,)


def test_validate_selected_capture_accepts_module_match(tmp_path):
    """A Module capture entry correlates against its selected source evidence."""
    source = tmp_path / "observer.py"
    source.write_text("def main(): return None\n")
    selected = _entry(source, "observer", "python_source")
    work = _ModuleWork(
        0, SimpleNamespace(), tmp_path,
        ModuleCandidate("observer", source, "python_source"), selected,
    )
    captured = SimpleNamespace(
        kind="python_source",
        logical_name="observer",
        validation=SimpleNamespace(source_path=source, identity=selected.identity),
    )
    validate_selected_capture(work, captured)


def test_capture_batches_returns_empty_for_no_work():
    """An empty work sequence yields no capture batches."""
    assert _capture_batches(()) == ()


def test_capture_batches_legacy_path_splits_at_128():
    """Legacy work without selection is packed into bounded 128-item batches."""
    works = tuple(
        _ScriptWork(0, SimpleNamespace(), HookScriptEntry(Path(f"/tmp/s{index}"), str(index), str(index)))
        for index in range(129)
    )
    batches = _capture_batches(works)
    assert [len(batch) for batch in batches] == [128, 1]


def test_capture_batches_rejects_more_than_eight_selected_batches(tmp_path):
    """Selected batches beyond the shard cap are rejected."""
    source = tmp_path / "shared"
    source.write_text("x")
    selected = _entry(source, "shared")
    works = tuple(
        _ScriptWork(
            index,
            SimpleNamespace(),
            HookScriptEntry(source, "shared", "shared"),
            selected,
        )
        for index in range(9)
    )
    with pytest.raises(SelectedResourceRejected, match="capacity_exceeded"):
        _capture_batches(works)


def test_work_source_path_returns_module_and_script_paths(tmp_path):
    """Work source paths resolve for both Module and Script records."""
    module_source = tmp_path / "observer.py"
    script_source = tmp_path / "run"
    module_work = _ModuleWork(
        0, SimpleNamespace(), tmp_path,
        ModuleCandidate("observer", module_source, "python_source"),
    )
    script_work = _ScriptWork(0, SimpleNamespace(), HookScriptEntry(script_source, "run", "run"))
    assert _work_source_path(module_work) == module_source
    assert _work_source_path(script_work) == script_source


def test_selected_point_work_returns_empty_without_resources():
    """A point without selected resources produces no work."""
    point = SimpleNamespace(resources=None)
    assert selected_point_work(point, 0, _operation(), _budget()) == ()


def test_selected_point_work_builds_module_and_script_work(tmp_path):
    """Selected Module and Script inventories become correlated work records."""
    from topsailai.hooks.configured_resource_contracts import ConfiguredScriptSettings

    module_source = tmp_path / "observer.py"
    module_source.write_text("def main(): return None\n")
    script_source = tmp_path / "run"
    script_source.write_text(f"#!{Path(__import__('sys').executable).resolve()}\nprint('ok')\n")
    script_source.chmod(0o700)
    policy = ExecutablePlatformPolicy("posix", (str(Path(__import__("sys").executable).resolve()),))
    point = SimpleNamespace(
        resources=SimpleNamespace(
            selection=HookPointResourceSelection(
                modules=HookResourceSelection(files=(str(module_source),)),
                scripts=HookResourceSelection(files=(str(script_source),)),
            ),
            script_settings=ConfiguredScriptSettings(policy),
        )
    )
    works = selected_point_work(point, 0, _operation(), _budget())
    assert [type(work).__name__ for work in works] == ["_ModuleWork", "_ScriptWork"]
    assert works[0].candidate.logical_name == "observer"
    assert works[1].entry.final_registered_name == "run"


def test_script_selection_configured_distinguishes_selected_and_legacy():
    """Script configuration presence is reported for selected and legacy points."""
    selected = SimpleNamespace(
        resources=SimpleNamespace(selection=HookPointResourceSelection(scripts=HookResourceSelection(files=("/tmp/run",))))
    )
    selected_modules_only = SimpleNamespace(
        resources=SimpleNamespace(selection=HookPointResourceSelection(modules=HookResourceSelection(files=("/tmp/m.py",))))
    )
    legacy = SimpleNamespace(resources=None, script=object())
    legacy_none = SimpleNamespace(resources=None, script=None)
    assert script_selection_configured(selected) is True
    assert script_selection_configured(selected_modules_only) is False
    assert script_selection_configured(legacy) is True
    assert script_selection_configured(legacy_none) is False


def test_script_settings_returns_none_for_legacy_point_without_script():
    """A legacy point without a Script yields no execution settings."""
    assert script_settings(SimpleNamespace(resources=None, script=None)) is None


def test_point_plan_rejection_preserves_selected_resource_error_type() -> None:
    """Selected plans translate executable rejection to the public selected token."""
    import topsailai.hooks.configured_preparation as preparation
    point = SimpleNamespace(resources=object())
    result = preparation._point_plan_rejection(point, "binding_conflict")
    assert isinstance(result, SelectedResourceRejected)
    assert str(result) == "binding_conflict"


def test_build_executable_plan_translates_selected_rejection() -> None:
    """The orchestration adapter preserves selected-resource rejection identity."""
    import topsailai.hooks.configured_preparation as preparation
    point = SimpleNamespace(resources=SimpleNamespace(script_settings=None))
    with pytest.raises(SelectedResourceRejected, match="binding_conflict"):
        preparation._build_executable_plan(point, tuple(SimpleNamespace(lease=SimpleNamespace(identity=str(i))) for i in range(129)))
