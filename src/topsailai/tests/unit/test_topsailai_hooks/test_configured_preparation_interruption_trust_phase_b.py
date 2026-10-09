"""Interruption and configured-root trust regressions for private preparation."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks.configured_preparation import prepare_private, get_preparation_recovery_owner
from topsailai.hooks.configured_preparation_ownership import ConfiguredRootOwner


def _root_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "configured-artifacts").mkdir(mode=0o700)
    (root / "configured-discovery").mkdir(mode=0o700)
    return root, root / "configured-artifacts", root / "configured-discovery"


def test_root_pins_complete_identity_and_requires_metadata_check(tmp_path, monkeypatch):
    root, artifacts, discovery = _root_tree(tmp_path)
    calls = []
    import topsailai.hooks.configured_preparation_ownership as ownership
    original = ownership.require_fd_metadata_absent

    def observe(fd, *, directory):
        calls.append((fd, directory))
        return original(fd, directory=directory)

    monkeypatch.setattr(ownership, "require_fd_metadata_absent", observe)
    owner = ConfiguredRootOwner(root)
    try:
        assert set(owner._identities) == {"configured-artifacts", "configured-discovery"}
        assert all(len(identity) == 5 for identity in owner._identities.values())
        assert len(calls) == 3
        owner.revalidate()
        assert len(calls) == 8
    finally:
        assert owner.close()


@pytest.mark.parametrize("replacement", ("symlink", "file", "mode", "inode"))
def test_root_child_replacement_is_stable_trust_rejection(tmp_path, replacement):
    root, artifacts, discovery = _root_tree(tmp_path)
    owner = ConfiguredRootOwner(root)
    try:
        if replacement == "symlink":
            artifacts.rmdir()
            artifacts.symlink_to(discovery, target_is_directory=True)
        elif replacement == "file":
            artifacts.rmdir()
            artifacts.write_text("not a directory", encoding="utf-8")
        elif replacement == "mode":
            artifacts.chmod(0o755)
        else:
            moved = root / "configured-artifacts-old"
            artifacts.rename(moved)
            artifacts.mkdir(mode=0o700)
        with pytest.raises(ValueError, match="^trust_rejected$"):
            owner.revalidate()
    finally:
        # The owner must never follow or remove a replacement pathname.
        for descriptor in tuple(owner._children.values()) + ((owner._root_fd,) if owner._root_fd >= 0 else ()):
            try:
                os.close(descriptor)
            except OSError:
                pass


def test_prepare_interruption_preserves_identity_and_aggregate_owner(tmp_path, monkeypatch):
    """A host interruption retains the aggregate authority only when cleanup remains."""
    from tests.unit.test_topsailai_hooks.test_configured_preparation import _runtime
    from topsailai.hooks import ConfiguredHooks, HookSettings

    sources = tmp_path / "sources"
    runtime_root = tmp_path / "runtime"
    sources.mkdir(mode=0o700)
    runtime_root.mkdir(mode=0o700)
    runtime, scope = _runtime(sources, runtime_root)
    primary = KeyboardInterrupt("prepare interruption")

    def interrupt(*args, **kwargs):
        raise primary

    monkeypatch.setattr("topsailai.hooks.configured_preparation._capture_work_sequence", interrupt)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            from topsailai.hooks import ConfiguredHookPoint, EventDefinition
            point = ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources)
            configuration = ConfiguredHooks((point,), HookSettings())
            monkeypatch.setattr("topsailai.hooks.configured_preparation._build_work_sequence", lambda *args: ())
            monkeypatch.setattr("topsailai.hooks.configured_preparation._capture_work_sequence", interrupt)
            prepare_private(runtime, configuration, scope)
        assert caught.value is primary
        # No capture resource was allocated before this checkpoint, so no
        # aggregate recovery owner is attached.
        assert get_preparation_recovery_owner(primary) is None
    finally:
        runtime.close()


def test_prepare_does_not_continue_after_pending_interruption(tmp_path, monkeypatch):
    from tests.unit.test_topsailai_hooks.test_configured_preparation import _runtime
    from topsailai.hooks import ConfiguredHooks, HookSettings

    sources = tmp_path / "sources"
    runtime_root = tmp_path / "runtime"
    sources.mkdir(mode=0o700)
    runtime_root.mkdir(mode=0o700)
    runtime, scope = _runtime(sources, runtime_root)
    primary = SystemExit("stop")
    successors = []

    def interrupt(*args, **kwargs):
        successors.append("capture")
        raise primary

    monkeypatch.setattr("topsailai.hooks.configured_preparation._capture_work_sequence", interrupt)
    try:
        with pytest.raises(SystemExit) as caught:
            from topsailai.hooks import ConfiguredHookPoint, EventDefinition
            point = ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1), module_folder=sources)
            monkeypatch.setattr("topsailai.hooks.configured_preparation._build_work_sequence", lambda *args: ())
            prepare_private(runtime, ConfiguredHooks((point,), HookSettings()), scope)
        assert caught.value is primary
        assert successors == ["capture"]
    finally:
        runtime.close()


def test_parent_path_replacement_is_rejected_before_child_handoff(tmp_path):
    """A replacement parent pathname cannot redirect a held root owner."""
    root, artifacts, discovery = _root_tree(tmp_path)
    owner = ConfiguredRootOwner(root)
    moved = tmp_path / "root-old"
    root.rename(moved)
    replacement = tmp_path / "root"
    replacement.mkdir(mode=0o700)
    (replacement / "configured-artifacts").mkdir(mode=0o700)
    (replacement / "configured-discovery").mkdir(mode=0o700)
    try:
        with pytest.raises(ValueError, match="^trust_rejected$"):
            owner.child("configured-artifacts")
        assert not (replacement / "configured-artifacts").exists() or replacement.exists()
    finally:
        owner.close()


def test_constructor_system_exit_identity_is_preserved(monkeypatch, tmp_path):
    """SystemExit from constructor validation remains the exact object."""
    primary = SystemExit("constructor exit")
    original_validate = ConfiguredRootOwner._validate_fd
    calls = {"count": 0}

    def interrupt_after_root(cls, fd):
        calls["count"] += 1
        if calls["count"] == 2:
            raise primary
        return original_validate(fd)

    monkeypatch.setattr(ConfiguredRootOwner, "_validate_fd", classmethod(interrupt_after_root))
    with pytest.raises(SystemExit) as caught:
        ConfiguredRootOwner(tmp_path)
    assert caught.value is primary
