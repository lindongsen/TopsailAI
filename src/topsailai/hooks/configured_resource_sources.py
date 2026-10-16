"""Strict selected-resource inventory construction for configured Hook Points."""

from __future__ import annotations

import importlib.machinery
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from topsailai.hooks.artifact_contracts import ArtifactFileIdentity
from topsailai.hooks.artifact_validation import file_identity
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy, discover_hook_script_entries
from topsailai.hooks.module_discovery import _logical_name
from topsailai.hooks.resource_selection_contracts import HookResourceSelection

ResourceKind = Literal["python_source", "python_extension", "script"]


@dataclass(frozen=True, slots=True)
class SelectedResourceEntry:
    """Record one selected source and its observation evidence."""

    kind: ResourceKind
    registered_name: str
    source_path: Path
    selection_root: Path
    identity: ArtifactFileIdentity


@dataclass(frozen=True, slots=True)
class SelectedResourceInventory:
    """Contain one complete immutable selected source inventory."""

    entries: tuple[SelectedResourceEntry, ...] = ()


class SelectedResourceRejected(ValueError):
    """Carry one validated selected-resource rejection token."""

    _TOKENS = frozenset({
        "trust_rejected", "discovery_rejected", "binding_conflict",
        "artifact_rejected", "capacity_exceeded", "prepare_timeout",
        "cancelled", "unsupported_platform",
    })

    def __init__(self, token: str) -> None:
        """Store only a stable public-safe classification."""
        if token not in self._TOKENS:
            raise ValueError("invalid selected-resource rejection token")
        super().__init__(token)
        self.token = token


_MODULE_SUFFIXES = tuple(sorted(importlib.machinery.EXTENSION_SUFFIXES, key=len, reverse=True))


def build_selected_inventory(
    selection: HookResourceSelection | None,
    *,
    kind: Literal["modules", "scripts"],
    script_policy: ExecutablePlatformPolicy | None = None,
    operation,
    budget,
) -> SelectedResourceInventory:
    """Build one strict direct-selection inventory without importing sources."""
    if selection is None:
        return SelectedResourceInventory()
    if type(selection) is not HookResourceSelection:
        raise SelectedResourceRejected("discovery_rejected")
    if kind == "scripts" and type(script_policy) is not ExecutablePlatformPolicy:
        raise SelectedResourceRejected("trust_rejected")
    paths, root = _selected_paths(selection, operation, budget)
    entries = []
    seen_names: set[str] = set()
    seen_identity: set[tuple[int, int]] = set()
    for path in paths:
        _checkpoint(operation)
        observed = _observe_regular(path, operation)
        canonical = _canonical_without_symlink_ancestry(path, operation)
        if canonical is None:
            raise SelectedResourceRejected("trust_rejected")
        canonical_status = _observe(canonical, operation)
        if not stat.S_ISREG(canonical_status.st_mode):
            raise SelectedResourceRejected("trust_rejected")
        if kind == "modules":
            name, entry_kind = _module_name(path.name)
            if name is None or entry_kind is None:
                if selection.files:
                    raise SelectedResourceRejected("discovery_rejected")
                continue
            registered_name = name
        else:
            result = discover_hook_script_entries(
                path, script_policy, checkpoint=operation.checkpoint
            )
            _checkpoint(operation)
            if not result.accepted or len(result.entries) != 1:
                raise SelectedResourceRejected("trust_rejected")
            after_admission = file_identity(_observe_regular(path, operation))
            if after_admission != file_identity(observed):
                raise SelectedResourceRejected("artifact_rejected")
            registered_name = result.entries[0].final_registered_name
            entry_kind = "script"
        _checkpoint(operation)
        identity = file_identity(observed)
        physical = (identity.device, identity.inode)
        if registered_name in seen_names or physical in seen_identity:
            raise SelectedResourceRejected("binding_conflict")
        seen_names.add(registered_name)
        seen_identity.add(physical)
        _account_candidate(budget, observed.st_size)
        selection_root = root if selection.folder is not None else canonical.parent
        entries.append(SelectedResourceEntry(
            entry_kind, registered_name, canonical, selection_root, identity
        ))
    if kind == "modules":
        entries.sort(key=lambda item: item.registered_name)
    else:
        entries.sort(key=lambda item: item.source_path.name)
    return SelectedResourceInventory(tuple(entries))


