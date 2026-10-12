"""Bounded retention and close tests for U08 artifact leases."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    activate,
    captured_candidate,
    lease_fixture,
)
from tests.unit.test_topsailai_hooks.artifact_trace_helpers import (
    composed_line_interruption,
)
from topsailai.hooks.artifact_leases import ArtifactLeaseManager
from topsailai.hooks.artifact_publication import (
    ArtifactPublicationMixin,
    PublicationCell,
    PublicationImage,
)


def test_retention_uses_last_release_and_exact_sixty_second_boundary(
    tmp_path: Path,
) -> None:
    """Retain an unreferenced version until the exact age boundary."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group, lease = captured_candidate(manager, requests, policy)
    assert manager.release(lease).accepted
    clock[0] = 59.999
    early = manager.reclaim(deadline=100.0)
    assert early.accepted and early.removed == 0
    clock[0] = 60.0
    boundary = manager.reclaim(deadline=100.0)
    assert boundary.accepted and boundary.removed == 1
    assert manager.release_group(group).accepted


def test_cleanup_budget_is_checked_between_complete_slot_passes(
    monkeypatch, tmp_path: Path
) -> None:
    """Allow one in-budget pass to overrun but do not start its sibling."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    first_group, first = captured_candidate(manager, requests, policy)
    second_group, second = captured_candidate(manager, requests, policy)
    manager.release(first)
    manager.release(second)
    calls = 0
    real_dispose = manager._owner.dispose

    def observed_dispose(artifact):
        nonlocal calls
        calls += 1
        result = real_dispose(artifact)
        clock[0] = 2.0
        return result

    monkeypatch.setattr(manager._owner, "dispose", observed_dispose)
    result = manager.reclaim(deadline=1.0, pressure=True)
    assert not result.accepted and result.errors == ("artifact_lease_timeout",)
    assert calls == 1 and manager.snapshot().stored_versions == 1
    clock[0] = 2.0
    retried = manager.reclaim(deadline=3.0, pressure=True)
    assert retried.accepted and manager.snapshot().stored_versions == 0
    manager.release_group(first_group)
    manager.release_group(second_group)


def test_repeated_close_does_not_extend_first_budget(tmp_path: Path) -> None:
    """Start no physical pass with an expired first or repeated close budget."""
    clock = [5.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    captured_candidate(manager, requests, policy)
    first = manager.close(deadline=4.0)
    second = manager.close(deadline=100.0)
    assert first.errors == second.errors == ("artifact_lease_timeout",)
    assert manager._close_deadline == 4.0
    assert manager.snapshot().capture_slots == 1
    recovered = manager.reclaim(deadline=6.0, pressure=True)
    assert recovered.accepted and recovered.removed == 1
    assert manager.snapshot().manager_state == "closed"



def test_cleanup_error_that_expires_budget_stops_before_sibling(
    monkeypatch, tmp_path: Path
) -> None:
    """Do not start a sibling pass after an ordinary failed pass expires."""
    from topsailai.hooks.artifact_contracts import ArtifactDisposeResult

    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    first_group, first = captured_candidate(manager, requests, policy)
    second_group, second = captured_candidate(manager, requests, policy)
    assert manager.release(first).accepted and manager.release(second).accepted
    real_dispose = manager._owner.dispose
    calls = []

    def fail_after_budget(artifact):
        calls.append(artifact)
        clock[0] = 2.0
        return ArtifactDisposeResult(
            True, cleanup_pending=True, errors=("artifact_cleanup_pending",)
        )

    monkeypatch.setattr(manager._owner, "dispose", fail_after_budget)
    timed_out = manager.reclaim(deadline=1.0, pressure=True)
    assert not timed_out.accepted
    assert timed_out.errors == ("artifact_lease_timeout",)
    assert timed_out.examined == 1 and len(calls) == 1
    assert manager.snapshot().stored_versions == 2

    monkeypatch.setattr(manager._owner, "dispose", real_dispose)
    clock[0] = 2.0
    retried = manager.reclaim(deadline=3.0, pressure=True)
    assert retried.accepted and retried.removed == 2
    assert manager.snapshot().stored_versions == 0
    assert manager.release_group(first_group).accepted
    assert manager.release_group(second_group).accepted


def test_explicit_retry_has_new_budget_without_extending_close(
    tmp_path: Path,
) -> None:
    """Use a fresh reclaim budget while preserving the first close deadline."""
    clock = [5.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    captured_candidate(manager, requests, policy)
    closed = manager.close(deadline=4.0)
    assert not closed.accepted and closed.errors == ("artifact_lease_timeout",)
    assert manager._close_deadline == 4.0

    retried = manager.recovery().retry(deadline=6.0)
    assert retried.accepted and retried.removed == 1
    assert manager._close_deadline is None
    assert manager.snapshot().manager_state == "closed"


def test_reclaim_expires_candidate_and_starts_retention_at_maintenance(
    tmp_path: Path,
) -> None:
    """Expire a candidate explicitly and retain its bytes for sixty seconds."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group, lease = captured_candidate(manager, requests, policy)
    directory = lease.directory

    clock[0] = 60.0
    expired = manager.reclaim(deadline=61.0)
    assert expired.accepted and expired.removed == 0
    assert lease.released and group.state == "settled"
    assert manager.snapshot().candidate_groups == 0
    assert directory.exists()

    clock[0] = 119.999
    retained = manager.reclaim(deadline=121.0)
    assert retained.accepted and retained.removed == 0
    assert directory.exists()

    clock[0] = 120.0
    reclaimed = manager.reclaim(deadline=121.0)
    assert reclaimed.accepted and reclaimed.removed == 1
    assert not directory.exists()


