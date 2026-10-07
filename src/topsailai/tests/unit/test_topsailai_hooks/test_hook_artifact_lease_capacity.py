"""Fixed capacity and bounded snapshot tests for U08 artifact leases."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    captured_candidate,
    lease_fixture,
)
from topsailai.hooks.artifact_lease_contracts import ArtifactLeaseDebt
from topsailai.hooks.artifact_leases import _MAX_VERSIONS, _Version


def test_physical_owner_uses_exact_slot_entry_and_byte_ceilings(tmp_path: Path) -> None:
    """Exercise the unmodified 16, 128, and 64-MiB owner capacity boundaries."""
    manager, requests, policy = lease_fixture(tmp_path)
    owner = manager._owner
    assert owner._has_capacity(128, 67_108_864)
    assert not owner._has_capacity(129, 67_108_864)
    assert not owner._has_capacity(128, 67_108_865)

    captures = []
    for _ in range(16):
        group, lease = captured_candidate(manager, requests, policy)
        captures.append((group, lease))
    snapshot = manager.snapshot()
    assert snapshot.capture_slots == snapshot.stored_versions == 16
    overflow_group = manager.begin_candidate().group
    assert overflow_group is None
    assert manager.release_group(captures[-1][0]).accepted
    extra_group = manager.begin_candidate().group
    assert extra_group is not None
    overflow = manager.capture(extra_group, requests, policy=policy)
    assert overflow.errors == ("artifact_capacity_exceeded",)
    assert manager.release_group(extra_group).accepted
    for group, lease in captures[:-1]:
        assert manager.release(lease).accepted
        assert manager.release_group(group).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 16


def test_fixed_version_ceiling_rejects_129th_reserved_version(tmp_path: Path) -> None:
    """Use the production 128-version constant without replacing it in tests."""
    manager, requests, policy = lease_fixture(tmp_path)
    source_group, source = captured_candidate(manager, requests, policy)
    for sequence in range(2, _MAX_VERSIONS + 1):
        manager._versions[sequence] = _Version(source._version.artifact, sequence)
    assert len(manager._versions) == 128
    candidate = manager.begin_candidate().group
    assert candidate is not None
    rejected = manager.capture(candidate, requests, policy=policy)
    assert rejected.errors == ("artifact_lease_capacity_exceeded",)
    snapshot = manager.snapshot()
    assert snapshot.stored_versions == 128 and snapshot.reserved_versions == 0
    manager._versions = {id(source._version.artifact): source._version}
    assert manager.release(source).accepted
    assert manager.release_group(source_group).accepted
    assert manager.release_group(candidate).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 1


def test_sharing_counts_one_bundle_while_fresh_duplicates_count_fully(tmp_path: Path) -> None:
    """Count shared references once and independent captures until exact deletion."""
    manager, requests, policy = lease_fixture(tmp_path)
    first_group, first = captured_candidate(manager, requests, policy)
    one_bundle = manager.snapshot().stored_bytes
    shared_group = manager.begin_candidate().group
    assert shared_group is not None
    assert manager.acquire(shared_group, first).accepted
    assert manager.acquire(shared_group, first).accepted
    shared = manager.snapshot()
    assert shared.live_tokens == 3 and shared.stored_bytes == one_bundle

    duplicate_group, duplicate = captured_candidate(manager, requests, policy)
    duplicated = manager.snapshot()
    assert duplicated.stored_versions == 2
    assert duplicated.stored_bytes == one_bundle + duplicate.total_bytes
    first_file = first.directory / first.entries[0].relative_path
    duplicate_file = duplicate.directory / duplicate.entries[0].relative_path
    assert first_file.stat().st_nlink == duplicate_file.stat().st_nlink == 1

    assert manager.release_group(shared_group).accepted
    assert manager.release(first).accepted
    assert manager.release(duplicate).accepted
    assert manager.release_group(first_group).accepted
    assert manager.release_group(duplicate_group).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 2


def test_snapshot_has_exact_bounded_scalar_and_debt_shapes(monkeypatch, tmp_path: Path) -> None:
    """Expose only fixed scalar counts and at most sixteen opaque cleanup debts."""
    manager, requests, policy = lease_fixture(tmp_path)
    group, lease = captured_candidate(manager, requests, policy)
    assert manager.release(lease).accepted

    import topsailai.hooks.artifact_cleanup as cleanup

    real_unlink = cleanup.os.unlink
    monkeypatch.setattr(
        cleanup.os,
        "unlink",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("retain")),
    )
    result = manager.reclaim(deadline=manager._clock() + 1.0, pressure=True)
    assert result.cleanup_pending
    snapshot = manager.recovery().snapshot()
    assert snapshot.manager_state == "open"
    assert len(snapshot.cleanup_debts) == 1 <= 16
    assert all(type(item) is ArtifactLeaseDebt for item in snapshot.cleanup_debts)
    assert all("/" not in item.debt_id and "\\" not in item.debt_id for item in snapshot.cleanup_debts)
    for field in fields(snapshot):
        value = getattr(snapshot, field.name)
        if field.name not in ("manager_state", "cleanup_debts"):
            assert type(value) is int and value >= 0
    assert type(snapshot.cleanup_debts) is tuple

    monkeypatch.setattr(cleanup.os, "unlink", real_unlink)
    debt = snapshot.cleanup_debts[0]
    assert manager.retry_cleanup(debt, deadline=manager._clock() + 1.0).accepted
    duplicate = manager.retry_cleanup(debt, deadline=manager._clock() + 1.0)
    assert duplicate.accepted and duplicate.examined == duplicate.removed == 0
    forged = ArtifactLeaseDebt(debt.debt_id, debt.category)
    assert manager.retry_cleanup(forged, deadline=manager._clock() + 1.0).errors == (
        "invalid_cleanup_debt",
    )
    assert manager.release_group(group).accepted


def test_retention_age_is_maintenance_eligibility_not_background_deletion(
    tmp_path: Path,
) -> None:
    """Leave an aged version present until an explicit maintenance call runs."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group, lease = captured_candidate(manager, requests, policy)
    directory = lease.directory
    assert manager.release(lease).accepted
    clock[0] = 600.0
    assert directory.exists() and manager.snapshot().stored_versions == 1
    reclaimed = manager.reclaim(deadline=601.0)
    assert reclaimed.accepted and reclaimed.removed == 1
    assert not directory.exists()
    assert manager.release_group(group).accepted


@pytest.mark.parametrize("limit", [True, 0, 17, 1.0])
def test_reclaim_limit_rejects_non_exact_bounded_values(tmp_path: Path, limit: object) -> None:
    """Reject invalid scan bounds without changing manager state."""
    manager, _, _ = lease_fixture(tmp_path)
    before = manager.snapshot()
    result = manager.reclaim(deadline=manager._clock() + 1.0, max_versions=limit)
    assert result.errors == ("invalid_lease_argument",)
    assert manager.snapshot() == before
