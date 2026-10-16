"""Defensive-branch tests for selected-resource contracts and adapters."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks import configured_resource_preparation as preparation
from topsailai.hooks import configured_resource_sources as sources
from topsailai.hooks.configured_resource_contracts import (
    _safe_environment_pair,
    validate_script_settings,
)
from topsailai.hooks.configured_resource_preparation import (
    _ExecutablePlanRejected,
    _ScriptWork,
    _selected_identity,
    revalidate_selected_batch,
)
from topsailai.hooks.configured_resource_sources import (
    SelectedResourceRejected,
    _canonical_without_symlink_ancestry,
    _selected_paths,
    build_selected_inventory,
)
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy, HookScriptEntry
from topsailai.hooks.resource_selection_contracts import HookResourceSelection


POLICY = ExecutablePlatformPolicy("posix", (str(Path(__import__("sys").executable).resolve()),))


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


def _script(path: Path) -> Path:
    """Create one valid selected script fixture."""
    path.write_text(f"#!{POLICY.allowed_interpreters[0]}\nprint('ok')\n")
    path.chmod(0o700)
    return path


def test_safe_environment_pair_rejects_non_string_inputs() -> None:
    """The environment pair predicate rejects non-string names and values."""
    assert _safe_environment_pair(123, "x") is False
    assert _safe_environment_pair("SAFE", 123) is False


def test_validate_settings_rejects_non_string_platform() -> None:
    """A platform policy carrying a non-string platform is rejected."""
    forged = object.__new__(ExecutablePlatformPolicy)
    object.__setattr__(forged, "platform", 123)
    object.__setattr__(forged, "allowed_interpreters", ())
    object.__setattr__(forged, "native_suffixes", ())
    with pytest.raises(ValueError):
        validate_script_settings(
            forged, HookScriptExecutionOptions(), HookScriptExecutionPolicy(),
            (), (), error="invalid",
        )


def test_validate_settings_rejects_undetachable_platform_collection() -> None:
    """A platform policy whose detached reconstruction fails is rejected."""
    forged = object.__new__(ExecutablePlatformPolicy)
    object.__setattr__(forged, "platform", "posix")
    object.__setattr__(forged, "allowed_interpreters", (123,))
    object.__setattr__(forged, "native_suffixes", ())
    with pytest.raises(ValueError):
        validate_script_settings(
            forged, HookScriptExecutionOptions(), HookScriptExecutionPolicy(),
            (), (), error="invalid",
        )


def test_executable_plan_rejection_rejects_unknown_token() -> None:
    """Only explicit executable-plan rejection tokens are accepted."""
    with pytest.raises(ValueError):
        _ExecutablePlanRejected("not-a-token")


def test_selected_identity_rejects_parent_traversal(tmp_path) -> None:
    """A selected source path containing parent traversal is rejected."""
    source = tmp_path / "run"
    source.write_text("x")
    traversal = tmp_path / "sub" / ".." / "run"
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        _selected_identity(traversal, _operation())


def test_selected_identity_rejects_symlink_ancestry(tmp_path) -> None:
    """A regular source reached through a symlinked ancestor is rejected."""
    real = tmp_path / "real"
    real.mkdir()
    source = real / "run"
    source.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        _selected_identity(link / "run", _operation())


def test_selected_identity_propagates_ancestry_rejection(tmp_path, monkeypatch) -> None:
    """A rejection raised by ancestry inspection propagates unchanged."""
    source = tmp_path / "run"
    source.write_text("x")

    def reject(path, operation):
        """Raise the selected-resource rejection directly."""
        raise SelectedResourceRejected("artifact_rejected")

    monkeypatch.setattr(preparation, "_has_symlink_ancestry", reject)
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        _selected_identity(source, _operation())


def test_selected_identity_wraps_ancestry_os_error(tmp_path, monkeypatch) -> None:
    """An OSError from ancestry inspection becomes an artifact rejection."""
    source = tmp_path / "run"
    source.write_text("x")

    def fail(path, operation):
        """Raise a raw OSError from ancestry inspection."""
        raise OSError("ancestry denied")

    monkeypatch.setattr(preparation, "_has_symlink_ancestry", fail)
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        _selected_identity(source, _operation())


def test_selected_identity_rejects_non_regular_canonical(tmp_path, monkeypatch) -> None:
    """A canonical path resolving to a non-regular file is rejected."""
    source = tmp_path / "run"
    source.write_text("x")
    monkeypatch.setattr(preparation, "_has_symlink_ancestry", lambda path, op: False)
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: tmp_path)
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        _selected_identity(source, _operation())


def test_revalidate_selected_batch_accepts_unchanged_source(tmp_path) -> None:
    """An unchanged selected source passes revalidation."""
    from topsailai.hooks.artifact_validation import file_identity
    from topsailai.hooks.configured_resource_sources import SelectedResourceEntry

    source = tmp_path / "run"
    source.write_text("x")
    selected = SelectedResourceEntry(
        "script", "run", source, tmp_path, file_identity(source.stat())
    )
    work = _ScriptWork(0, SimpleNamespace(), HookScriptEntry(source, "run", "run"), selected)
    assert revalidate_selected_batch((work,), _operation()) == (work,)


def test_selected_point_work_rejects_shared_physical_identity(tmp_path) -> None:
    """A file admitted as both Module and Script is rejected as a conflict."""
    from topsailai.hooks.configured_resource_contracts import ConfiguredScriptSettings
    from topsailai.hooks.configured_resource_preparation import selected_point_work

    source = tmp_path / "dual.py"
    source.write_text(
        f"#!{POLICY.allowed_interpreters[0]}\ndef main():\n    return None\n"
    )
    source.chmod(0o700)
    hardlink = tmp_path / "dual-link"
    hardlink.hardlink_to(source)
    point = SimpleNamespace(
        resources=SimpleNamespace(
            selection=SimpleNamespace(
                modules=HookResourceSelection(files=(str(source),)),
                scripts=HookResourceSelection(files=(str(hardlink),)),
            ),
            script_settings=ConfiguredScriptSettings(POLICY),
        )
    )
    with pytest.raises(SelectedResourceRejected, match="binding_conflict"):
        selected_point_work(point, 0, _operation(), _budget())


def test_inventory_rejects_symlink_ancestry_for_regular_file(tmp_path) -> None:
    """A regular file reached through a symlinked ancestor is rejected."""
    real = tmp_path / "real"
    real.mkdir()
    source = real / "observer.py"
    source.write_text("def main(): return None\n")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(link / "observer.py"),)),
            kind="modules",
            operation=_operation(),
            budget=_budget(),
        )


def test_inventory_rejects_non_regular_canonical(tmp_path, monkeypatch) -> None:
    """A canonical path resolving to a non-regular file is rejected."""
    source = tmp_path / "observer.py"
    source.write_text("def main(): return None\n")
    monkeypatch.setattr(sources, "_has_symlink_ancestry", lambda path, op: False)
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: tmp_path)
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source),)),
            kind="modules",
            operation=_operation(),
            budget=_budget(),
        )


def test_selected_paths_returns_empty_for_absent_selector() -> None:
    """A selector with neither files nor folder yields no paths."""
    selection = SimpleNamespace(files=(), folder=None)
    assert _selected_paths(selection, _operation(), _budget()) == ((), Path("/"))


def test_selected_paths_rejects_relative_file_path() -> None:
    """A relative explicit file path is rejected as non-absolute."""
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _selected_paths(
            HookResourceSelection(files=("relative.py",)), _operation(), _budget()
        )


def test_selected_paths_rejects_root_resolution_failure(tmp_path, monkeypatch) -> None:
    """A failure resolving the selection root is rejected."""
    source = tmp_path / "observer.py"
    source.write_text("def main(): return None\n")

    def fail(self, strict=False):
        """Reject root resolution."""
        raise OSError("resolve denied")

    monkeypatch.setattr(Path, "resolve", fail)
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _selected_paths(
            HookResourceSelection(files=(str(source),)), _operation(), _budget()
        )


def test_selected_paths_rejects_symlinked_folder_ancestor(tmp_path) -> None:
    """A real folder reached through a symlinked ancestor is rejected."""
    real = tmp_path / "real"
    nested = real / "nested"
    nested.mkdir(parents=True)
    _script(nested / "run")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _selected_paths(
            HookResourceSelection(folder=str(link / "nested")), _operation(), _budget()
        )


def test_canonical_without_symlink_ancestry_wraps_resolution_failure(tmp_path, monkeypatch) -> None:
    """A resolution failure after ancestry inspection returns None."""
    source = tmp_path / "observer.py"
    source.write_text("def main(): return None\n")
    monkeypatch.setattr(sources, "_has_symlink_ancestry", lambda path, op: False)

    def fail(self, strict=False):
        """Reject canonical resolution."""
        raise OSError("resolve denied")

    monkeypatch.setattr(Path, "resolve", fail)
    assert _canonical_without_symlink_ancestry(source, _operation()) is None