def test_expiry_reaches_candidate_after_live_group_prefix(
    monkeypatch, tmp_path: Path
) -> None:
    """Expire a later candidate without scanning the live-group prefix."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    active, _ = captured_candidate(manager, requests, policy)
    activate(manager, active)
    admitted = tuple(manager.admit((active,)).group for _ in range(15))
    assert all(group is not None for group in admitted)
    candidate, lease = captured_candidate(manager, requests, policy)

    examined = 0
    valid_group = manager._valid_group

    def count_candidate(group):
        nonlocal examined
        examined += 1
        return valid_group(group)

    monkeypatch.setattr(manager, "_valid_group", count_candidate)
    clock[0] = 60.0
    result = manager.reclaim(deadline=61.0)
    assert result.accepted and result.removed == 0
    assert examined == 1
    assert candidate.state == "settled" and lease.released
    assert manager.snapshot().candidate_groups == 0


def test_expiry_scans_at_most_sixteen_candidate_positions(
    monkeypatch, tmp_path: Path
) -> None:
    """Bound one explicit maintenance expiry scan to candidate capacity."""
    clock = [0.0]
    manager, _, _ = lease_fixture(tmp_path, clock=lambda: clock[0])
    groups = tuple(manager.begin_candidate().group for _ in range(16))
    assert all(group is not None for group in groups)
    assert not manager.begin_candidate().accepted

    examined = 0
    valid_group = manager._valid_group

    def count_candidate(group):
        nonlocal examined
        examined += 1
        return valid_group(group)

    monkeypatch.setattr(manager, "_valid_group", count_candidate)
    clock[0] = 60.0
    result = manager.reclaim(deadline=61.0)
    assert result.accepted and examined == 16
    assert all(group.state == "settled" for group in groups)
    assert manager.snapshot().candidate_groups == 0


@pytest.mark.parametrize(
    ("fragment", "candidate_state", "indexed"),
    (("candidate._state = \"active\"", "staged", True),
     ("if self._candidate_groups.get(candidate._group_id) is candidate:", "active", True),
     ("for group in stage._old_groups:", "active", False)),
)
def test_decided_publication_snapshot_classifies_candidate_once(
    tmp_path: Path, fragment: str, candidate_state: str, indexed: bool,
) -> None:
    """Derive exclusive group counts from the decision during bookkeeping."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=cell.current, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    stage = staged.stage
    cell.current = replacement
    source, first = inspect.getsourcelines(ArtifactPublicationMixin._reconcile_stage_locked)
    target = first + next(index for index, line in enumerate(source) if fragment in line)
    interruption = KeyboardInterrupt(fragment)

    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            ArtifactPublicationMixin._reconcile_stage_locked.__code__, target, interruption
        ):
            manager._reconcile_publication(stage)

    assert caught.value is interruption and candidate.state == candidate_state
    snapshot = manager.snapshot()
    assert snapshot.candidate_groups == 0 and snapshot.active_groups == 1
    assert snapshot.publication_stages == 1
    assert (manager._candidate_groups.get(candidate._group_id) is candidate) is indexed
    assert manager._reconcile_publication(stage).accepted


