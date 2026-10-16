"""Behavioral tests for selected-resource preparation adapters."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, EventDefinition, HookSettings
from topsailai.hooks import configured_preparation as preparation_module
from topsailai.hooks.configured_preparation import _PreparationRejected, prepare_private
from topsailai.hooks.configured_resource_contracts import ConfiguredScriptSettings, ConfiguredSelectedResources
from topsailai.hooks.configured_resource_preparation import (
    _ModuleWork,
    _ScriptWork,
    _capture_batches,
    build_executable_plan,
    revalidate_selected_batch,
    selected_point_work,
    validate_selected_capture,
)
from topsailai.hooks.configured_resource_sources import SelectedResourceEntry, SelectedResourceRejected
from topsailai.hooks.hook_script_discovery import HookScriptEntry
from topsailai.hooks.module_discovery import ModuleCandidate
from topsailai.hooks.resource_selection_contracts import HookPointResourceSelection, HookResourceSelection
from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions, HookScriptExecutionPolicy
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from tests.unit.test_topsailai_hooks import test_configured_preparation as preparation_helpers
secure_test_root = preparation_helpers.secure_test_root


def _entry(path: Path, name: str, kind: str = "script") -> SelectedResourceEntry:
    """Build a selected entry with filesystem identity evidence."""
    status = path.stat()
    from topsailai.hooks.artifact_validation import file_identity
    return SelectedResourceEntry(kind, name, path, path.parent, file_identity(status))


def test_capture_batches_preserve_point_groups_and_split_duplicate_paths(tmp_path):
    """Selected batches remain point-complete and avoid repeated physical paths."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_text("x")
    second.write_text("y")
    point = SimpleNamespace()
    a = _ScriptWork(0, point, HookScriptEntry(first, "first", "first"), _entry(first, "first"))
    b = _ScriptWork(1, point, HookScriptEntry(first, "first", "first"), _entry(first, "first"))
    c = _ScriptWork(1, point, HookScriptEntry(second, "second", "second"), _entry(second, "second"))
    batches = _capture_batches((a, b, c))
    assert [[work.entry.final_registered_name for work in batch] for batch in batches] == [["first"], ["first", "second"]]


def test_validate_selected_capture_rejects_wrong_identity_and_accepts_match(tmp_path):
    """Capture correlation requires kind, logical name, source path, and identity."""
    source = tmp_path / "run"
    source.write_text("x")
    selected = _entry(source, "run")
    work = _ScriptWork(0, SimpleNamespace(), HookScriptEntry(source, "run", "run"), selected)
    good = SimpleNamespace(kind="script", logical_name="run", validation=SimpleNamespace(source_path=source, identity=selected.identity))
    validate_selected_capture(work, good)
    bad = SimpleNamespace(kind="script", logical_name="other", validation=SimpleNamespace(source_path=source, identity=selected.identity))
    with pytest.raises(SelectedResourceRejected, match="^artifact_rejected$"):
        validate_selected_capture(work, bad)


def test_revalidate_selected_batch_detects_replacement(tmp_path):
    """Source replacement between inventory and capture is rejected."""
    source = tmp_path / "run"
    source.write_text("before")
    selected = _entry(source, "run")
    work = _ScriptWork(0, SimpleNamespace(), HookScriptEntry(source, "run", "run"), selected)
    source.unlink()
    source.write_text("after")
    operation = SimpleNamespace(checkpoint=lambda: None)
    with pytest.raises(SelectedResourceRejected, match="^artifact_rejected$"):
        revalidate_selected_batch((work,), operation)


def test_selected_point_work_rejects_unadmitted_script_before_conflict_check(tmp_path):
    """Script admission rejects an invalid hardlink before physical conflict checking."""
    from topsailai.hooks.configured_resource_contracts import ConfiguredScriptSettings
    from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
    source = tmp_path / "module.py"
    source.write_text(f"#!{__import__('sys').executable}\ndef main(): return None\n")
    source.chmod(0o700)
    script = tmp_path / "run"
    script.hardlink_to(source)
    policy = ExecutablePlatformPolicy("posix", (str(Path(__import__('sys').executable).resolve()),))
    resources = ConfiguredScriptSettings(policy)
    selected = SimpleNamespace(
        selection=HookPointResourceSelection(
            modules=HookResourceSelection(files=(str(source),)),
            scripts=HookResourceSelection(files=(str(script),)),
        ),
        script_settings=resources,
    )
    point = SimpleNamespace(resources=selected)
    operation = SimpleNamespace(checkpoint=lambda: None)
    budget = SimpleNamespace(add_scan=lambda count=1: None, add_candidate=lambda count=1: None, add_source_bytes=lambda count: None)
    with pytest.raises(SelectedResourceRejected, match="^trust_rejected$"):
        selected_point_work(point, 0, operation, budget)


