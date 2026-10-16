"""Boundary and failure-path tests for selected-resource inventory construction."""

import os
import stat
from pathlib import Path

import pytest

from topsailai.hooks.configured_preparation import _Operation, _PreparationBudget
from topsailai.hooks.configured_resource_sources import (
    SelectedResourceRejected,
    _canonical_without_symlink_ancestry,
    _has_symlink_ancestry,
    _module_name,
    _observe,
    _selected_paths,
    build_selected_inventory,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.resource_selection_contracts import HookResourceSelection


POLICY = ExecutablePlatformPolicy("posix", (str(Path(__import__("sys").executable).resolve()),))


def _budget(**overrides):
    """Return a bounded preparation budget with optional overrides."""
    values = dict(max_scanned_entries=100, max_candidates=100, max_artifact_bytes=100000)
    values.update(overrides)
    return _PreparationBudget(**values)


def _script(path: Path) -> Path:
    """Create one valid selected script fixture."""
    path.write_text(f"#!{POLICY.allowed_interpreters[0]}\nprint('ok')\n")
    path.chmod(0o700)
    return path


def test_rejection_token_must_be_known() -> None:
    """Only stable public-safe rejection tokens are accepted."""
    with pytest.raises(ValueError):
        SelectedResourceRejected("not-a-token")


def test_inventory_returns_empty_for_absent_selection() -> None:
    """An absent selection yields an empty inventory without I/O."""
    inventory = build_selected_inventory(
        None, kind="modules", operation=_Operation(10000, None), budget=_budget()
    )
    assert inventory.entries == ()


def test_inventory_rejects_wrong_selection_type() -> None:
    """A non-contract selection is rejected as a discovery failure."""
    with pytest.raises(SelectedResourceRejected, match="discovery_rejected"):
        build_selected_inventory(
            object(), kind="modules", operation=_Operation(10000, None), budget=_budget()
        )


def test_script_inventory_requires_platform_policy(tmp_path) -> None:
    """Script selection without an exact platform policy is rejected."""
    source = _script(tmp_path / "run")
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source),)),
            kind="scripts",
            script_policy=None,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_inventory_rejects_non_regular_and_missing_sources(tmp_path) -> None:
    """Missing and non-regular selected sources are rejected."""
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(tmp_path / "missing.py"),)),
            kind="modules",
            operation=_Operation(10000, None),
            budget=_budget(),
        )
    directory = tmp_path / "folder"
    directory.mkdir()
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(directory),)),
            kind="modules",
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_inventory_rejects_source_replacement_after_admission(tmp_path, monkeypatch) -> None:
    """A Script replaced between admission and re-observation is rejected."""
    source = _script(tmp_path / "run")
    from topsailai.hooks import configured_resource_sources as sources

    original = sources.file_identity
    calls = {"count": 0}

    def flaky(status):
        """Return a mismatching identity on the second observation."""
        calls["count"] += 1
        identity = original(status)
        if calls["count"] == 2:
            from dataclasses import replace

            return replace(identity, size=identity.size + 1)
        return identity

    monkeypatch.setattr(sources, "file_identity", flaky)
    with pytest.raises(SelectedResourceRejected, match="artifact_rejected"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source),)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_selected_paths_reject_parent_traversal(tmp_path) -> None:
    """Explicit file and folder selections reject parent traversal."""
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _selected_paths(
            HookResourceSelection(files=(str(tmp_path / ".." / "escape.py"),)),
            _Operation(10000, None),
            _budget(),
        )
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _selected_paths(
            HookResourceSelection(folder=str(tmp_path / ".." / "escape")),
            _Operation(10000, None),
            _budget(),
        )


def test_selected_paths_reject_non_directory_folder(tmp_path) -> None:
    """A folder selection pointing at a regular file is rejected."""
    source = tmp_path / "file"
    source.write_text("x")
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _selected_paths(
            HookResourceSelection(folder=str(source)),
            _Operation(10000, None),
            _budget(),
        )


def test_folder_selection_skips_subdirectories(tmp_path) -> None:
    """Direct-child folder selection ignores nested directories."""
    _script(tmp_path / "run")
    (tmp_path / "nested").mkdir()
    inventory = build_selected_inventory(
        HookResourceSelection(folder=str(tmp_path)),
        kind="scripts",
        script_policy=POLICY,
        operation=_Operation(10000, None),
        budget=_budget(),
    )
    assert [entry.registered_name for entry in inventory.entries] == ["run"]