def test_decided_changed_publication_snapshot_counts_remain_exclusive(
    tmp_path: Path,
) -> None:
    """Keep decision-derived counts stable across bookkeeping states."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=cell.current, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    cell.current = replacement

    states = (("staged", True), ("active", True), ("active", False))
    for candidate_state, indexed in states:
        candidate._state = candidate_state
        if not indexed:
            manager._candidate_groups.pop(candidate._group_id)
        snapshot = manager.snapshot()
        assert snapshot.candidate_groups == 0 and snapshot.active_groups == 1

    assert manager._reconcile_publication(staged.stage).accepted


def test_decided_noop_publication_snapshot_excludes_consumed_candidate(
    tmp_path: Path,
) -> None:
    """Classify a decided no-op candidate as neither candidate nor active."""
    manager, _, _ = lease_fixture(tmp_path)
    candidate = manager.begin_candidate().group
    assert candidate is not None
    expected = PublicationImage(7, ("same",), ())
    replacement = PublicationImage(7, ("same",), ())
    cell = PublicationCell(expected)
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=False,
    )
    assert staged.accepted and staged.stage is not None
    cell.current = replacement

    snapshot = manager.snapshot()
    assert snapshot.candidate_groups == snapshot.active_groups == 0
    assert manager._reconcile_publication(staged.stage).accepted


@pytest.mark.parametrize("boundary", ("after_primary", "before_return"))
def test_interrupted_candidate_registration_leaves_no_partial_registry(
    tmp_path: Path, boundary: str,
) -> None:
    """Roll back after the primary write and immediately before returning."""
    manager, _, _ = lease_fixture(tmp_path)
    if boundary == "after_primary":
        method = ArtifactLeaseManager._register_candidate
        fragment = "self._candidate_groups[group._group_id] = group"

        def assert_boundary() -> None:
            assert len(manager._groups) == 1
            assert manager._candidate_groups == {}
    else:
        method = ArtifactLeaseManager.begin_candidate
        fragment = "return LeaseGroupResult(True, group)"

        def assert_boundary() -> None:
            assert len(manager._groups) == len(manager._candidate_groups) == 1
    source, first = inspect.getsourcelines(method)
    target = first + next(index for index, line in enumerate(source) if fragment in line)
    interruption = KeyboardInterrupt(boundary)

    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            method.__code__, target, interruption, before_interrupt=assert_boundary
        ):
            manager.begin_candidate()

    assert caught.value is interruption
    assert manager._groups == manager._candidate_groups == {}
    retried = manager.begin_candidate()
    assert retried.accepted and retried.group is not None
    assert manager.release_group(retried.group).accepted


@pytest.mark.parametrize(
    "boundary", ("before_primary", "between_removals", "after_candidate_index")
)
def test_interrupted_candidate_removal_remains_publicly_recoverable(
    tmp_path: Path, boundary: str,
) -> None:
    """Keep exact terminal custody through every dual-registry removal window."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group, _ = captured_candidate(manager, requests, policy)
    if boundary == "before_primary":
        fragment = "if self._groups.get(group._group_id) is group:"

        def assert_boundary() -> None:
            assert manager._groups.get(group._group_id) is group
            assert manager._candidate_groups.get(group._group_id) is group
            assert group._mutation is not None
    elif boundary == "between_removals":
        fragment = "if self._candidate_groups.get(group._group_id) is group:"

        def assert_boundary() -> None:
            assert group._group_id not in manager._groups
            assert manager._candidate_groups.get(group._group_id) is group
            assert group._mutation is not None
            assert manager._cleanup_pending()
    else:
        fragment = "return"

        def assert_boundary() -> None:
            assert manager._groups == manager._candidate_groups == {}
            assert group._mutation is None
    source, first = inspect.getsourcelines(ArtifactLeaseManager._unregister_candidate)
    target = first + next(index for index, line in enumerate(source) if line.strip() == fragment)
    interruption = KeyboardInterrupt(boundary)

    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            ArtifactLeaseManager._unregister_candidate.__code__, target, interruption,
            before_interrupt=assert_boundary,
        ):
            clock[0] = 60.0
            manager.reclaim(deadline=61.0)

    assert caught.value is interruption
    if boundary == "before_primary":
        assert manager.snapshot().candidate_groups == 1
    elif boundary == "between_removals":
        assert manager.snapshot().candidate_groups == 1
        assert manager._cleanup_pending()
    recovered = manager.reclaim(deadline=61.0, pressure=True)
    assert recovered.accepted
    closed = manager.close(deadline=61.0)
    assert closed.accepted and not closed.cleanup_pending
    snapshot = manager.snapshot()
    assert snapshot.manager_state == "closed"
    assert snapshot.candidate_groups == snapshot.stored_versions == 0
    assert manager._groups == manager._candidate_groups == {}
    assert group._mutation is None