def test_capture_batches_rejects_oversized_selected_point():
    """A selected Hook Point cannot be split beyond its bounded batch size."""
    point = SimpleNamespace()
    selected = SimpleNamespace(source_path=Path("/tmp/selected"), identity=SimpleNamespace(device=1, inode=1))
    works = tuple(
        _ScriptWork(0, point, HookScriptEntry(Path(f"/tmp/script-{index}"), str(index), str(index)), selected)
        for index in range(129)
    )
    with pytest.raises(SelectedResourceRejected, match="^capacity_exceeded$"):
        _capture_batches(works)


def test_script_settings_supports_legacy_point_and_selected_point():
    """The adapter preserves both selected and legacy Script settings."""
    from topsailai.hooks.configured_resource_preparation import script_settings
    selected_point = SimpleNamespace(resources=SimpleNamespace(script_settings="selected"))
    legacy_point = SimpleNamespace(resources=None, script="legacy")
    assert script_settings(selected_point) == "selected"
    assert script_settings(legacy_point) == "legacy"


def test_validate_selected_capture_rejects_wrong_kind(tmp_path):
    """Capture correlation rejects a Script entry carrying a Module kind."""
    source = tmp_path / "run"
    source.write_text("x")
    selected = _entry(source, "run")
    work = _ScriptWork(0, SimpleNamespace(), HookScriptEntry(source, "run", "run"), selected)
    captured = SimpleNamespace(kind="python_source", logical_name="run", validation=SimpleNamespace(source_path=source, identity=selected.identity))
    with pytest.raises(SelectedResourceRejected, match="^artifact_rejected$"):
        validate_selected_capture(work, captured)
def test_selected_resources_complete_executable_preparation(secure_test_root):
    """Selected Module and Script sources complete real executable preparation."""
    sources, runtime_root, _ = secure_test_root
    executable = Path(__import__('sys').executable).resolve(strict=True)
    module_source = sources / "observer.py"
    module_source.write_text("def main(): return None\n")
    script_source = sources / "run"
    script_source.write_text(f"#!{executable}\nprint('run')\n")
    script_source.chmod(0o700)
    policy = ExecutablePlatformPolicy("posix", (str(executable),))
    selected = ConfiguredSelectedResources(
        HookPointResourceSelection(
            modules=HookResourceSelection(files=(str(module_source),)),
            scripts=HookResourceSelection(files=(str(script_source),)),
        ),
        ConfiguredScriptSettings(
            policy, HookScriptExecutionOptions(), HookScriptExecutionPolicy()
        ),
    )
    runtime, scope = preparation_helpers._runtime(sources, runtime_root)
    trust = runtime.configured_trust
    runtime._configured_trust = type(trust)(
        trust.source_roots,
        closure_assertions=(
            preparation_helpers._assertion(module_source, "observer", "python_source"),
            preparation_helpers._assertion(script_source, "run", "script"),
        ),
        python_runtime=trust.python_runtime,
        allowed_interpreters=(executable,),
    )
    point = ConfiguredHookPoint(
        "hook_alpha", EventDefinition("test.hook_alpha", 1), resources=selected,
    )
    try:
        image = prepare_private(
            runtime, ConfiguredHooks((point,), HookSettings()), scope, _executable=True
        )
        assert image.accepted, image.errors
        plan = image.plans[0].executable
        assert [item.source.logical_name for item in plan.modules] == ["observer"]
        assert len(plan.default_script_hook.scripts) == 1
        assert plan.default_script_hook.configured is True
        assert plan.default_script_hook.scripts[0].identity.name == "run"
        assert image.close().accepted
        assert not image.cleanup_debts()
    finally:
        runtime.close()