def test_folder_selection_rejects_symlink_child(tmp_path) -> None:
    """A symlinked direct child is rejected rather than followed."""
    source = _script(tmp_path / "run")
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(folder=str(tmp_path)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_folder_selection_rejects_child_stat_failure(tmp_path, monkeypatch) -> None:
    """A child stat failure during folder scanning is rejected."""
    _script(tmp_path / "run")
    real_scandir = os.scandir

    class FailingEntry:
        """Wrap one directory entry whose stat raises an OSError."""

        def __init__(self, entry):
            self._entry = entry
            self.name = entry.name

        def stat(self, *, follow_symlinks=True):
            raise OSError("stat denied")

    class FailingIterator:
        """Yield wrapped entries and expose a close method."""

        def __init__(self, iterator):
            self._iterator = iterator

        def __iter__(self):
            for entry in self._iterator:
                yield FailingEntry(entry)

        def close(self):
            self._iterator.close()

    monkeypatch.setattr(
        "topsailai.hooks.configured_resource_sources.os.scandir",
        lambda path: FailingIterator(real_scandir(path)),
    )
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(folder=str(tmp_path)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_folder_selection_rejects_iterator_close_failure(tmp_path, monkeypatch) -> None:
    """A failure while closing the folder iterator is rejected."""
    _script(tmp_path / "run")
    real_scandir = os.scandir

    class CloseFailingIterator:
        """Wrap a real iterator but fail on close."""

        def __init__(self, iterator):
            self._iterator = iterator

        def __iter__(self):
            return iter(self._iterator)

        def close(self):
            raise OSError("close denied")

    monkeypatch.setattr(
        "topsailai.hooks.configured_resource_sources.os.scandir",
        lambda path: CloseFailingIterator(real_scandir(path)),
    )
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(folder=str(tmp_path)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_folder_selection_rejects_scandir_failure(tmp_path, monkeypatch) -> None:
    """A failure opening the folder iterator is rejected."""
    def deny(path):
        """Reject directory enumeration."""
        raise OSError("scandir denied")

    monkeypatch.setattr(
        "topsailai.hooks.configured_resource_sources.os.scandir", deny
    )
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(folder=str(tmp_path)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_folder_selection_rejects_symlink_ancestry(tmp_path) -> None:
    """A folder reached through a symlinked ancestor is rejected."""
    real = tmp_path / "real"
    real.mkdir()
    _script(real / "run")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        build_selected_inventory(
            HookResourceSelection(folder=str(link)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_canonical_without_symlink_ancestry_returns_none_for_symlink(tmp_path) -> None:
    """Canonicalization returns None when the path itself is a symbolic link."""
    real = tmp_path / "real"
    real.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert _canonical_without_symlink_ancestry(link, _Operation(10000, None)) is None

def test_canonical_without_symlink_ancestry_rejects_missing_path(tmp_path) -> None:
    """Canonicalization rejects a missing path through its ancestry observation."""
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _canonical_without_symlink_ancestry(tmp_path / "missing", _Operation(10000, None))


def test_has_symlink_ancestry_detects_link(tmp_path) -> None:
    """Symlink ancestry detection reports a linked ancestor."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "child").write_text("x")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert _has_symlink_ancestry(link / "child", _Operation(10000, None)) is True
    assert _has_symlink_ancestry(real / "child", _Operation(10000, None)) is False

def test_observe_rejects_missing_path(tmp_path) -> None:
    """Observation of a missing path raises a trust rejection."""
    with pytest.raises(SelectedResourceRejected, match="trust_rejected"):
        _observe(tmp_path / "missing", _Operation(10000, None))


def test_module_name_rejects_init_and_non_identifier() -> None:
    """Module naming rejects __init__ and non-identifier stems."""
    assert _module_name("__init__.py") == (None, None)
    assert _module_name("not-a-module.py") == (None, None)
    assert _module_name("observer.py") == ("observer", "python_source")


def test_folder_module_selection_skips_unsupported_children(tmp_path) -> None:
    """Folder Module selection silently skips unsupported direct children."""
    (tmp_path / "observer.py").write_text("def main(): return None\n")
    (tmp_path / "notes.txt").write_text("data")
    inventory = build_selected_inventory(
        HookResourceSelection(folder=str(tmp_path)),
        kind="modules",
        operation=_Operation(10000, None),
        budget=_budget(),
    )
    assert [entry.registered_name for entry in inventory.entries] == ["observer"]


def test_inventory_rejects_duplicate_registered_names(tmp_path) -> None:
    """Two distinct files resolving to the same registered name are rejected."""
    first = tmp_path / "a" / "observer.py"
    second = tmp_path / "b" / "observer.py"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("def main(): return None\n")
    second.write_text("def main(): return None\n")
    with pytest.raises(SelectedResourceRejected, match="binding_conflict"):
        build_selected_inventory(
            HookResourceSelection(files=(str(first), str(second))),
            kind="modules",
            operation=_Operation(10000, None),
            budget=_budget(),
        )


def test_inventory_rejects_candidate_limit(tmp_path) -> None:
    """Candidate accounting rejects overflow of the shared budget."""
    source = _script(tmp_path / "run")
    with pytest.raises(SelectedResourceRejected, match="capacity_exceeded"):
        build_selected_inventory(
            HookResourceSelection(files=(str(source),)),
            kind="scripts",
            script_policy=POLICY,
            operation=_Operation(10000, None),
            budget=_budget(max_candidates=0),
        )