def _selected_paths(selection, operation, budget):
    """Select exact files or direct children while preserving explicit boundaries."""
    if selection.files:
        paths = tuple(Path(value) for value in selection.files)
        if any(".." in path.parts for path in paths):
            raise SelectedResourceRejected("trust_rejected")
        root = paths[0].parent
        for _ in paths:
            _account_scan_checked(budget)
    elif selection.folder is not None:
        root = Path(selection.folder)
        if ".." in root.parts:
            raise SelectedResourceRejected("trust_rejected")
        status = _observe(root, operation)
        if not stat.S_ISDIR(status.st_mode):
            raise SelectedResourceRejected("trust_rejected")
        paths = []
        try:
            iterator = os.scandir(root)
            try:
                _checkpoint(operation)
                for item in iterator:
                    _checkpoint(operation)
                    _account_scan_checked(budget)
                    child = root / item.name
                    try:
                        child_status = item.stat(follow_symlinks=False)
                    except OSError as error:
                        _checkpoint(operation)
                        raise SelectedResourceRejected("trust_rejected") from error
                    _checkpoint(operation)
                    if stat.S_ISDIR(child_status.st_mode):
                        continue
                    if stat.S_ISLNK(child_status.st_mode) or not stat.S_ISREG(child_status.st_mode):
                        raise SelectedResourceRejected("trust_rejected")
                    paths.append(child)
            finally:
                try:
                    iterator.close()
                except OSError as error:
                    _checkpoint(operation)
                    raise SelectedResourceRejected("trust_rejected") from error
        except OSError as error:
            _checkpoint(operation)
            raise SelectedResourceRejected("trust_rejected") from error
    else:
        return (), Path("/")
    if not root.is_absolute() or any(not path.is_absolute() for path in paths):
        raise SelectedResourceRejected("trust_rejected")
    _checkpoint(operation)
    try:
        canonical_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        _checkpoint(operation)
        raise SelectedResourceRejected("trust_rejected") from error
    _checkpoint(operation)
    if _has_symlink_ancestry(root, operation):
        raise SelectedResourceRejected("trust_rejected")
    return tuple(paths), canonical_root


def _module_name(filename: str):
    """Return the existing logical module name and kind for one filename."""
    name = _logical_name(filename, _MODULE_SUFFIXES)
    if name is None or name == "__init__" or not name.isidentifier():
        return None, None
    kind: ResourceKind = "python_source" if filename.endswith(".py") else "python_extension"
    return name, kind


def _canonical_without_symlink_ancestry(path: Path, operation) -> Path | None:
    """Reject symbolic-link ancestry with checkpoints around every observation."""
    try:
        if _has_symlink_ancestry(path, operation):
            return None
        _checkpoint(operation)
        canonical = path.resolve(strict=True)
        _checkpoint(operation)
        return canonical
    except (OSError, RuntimeError):
        _checkpoint(operation)
        return None


def _has_symlink_ancestry(path: Path, operation) -> bool:
    """Inspect a path and all ancestors without following links."""
    for ancestor in reversed((path, *path.parents)):
        status = _observe(ancestor, operation)
        if stat.S_ISLNK(status.st_mode):
            return True
    return False


def _observe(path: Path, operation):
    """Observe one path with operation checkpoints around the I/O boundary."""
    _checkpoint(operation)
    try:
        status = path.lstat()
    except OSError as error:
        _checkpoint(operation)
        raise SelectedResourceRejected("trust_rejected") from error
    _checkpoint(operation)
    return status


def _observe_regular(path: Path, operation):
    """Require one non-symlink regular source file."""
    status = _observe(path, operation)
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise SelectedResourceRejected("trust_rejected")
    return status


def _checkpoint(operation) -> None:
    """Check the caller-owned operation."""
    operation.checkpoint()


def _account_scan_checked(budget) -> None:
    """Account one selected scan through the shared budget."""
    try:
        budget.add_scan()
    except Exception as error:
        raise SelectedResourceRejected("capacity_exceeded") from error


def _account_candidate(budget, size: int) -> None:
    """Account one candidate and its source bytes through the shared budget."""
    try:
        budget.add_candidate()
        budget.add_source_bytes(size)
    except Exception as error:
        raise SelectedResourceRejected("capacity_exceeded") from error