def test_public_reclaim_recovers_interrupted_terminal_index_removal(
    tmp_path: Path,
) -> None:
    """Recover terminal index custody after primary removal without tracing."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group, _ = captured_candidate(manager, requests, policy)
    interruption = KeyboardInterrupt("between registry removals")

    class InterruptingCandidateIndex(dict):
        """Interrupt once when terminal removal reaches candidate custody."""

        armed = True

        def get(self, key, default=None):
            """Raise only after the primary registry has removed this group."""
            if self.armed and key == group._group_id and key not in manager._groups:
                self.armed = False
                raise interruption
            return super().get(key, default)

    manager._candidate_groups = InterruptingCandidateIndex(manager._candidate_groups)
    clock[0] = 60.0
    with pytest.raises(KeyboardInterrupt) as caught:
        manager.reclaim(deadline=61.0)

    assert caught.value is interruption
    assert group._group_id not in manager._groups
    assert manager._candidate_groups.get(group._group_id) is group
    assert group._mutation is not None and manager._cleanup_pending()

    recovered = manager.reclaim(deadline=61.0, pressure=True)
    assert recovered.accepted
    closed = manager.close(deadline=61.0)
    assert closed.accepted and not closed.cleanup_pending
    snapshot = manager.snapshot()
    assert snapshot.manager_state == "closed"
    assert snapshot.candidate_groups == snapshot.stored_versions == 0
    assert manager._groups == manager._candidate_groups == {}
    assert group._mutation is None


def test_pressure_reclaims_in_retirement_then_sequence_order(
    monkeypatch, tmp_path: Path
) -> None:
    """Use stable retirement time and version sequence to order pressure cleanup."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    first_group, first = captured_candidate(manager, requests, policy)
    second_group, second = captured_candidate(manager, requests, policy)
    third_group, third = captured_candidate(manager, requests, policy)
    pinned_group, pinned = captured_candidate(manager, requests, policy)

    clock[0] = 10.0
    assert manager.release(second).accepted
    assert manager.release(first).accepted
    clock[0] = 5.0
    assert manager.release(third).accepted

    observed = []
    real_dispose = manager._owner.dispose

    def record_dispose(artifact):
        observed.append(artifact)
        return real_dispose(artifact)

    monkeypatch.setattr(manager._owner, "dispose", record_dispose)
    reclaimed = manager.reclaim(deadline=11.0, max_versions=3, pressure=True)
    assert reclaimed.accepted and reclaimed.removed == 3
    assert observed == [third._version.artifact, first._version.artifact, second._version.artifact]
    assert pinned.directory.exists() and manager.snapshot().stored_versions == 1

    assert manager.release(pinned).accepted
    for group in (first_group, second_group, third_group, pinned_group):
        assert manager.release_group(group).accepted
    assert manager.reclaim(deadline=11.0, pressure=True).removed == 1
