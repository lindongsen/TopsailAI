"""Focused behavioral coverage for configured preparation ownership."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import topsailai.hooks.configured_preparation_ownership as ownership
from topsailai.hooks.configured_preparation_ownership import (
    CaptureShard,
    ConfiguredRootOwner,
    PreparationOwnership,
    _settle_module_owner,
)


class U03:
    def __init__(self, debts=(), results=None):
        self.debts = list(debts)
        self.results = list(results or [True] * len(self.debts))
        self.calls = []

    def cleanup_debts(self):
        return tuple(SimpleNamespace(debt_id=item) for item in self.debts)

    def retry_cleanup(self, debt_id):
        self.calls.append(debt_id)
        result = self.results.pop(0) if self.results else True
        if result and debt_id in self.debts:
            self.debts.remove(debt_id)
        return result


class U07:
    def __init__(self, debts=(), result=None, error=None):
        self.debts = list(debts)
        self.result = result or SimpleNamespace(accepted=True, cleanup_pending=False)
        self.error = error
        self.released = []
        self.calls = []

    def snapshot(self):
        return SimpleNamespace(cleanup_debts=tuple(self.debts))

    def release_group(self, group):
        self.released.append(group)
        if self.error:
            raise self.error

    def close(self, *, deadline):
        self.calls.append(deadline)
        return self.result

    def retry_cleanup(self, debt, *, deadline):
        self.calls.append((debt, deadline))
        if debt in self.debts:
            self.debts.remove(debt)
        return self.result


class RootStub:
    def __init__(self, closed=False, failed=(), close_result=True):
        self._closed = closed
        self._failed_slots = set(failed)
        self._root_fd = -1 if closed else 42
        self.close_result = close_result
        self.close_calls = 0
        self.revalidate_calls = 0

    def close(self):
        self.close_calls += 1
        if self.close_result:
            self._closed = True
            self._root_fd = -1
            self._failed_slots.clear()
        return self.close_result

    def close_slot(self, slot):
        if str(slot) != "42":
            return False
        self._closed = True
        self._root_fd = -1
        self._failed_slots.discard(42)
        return True

    def revalidate(self):
        self.revalidate_calls += 1


def test_real_root_construct_revalidate_child_and_close_is_idempotent(tmp_path):
    root = ConfiguredRootOwner(tmp_path)
    assert root.child("configured-artifacts") == tmp_path / "configured-artifacts"
    root.revalidate()
    assert root.close()
    assert root.close()
    with pytest.raises(ValueError, match="trust_rejected"):
        root.revalidate()


def test_root_rejects_bad_root_and_metadata(monkeypatch, tmp_path):
    original = os.fstat
    calls = {"count": 0}

    def bad_fstat(fd):
        calls["count"] += 1
        if calls["count"] == 1:
            return os.stat_result((0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return original(fd)

    monkeypatch.setattr(ownership.os, "fstat", bad_fstat)
    with pytest.raises(ValueError, match="trust_rejected"):
        ConfiguredRootOwner(tmp_path)

    monkeypatch.setattr(ownership.os, "fstat", original)
    owner = ConfiguredRootOwner(tmp_path)
    monkeypatch.setattr(ownership, "require_fd_metadata_absent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("metadata")))
    with pytest.raises(ValueError, match="trust_rejected"):
        owner.child("configured-artifacts")
    owner.close()


def test_root_revalidation_child_missing_and_identity_mismatch(monkeypatch, tmp_path):
    owner = ConfiguredRootOwner(tmp_path)
    with pytest.raises(ValueError, match="trust_rejected"):
        owner.child("unknown")
    monkeypatch.setattr(ownership.os, "stat", lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    with pytest.raises(ValueError, match="trust_rejected"):
        owner.child("configured-artifacts")
    owner.close()


def test_close_slot_all_result_branches(monkeypatch, tmp_path):
    owner = ConfiguredRootOwner(tmp_path)
    assert owner.close_slot("not-an-int") is False
    assert owner.close_slot("999999") is False
    fd = owner._root_fd
    real_close = os.close
    monkeypatch.setattr(ownership.os, "close", lambda value: (_ for _ in ()).throw(OSError("close")) if value == fd else real_close(value))
    assert owner.close_slot(str(fd)) is False
    monkeypatch.setattr(ownership.os, "close", real_close)
    assert owner.close_slot(str(fd)) is True
    owner.close()


def test_close_retains_failed_descriptors_then_retries(monkeypatch, tmp_path):
    owner = ConfiguredRootOwner(tmp_path)
    real_close = os.close
    failed = {next(iter(owner._children.values()))}

    def flaky(fd):
        if fd in failed:
            raise OSError("busy")
        real_close(fd)

    monkeypatch.setattr(ownership.os, "close", flaky)
    assert owner.close() is False
    assert failed <= owner._failed_slots
    failed.clear()
    monkeypatch.setattr(ownership.os, "close", real_close)
    assert owner.close() is True


def test_registration_guards_and_debt_snapshot_limits():
    aggregate = PreparationOwnership(None, 10.0)
    manager = U07([SimpleNamespace(debt_id=f"d{i}") for i in range(20)])
    group = object()
    aggregate.register_shard(CaptureShard(1, manager, group))
    with pytest.raises(RuntimeError):
        aggregate.register_shard(CaptureShard(2, manager, object()))
    with pytest.raises(RuntimeError):
        aggregate.register_shard(CaptureShard(2, U07(), group))
    owner = U03(["u"])
    aggregate.register_module_owner(owner, "hook")
    with pytest.raises(RuntimeError):
        aggregate.register_module_owner(owner)
    aggregate.mark_pending()
    with pytest.raises(RuntimeError):
        aggregate.register_module_owner(U03())
    debts = aggregate.cleanup_debts()
    assert len([d for d in debts if d.category == "u07"]) == 16
    assert all(d.debt_id.startswith("u07:1:") for d in debts if d.category == "u07")


def test_retry_u03_u07_root_and_unknown_paths():
    root = RootStub(failed=[42])
    owner = U03(["u"])
    debt = SimpleNamespace(debt_id="z")
    manager = U07([debt])
    aggregate = PreparationOwnership(root, 8.0)
    aggregate.register_module_owner(owner, "h")
    aggregate.register_shard(CaptureShard(3, manager, object()))
    assert aggregate.retry_cleanup("u03:h:u")
    assert aggregate.retry_cleanup("u07:3:z")
    assert aggregate.retry_cleanup("root:42")
    assert aggregate.retry_cleanup("missing") is False
    assert manager.calls and manager.calls[0][0] is debt


def test_retry_u07_missing_exact_cache_and_root_fallback(monkeypatch):
    manager = U07([SimpleNamespace(debt_id="d")])
    aggregate = PreparationOwnership(None, 1.0)
    aggregate.register_shard(CaptureShard(0, manager, object()))
    aggregate._u07_debts["u07:0:d"] = None
    assert aggregate.retry_cleanup("u07:0:d") is False
    root = RootStub(failed=[42])
    aggregate = PreparationOwnership(root, 1.0)
    aggregate.cleanup_debts()
    assert aggregate.retry_cleanup("root:42")


def test_settle_success_closed_idempotent_and_all_failures():
    root = RootStub()
    manager = U07()
    aggregate = PreparationOwnership(root, 4.0)
    aggregate.register_shard(CaptureShard(0, manager, "group"))
    assert aggregate.settle()
    assert aggregate.state == "closed"
    assert aggregate.settle()

    for result in (SimpleNamespace(accepted=False, cleanup_pending=False), SimpleNamespace(accepted=True, cleanup_pending=True)):
        root = RootStub()
        manager = U07(result=result)
        aggregate = PreparationOwnership(root, 4.0)
        aggregate.register_shard(CaptureShard(0, manager, object()))
        assert aggregate.settle() is False
        assert aggregate.state == "cleanup_pending"


def test_settle_exception_interruptions_and_root_failure():
    for error in (RuntimeError("failure"),):
        aggregate = PreparationOwnership(None, 4.0)
        aggregate.register_shard(CaptureShard(0, U07(error=error), object()))
        assert aggregate.settle() is False
        assert aggregate.state == "cleanup_pending"
    for error in (KeyboardInterrupt(), SystemExit()):
        aggregate = PreparationOwnership(None, 4.0)
        aggregate.register_shard(CaptureShard(0, U07(error=error), object()))
        with pytest.raises(type(error)):
            aggregate.settle()
    aggregate = PreparationOwnership(RootStub(close_result=False), 4.0)
    assert aggregate.settle() is False
    assert aggregate.state == "cleanup_pending"


def test_module_owner_settlement_and_transfer_paths():
    assert _settle_module_owner(U03())
    assert _settle_module_owner(U03(["d"], [True]))
    assert not _settle_module_owner(U03(["d"], [False]))
    root = RootStub()
    aggregate = PreparationOwnership(root, 2.0)
    aggregate.transfer_to_image()
    assert aggregate.state == "transferred"
    assert root.revalidate_calls == 1
    with pytest.raises(RuntimeError):
        aggregate.transfer_to_image()


def test_transfer_rejects_debts_and_pending_state():
    aggregate = PreparationOwnership(None, 2.0)
    aggregate.register_module_owner(U03(["d"]))
    with pytest.raises(RuntimeError):
        aggregate.transfer_to_image()
    aggregate = PreparationOwnership(None, 2.0)
    aggregate.mark_pending()
    with pytest.raises(RuntimeError):
        aggregate.transfer_to_image()


def test_real_child_debt_is_published_and_retried_by_exact_aggregate_id(monkeypatch, tmp_path):
    """A failed child close remains reachable through the aggregate debt ID."""
    owner = ConfiguredRootOwner(tmp_path)
    child_fd = owner._children["configured-artifacts"]
    real_close = os.close
    blocked = {child_fd}

    def flaky(fd):
        if fd in blocked:
            raise OSError("busy")
        real_close(fd)

    monkeypatch.setattr(ownership.os, "close", flaky)
    aggregate = PreparationOwnership(owner, 10.0)
    assert aggregate.settle() is False
    debt = next(item for item in aggregate.cleanup_debts() if item.category == "root")
    assert debt.debt_id == f"root:{child_fd}"
    blocked.clear()
    monkeypatch.setattr(ownership.os, "close", real_close)
    assert aggregate.retry_cleanup(debt.debt_id)
    assert aggregate.settle()
    assert aggregate.cleanup_debts() == ()


def test_constructor_host_interrupt_keeps_identity_and_private_owner(monkeypatch, tmp_path):
    """Constructor interruption is not normalized and retains exact debt owner."""
    primary = KeyboardInterrupt("constructor stop")
    calls = {"count": 0}
    original_validate = ConfiguredRootOwner._validate_fd

    def interrupt_after_root(cls, fd):
        calls["count"] += 1
        if calls["count"] == 2:
            raise primary
        return original_validate(fd)

    monkeypatch.setattr(ConfiguredRootOwner, "_validate_fd", classmethod(interrupt_after_root))
    with pytest.raises(KeyboardInterrupt) as caught:
        ConfiguredRootOwner(tmp_path)
    assert caught.value is primary
    assert ownership.get_configured_root_recovery_owner(primary) is None


def test_close_host_interruption_keeps_all_owned_slots_retryable(monkeypatch, tmp_path):
    """A host interruption before bookkeeping leaves exact custody recoverable."""
    owner = ConfiguredRootOwner(tmp_path)
    real_close = os.close
    interrupted = {"value": False}

    def interrupt_first(fd):
        if not interrupted["value"]:
            interrupted["value"] = True
            raise KeyboardInterrupt("cleanup stop")
        return real_close(fd)

    monkeypatch.setattr(ownership.os, "close", interrupt_first)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.close()
    assert str(caught.value) == "cleanup stop"
    debts = owner.cleanup_debts()
    assert {int(debt.debt_id) for debt in debts} == set(owner._children.values()) | {owner._root_fd}
    monkeypatch.setattr(ownership.os, "close", real_close)
    for debt in debts:
        assert owner.close_slot(debt.debt_id)
    assert owner._closed
    assert owner.cleanup_debts() == ()


def test_close_slot_host_interruption_preserves_exact_slot(monkeypatch, tmp_path):
    """A close-slot interruption does not discard the owned descriptor."""
    owner = ConfiguredRootOwner(tmp_path)
    fd = owner._root_fd
    primary = SystemExit("slot stop")
    original_close = ownership.os.close
    ownership.os.close = lambda value: (_ for _ in ()).throw(primary)
    try:
        with pytest.raises(SystemExit) as caught:
            owner.close_slot(str(fd))
    finally:
        ownership.os.close = original_close
    assert caught.value is primary
    assert owner._root_fd == fd
    assert owner.cleanup_debts()[0].debt_id == str(fd)
    monkeypatch.setattr(ownership.os, "close", os.close)
    assert owner.close_slot(str(fd))
    assert owner.close()


def test_constructor_cleanup_host_interruption_attaches_exact_owner(monkeypatch, tmp_path):
    """An ordinary constructor failure with interrupted cleanup preserves authority."""
    primary = ValueError("trust_rejected")
    cleanup = KeyboardInterrupt("cleanup stop")
    original_validate = ConfiguredRootOwner._validate_fd
    calls = {"value": 0}

    def reject_child(cls, fd):
        calls["value"] += 1
        if calls["value"] == 2:
            raise primary
        return original_validate(fd)

    monkeypatch.setattr(ConfiguredRootOwner, "_validate_fd", classmethod(reject_child))
    real_close = os.close
    monkeypatch.setattr(ownership.os, "close", lambda value: (_ for _ in ()).throw(cleanup))
    with pytest.raises(KeyboardInterrupt) as caught:
        ConfiguredRootOwner(tmp_path)
    assert caught.value is cleanup
    owner = ownership.get_configured_root_recovery_owner(cleanup)
    assert owner is not None and owner.cleanup_debts()
    monkeypatch.setattr(ownership.os, "close", real_close)
    for debt in owner.cleanup_debts():
        assert owner.close_slot(debt.debt_id)
    assert owner._closed


def test_aggregate_requires_recovery_tracks_actual_root_custody(tmp_path):
    """Aggregate recovery remains required while exact root custody exists."""
    owner = ConfiguredRootOwner(tmp_path)
    aggregate = PreparationOwnership(owner, 1.0)
    aggregate.mark_pending()
    assert aggregate.requires_recovery()
    debts = aggregate.cleanup_debts()
    assert len(debts) == 3
    for debt in debts:
        assert aggregate.retry_cleanup(debt.debt_id)
    assert owner._closed
    aggregate.state = "closed"
    assert aggregate.requires_recovery() is False


def test_root_debt_snapshot_excludes_closed_slots_after_exact_retry(monkeypatch, tmp_path):
    """Exact child and root retries update aggregate state independently."""
    owner = ConfiguredRootOwner(tmp_path)
    aggregate = PreparationOwnership(owner, 1.0)
    aggregate.mark_pending()
    first = aggregate.cleanup_debts()[0]
    assert aggregate.retry_cleanup(first.debt_id)
    remaining = aggregate.cleanup_debts()
    assert first.debt_id not in {debt.debt_id for debt in remaining}
    real_close = os.close
    monkeypatch.setattr(ownership.os, "close", real_close)
    for debt in remaining:
        assert aggregate.retry_cleanup(debt.debt_id)
    assert aggregate.cleanup_debts() == ()
