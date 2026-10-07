"""Behavioral branch closure for the bounded U08 lease implementation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    activate,
    captured_candidate,
    lease_fixture,
)
from topsailai.hooks.artifact_contracts import ArtifactCaptureResult
from topsailai.hooks.artifact_lease_authority import get_artifact_lease_recovery
from topsailai.hooks.artifact_lease_contracts import ArtifactLeaseDebt
from topsailai.hooks.artifact_leases import ArtifactLease, ArtifactLeaseGroup, CaptureReceipt
from topsailai.hooks.artifact_publication import (
    PublicationCell,
    PublicationImage,
    PublicationStage,
)


def test_authority_constructors_and_unattached_error_are_opaque() -> None:
    """Reject caller-created authorities and absent recovery attachments."""
    with pytest.raises(TypeError):
        ArtifactLease(object())
    with pytest.raises(TypeError):
        ArtifactLeaseGroup(object())
    with pytest.raises(TypeError):
        CaptureReceipt(object())
    with pytest.raises(TypeError):
        PublicationStage()
    with pytest.raises(TypeError):
        PublicationCell(object())
    assert get_artifact_lease_recovery(RuntimeError("plain")) is None


def test_admit_accepts_complete_active_union_without_mutation(tmp_path: Path) -> None:
    """Admit one exact token per version from mutation-free active roots."""
    manager, requests, policy = lease_fixture(tmp_path)
    first, first_source = captured_candidate(manager, requests, policy)
    cell = activate(manager, first)
    second, second_source = captured_candidate(manager, requests, policy)
    staged = manager._stage_publication(
        cell, second, expected=cell.current,
        replacement=PublicationImage(2, object(), (first, second)),
        old_groups=(), changed=True,
    )
    assert staged.accepted and manager._commit_publication(staged.stage).accepted
    admitted = manager.admit((first, second))
    assert admitted.accepted and admitted.group is not None
    assert len(admitted.group._tokens) == 2
    assert manager._execution_port().settle(admitted.group).accepted
    assert manager.retire(first).accepted and manager.retire(second).accepted
    assert first_source.released and second_source.released
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and manager.snapshot().manager_state == "closed"


def test_receipt_busy_token_and_version_reservations_are_conservative(
    monkeypatch, tmp_path: Path
) -> None:
    """Charge one pending receipt and reject all dependent candidate mutations."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    reserved = manager._reserve_capture(group, requests, policy, None)
    assert reserved.accepted and reserved.receipt is not None
    assert manager.snapshot().reserved_tokens == manager.snapshot().reserved_versions == 1
    assert manager._reserve_capture(group, requests, policy, None).errors == (
        "artifact_lease_busy",
    )
    assert manager.renew(group, expires_at=manager._clock() + 1.0).errors == (
        "artifact_lease_busy",
    )
    manager._rollback_receipt(reserved.receipt)

    monkeypatch.setattr(manager, "_max_tokens", 0)
    assert manager._reserve_capture(group, requests, policy, None).errors == (
        "artifact_lease_capacity_exceeded",
    )
    monkeypatch.setattr(manager, "_max_tokens", 4096)
    monkeypatch.setattr(manager, "_max_versions", 0)
    assert manager._reserve_capture(group, requests, policy, None).errors == (
        "artifact_lease_capacity_exceeded",
    )
    assert manager.release_group(group).accepted


def test_post_capture_cancellation_and_mutation_reject_adoption(
    monkeypatch, tmp_path: Path
) -> None:
    """Dispose issued bytes when cancellation or mutation wins the second check."""
    import threading

    for suffix, configure in (
        ("cancel", lambda group, cancellation: cancellation.set()),
        ("mutation", lambda group, cancellation: setattr(group, "_mutation", object())),
    ):
        manager, requests, policy = lease_fixture(tmp_path / suffix)
        group = manager.begin_candidate().group
        assert group is not None
        cancellation = threading.Event()
        real_capture = manager._owner.capture

        def capture_then_change(*args, **kwargs):
            result = real_capture(*args, **kwargs)
            configure(group, cancellation)
            return result

        monkeypatch.setattr(manager._owner, "capture", capture_then_change)
        result = manager.capture(group, requests, policy=policy, cancellation=cancellation)
        expected = "artifact_lease_cancelled" if suffix == "cancel" else "artifact_lease_busy"
        assert result.errors == (expected,)
        assert manager.snapshot().capture_slots == manager.snapshot().stored_versions == 0
        group._mutation = None
        assert manager.release_group(group).accepted


