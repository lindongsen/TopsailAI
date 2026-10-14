"""Bounded fail-closed prepared Script membership. Author: DawsonLin."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from topsailai.hooks.hook_script_discovery import (
    ExecutablePlatformPolicy, HookScriptDiscoveryResult, HookScriptEntry,
    discover_hook_script_entries, _observe, _ObservationError, _owned, _open_owned,
)


def _reject():
    """Return no members after any unsafe filesystem observation."""
    return HookScriptDiscoveryResult(False, errors=("trust_rejected",))


def _status(path, checkpoint):
    """Bracket every named metadata observation with the same deadline."""
    return _observe(checkpoint, path.lstat)


def _canonical(path, checkpoint):
    """Reject symbolic-link ancestry before resolving a configured path."""
    for ancestor in reversed((path, *path.parents)):
        if stat.S_ISLNK(_status(ancestor, checkpoint).st_mode):
            return None
    return _observe(checkpoint, path.resolve, strict=True)


def discover_prepared_script_entries(target, platform_policy, *, operation, budget):
    """Discover direct children atomically under aggregate preparation limits."""
    if type(platform_policy) is not ExecutablePlatformPolicy:
        return _reject()
    path = Path(target)
    if not path.is_absolute():
        return _reject()
    checkpoint = operation.checkpoint
    try:
        root = _canonical(path, checkpoint)
        if root is None:
            return _reject()
        mode = _status(path, checkpoint).st_mode
        if stat.S_ISREG(mode):
            budget.add_scan()
            return _members((path,), root.parent, platform_policy, checkpoint, budget)
        if not stat.S_ISDIR(mode):
            return _reject()
        children = _open_owned(checkpoint, os.scandir, path)
        with _owned(children, checkpoint):
            checkpoint()
            candidates = []
            while True:
                child = _observe(checkpoint, next, children, None)
                if child is None:
                    break
                budget.add_scan()
                candidate = path / child.name
                child_mode = _status(candidate, checkpoint).st_mode
                if stat.S_ISDIR(child_mode):
                    continue
                if not stat.S_ISREG(child_mode):
                    return _reject()
                budget.add_candidate()
                candidates.append(candidate)
        checkpoint()
        return _members(candidates, root, platform_policy, checkpoint, budget,
                        candidates_counted=True)
    except _ObservationError:
        return _reject()


def _members(paths, root, policy, checkpoint, budget, *, candidates_counted=False):
    """Validate unique sources before publishing the complete sorted inventory."""
    entries, names, identities = [], set(), set()
    for path in paths:
        if not candidates_counted:
            budget.add_candidate()
        canonical = _canonical(path, checkpoint)
        if canonical is None or not canonical.is_relative_to(root):
            return _reject()
        status = _status(path, checkpoint)
        identity = (status.st_dev, status.st_ino)
        if not stat.S_ISREG(status.st_mode) or path.name in names or identity in identities:
            return _reject()
        # Metadata size is an early limit; capture revalidates bytes and identity.
        budget.add_source_bytes(status.st_size)
        checkpoint()
        result = discover_hook_script_entries(path, policy, checkpoint=checkpoint)
        checkpoint()
        if not result.accepted or len(result.entries) != 1:
            return _reject()
        entry = result.entries[0]
        if entry.source_path != canonical:
            return _reject()
        names.add(path.name)
        identities.add(identity)
        entries.append(HookScriptEntry(canonical, path.name, path.name))
    return HookScriptDiscoveryResult(True, tuple(sorted(
        entries, key=lambda entry: entry.final_registered_name)))
