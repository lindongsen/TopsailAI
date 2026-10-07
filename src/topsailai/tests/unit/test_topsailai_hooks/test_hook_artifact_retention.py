"""Bounded retention and close tests for U08 artifact leases."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    captured_candidate,
    lease_fixture,
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
    assert manager._close_deadline == 4.0
    assert manager.snapshot().manager_state == "closed"