def test_failed_capture_and_recovery_attachment_failure_keep_manager_custody(
    monkeypatch, tmp_path: Path
) -> None:
    """Settle an ordinary failed receipt and tolerate a hostile exception object."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    monkeypatch.setattr(
        manager._owner,
        "capture",
        lambda *args, **kwargs: ArtifactCaptureResult(False, errors=("rejected",)),
    )
    assert manager.capture(group, requests, policy=policy).errors == ("rejected",)

    class Hostile(BaseException):
        """Reject dynamic attributes while preserving interruption identity."""

        __slots__ = ()

    manager._attach_recovery(Hostile())
    assert manager.release_group(group).accepted


def test_publication_validation_and_stale_decision_branches(tmp_path: Path) -> None:
    """Reject malformed, foreign, busy, and stale publication transactions."""
    manager, _, _ = lease_fixture(tmp_path / "one")
    foreign, _, _ = lease_fixture(tmp_path / "two")
    candidate = manager.begin_candidate().group
    foreign_candidate = foreign.begin_candidate().group
    assert candidate is not None and foreign_candidate is not None
    expected = PublicationImage(1, object(), ())
    cell = PublicationCell(expected)
    replacement = PublicationImage(2, object(), (candidate,))

    malformed = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=[], changed=True,
    )
    assert malformed.errors == ("invalid_publication_stage",)
    assert manager._stage_publication(
        cell, foreign_candidate, expected=expected,
        replacement=PublicationImage(2, object(), (foreign_candidate,)),
        old_groups=(), changed=True,
    ).errors == ("invalid_lease_group",)

    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    recovered = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert recovered.accepted and recovered.stage is staged.stage
    cell.current = PublicationImage(99, object(), ())
    assert manager._commit_publication(staged.stage).errors == (
        "invalid_publication_stage",
    )
    assert manager._reconcile_publication(staged.stage).errors == (
        "invalid_publication_stage",
    )
    cell.current = expected
    assert manager._abort_publication(staged.stage).accepted

    other = manager.begin_candidate().group
    assert other is not None
    other_cell = PublicationCell(PublicationImage(1, object(), ()))
    assert manager._stage_publication(
        other_cell, other, expected=other_cell.current,
        replacement=PublicationImage(2, object(), (other,)),
        old_groups=(), changed=True,
    ).errors == ("invalid_publication_stage",)
    assert manager.release_group(other).accepted


def test_cleanup_busy_exact_debt_and_closed_idempotency(tmp_path: Path) -> None:
    """Reject busy/foreign cleanup and preserve exact closed-state reports."""
    manager, _, _ = lease_fixture(tmp_path)
    assert manager._physical.acquire(blocking=False)
    try:
        busy = manager.reclaim(deadline=manager._clock() + 1.0)
    finally:
        manager._physical.release()
    assert busy.errors == ("artifact_lease_busy",)
    assert manager.retry_cleanup(
        ArtifactLeaseDebt("foreign"), deadline=manager._clock() + 1.0
    ).errors == ("invalid_cleanup_debt",)
    first = manager.close(deadline=manager._clock() + 1.0)
    second = manager.close(deadline=manager._clock() + 1.0)
    assert first.accepted and second.accepted
    assert manager.snapshot().manager_state == "closed"


def test_retire_rejects_foreign_and_stale_registry_objects(tmp_path: Path) -> None:
    """Distinguish foreign and stale root identities before state mutation."""
    manager, requests, policy = lease_fixture(tmp_path / "one")
    foreign, foreign_requests, foreign_policy = lease_fixture(tmp_path / "two")
    active, _ = captured_candidate(manager, requests, policy)
    activate(manager, active)
    foreign_group, _ = captured_candidate(foreign, foreign_requests, foreign_policy)
    assert manager.retire(foreign_group).errors == ("invalid_lease_group",)
    manager._groups.pop(active._group_id)
    assert manager.retire(active).errors == ("invalid_lease_group",)


def test_publication_invalid_stage_entrypoints_and_foreign_old_root(tmp_path: Path) -> None:
    """Reject unissued stages and old roots outside the owning manager."""
    manager, _, _ = lease_fixture(tmp_path / "manager")
    foreign, _, _ = lease_fixture(tmp_path / "foreign")
    candidate = manager.begin_candidate().group
    foreign_old = foreign.begin_candidate().group
    assert candidate is not None and foreign_old is not None
    expected = PublicationImage(1, object(), ())
    cell = PublicationCell(expected)
    replacement = PublicationImage(2, object(), (candidate,))
    invalid = object()
    assert manager._commit_publication(invalid).errors == ("invalid_publication_stage",)
    assert manager._abort_publication(invalid).errors == ("invalid_publication_stage",)
    assert manager._reconcile_publication(invalid).errors == ("invalid_publication_stage",)
    assert manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(foreign_old,), changed=True,
    ).errors == ("invalid_publication_stage",)


def test_noop_publication_releases_a_captured_candidate_token(tmp_path: Path) -> None:
    """Consume a captured no-op candidate and release its exact storage token."""
    manager, requests, policy = lease_fixture(tmp_path)
    candidate, lease = captured_candidate(manager, requests, policy)
    expected = PublicationImage(3, object(), ())
    cell = PublicationCell(expected)
    replacement = PublicationImage(3, object(), ())
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=False,
    )
    assert staged.accepted and staged.stage is not None
    assert manager._commit_publication(staged.stage).accepted
    assert lease.released
    snapshot = manager.snapshot()
    assert snapshot.live_tokens == 0 and snapshot.stored_versions == 1
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).accepted
    assert manager.snapshot().stored_versions == 0
