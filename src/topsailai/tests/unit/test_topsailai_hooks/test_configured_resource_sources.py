"""Focused selected-resource inventory regression tests."""

from pathlib import Path
import sys

import pytest

from topsailai.hooks.configured_preparation import _Operation, _PreparationBudget, _PreparationRejected
from topsailai.hooks.configured_resource_sources import (
    SelectedResourceRejected,
    build_selected_inventory,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.resource_selection_contracts import HookResourceSelection


POLICY = ExecutablePlatformPolicy("posix", (str(Path(sys.executable).resolve()),))


def _script(path: Path, *, valid: bool = True) -> Path:
    """Create one selected script fixture with controlled admission validity."""
    path.write_text(
        f"#!{POLICY.allowed_interpreters[0]}\nprint('ok')\n"
        if valid else "not an executable script\n"
    )
    path.chmod(0o700 if valid else 0o600)
    return path


def _budget() -> _PreparationBudget:
    """Return a bounded preparation budget for one focused inventory."""
    return _PreparationBudget(
        max_scanned_entries=10,
        max_candidates=10,
        max_artifact_bytes=10000,
    )


def test_folder_script_admission_failure_rejects_complete_candidate(tmp_path):
    """A bad folder member cannot be silently dropped from a selected plan."""
    _script(tmp_path / "good")
    _script(tmp_path / "bad", valid=False)

    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(folder=str(tmp_path)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_folder_script_names_are_deterministic(tmp_path):
    """Valid selected scripts are returned in final registered-name order."""
    _script(tmp_path / "z")
    _script(tmp_path / "a")

    inventory = build_selected_inventory(
        HookResourceSelection(folder=str(tmp_path)),
        kind="scripts",
        script_policy=POLICY,
        operation=_Operation(10000, None),
        budget=_budget(),
    )

    assert [entry.registered_name for entry in inventory.entries] == ["a", "z"]


def test_module_file_and_folder_inventory_is_sorted_and_filters_non_modules(tmp_path):
    """Module selections admit supported files and order final registered names."""
    (tmp_path / "z.py").write_text("def main(): return None\n")
    (tmp_path / "a.py").write_text("def main(): return None\n")
    (tmp_path / "__init__.py").write_text("")
    inventory = build_selected_inventory(
        HookResourceSelection(folder=str(tmp_path)), kind="modules",
        operation=_Operation(10000, None), budget=_budget(),
    )
    assert [entry.registered_name for entry in inventory.entries] == ["a", "z"]
    explicit = build_selected_inventory(
        HookResourceSelection(files=(str(tmp_path / "z.py"),)), kind="modules",
        operation=_Operation(10000, None), budget=_budget(),
    )
    assert [entry.registered_name for entry in explicit.entries] == ["z"]


def test_module_explicit_unsupported_file_rejects(tmp_path):
    """Explicit Module selection cannot silently discard an unsupported file."""
    bad = tmp_path / "not-a-module.txt"
    bad.write_text("data")
    with pytest.raises(SelectedResourceRejected, match="discovery_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(bad),)), kind="modules",
            operation=_Operation(10000, None), budget=_budget(),
        )


def test_selected_inventory_rejects_symlink_and_duplicate_physical_identity(tmp_path):
    """Selected resources reject symlink admission and duplicate physical files."""
    source = _script(tmp_path / "source")
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(link),)), kind="scripts", script_policy=POLICY,
            operation=_Operation(10000, None), budget=_budget(),
        )
    hardlink = tmp_path / "hardlink"
    hardlink.hardlink_to(source)
    with pytest.raises(SelectedResourceRejected, match="binding_conflict"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source), str(hardlink))), kind="scripts", script_policy=POLICY,
            operation=_Operation(10000, None), budget=_budget(),
        )


def test_selected_inventory_enforces_scan_and_byte_limits(tmp_path):
    """Selection accounting rejects scan and source-byte budget overflow."""
    source = _script(tmp_path / "run")
    with pytest.raises(SelectedResourceRejected, match="capacity_exceeded"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source),)), kind="scripts", script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_PreparationBudget(max_scanned_entries=0, max_candidates=10, max_artifact_bytes=10000),
        )
    with pytest.raises(SelectedResourceRejected, match="capacity_exceeded"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source),)), kind="scripts", script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_PreparationBudget(max_scanned_entries=10, max_candidates=10, max_artifact_bytes=1),
        )


def test_selected_inventory_observes_cancellation(tmp_path):
    """Cancellation is checked before selected source I/O."""
    event = __import__("threading").Event()
    event.set()
    source = _script(tmp_path / "run")
    with pytest.raises(_PreparationRejected, match="^cancelled$"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source),)), kind="scripts", script_policy=POLICY,
            operation=_Operation(10000, event), budget=_budget(),
        )
