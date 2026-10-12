"""Core ownership tests for U08 artifact leases."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_trace_helpers import composed_line_interruption

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    activate,
    captured_candidate,
    lease_fixture,
)

def test_capture_reserves_adopts_and_reclaims_exact_version(tmp_path: Path) -> None:
    """Adopt one real capture and reclaim it only after exact release."""
    manager, requests, policy = lease_fixture(tmp_path)
    group, lease = captured_candidate(manager, requests, policy)
    snapshot = manager.snapshot()
    assert snapshot.capture_slots == snapshot.stored_versions == snapshot.live_tokens == 1
    assert lease.directory.is_dir()
    assert manager.release(lease).accepted
    result = manager.reclaim(deadline=manager._clock() + 1.0, pressure=True)
    assert result.accepted and result.removed == 1
    assert manager.snapshot().capture_slots == 0
    assert manager.release_group(group).accepted

def test_repeated_acquire_creates_distinct_tokens_and_scope_is_exact(tmp_path: Path) -> None:
    """Release an inner scoped acquisition without releasing its outer source."""
    manager, requests, policy = lease_fixture(tmp_path)
    source_group, source = captured_candidate(manager, requests, policy)
    inner_group = manager.begin_candidate().group
    assert inner_group is not None
    first = manager.acquire(inner_group, source)
    assert first.accepted and first.lease is not None and first.lease is not source
    scoped_group = manager.begin_candidate().group
    assert scoped_group is not None
    with pytest.raises(RuntimeError):
        with manager._lease_scope(scoped_group, source) as scoped:
            assert scoped.accepted and scoped.lease is not None
            assert manager.snapshot().live_tokens == 3
            raise RuntimeError("body")
    assert manager.snapshot().live_tokens == 2
    assert not source.released and not first.lease.released
    assert manager.release_group(inner_group).accepted
    assert manager.release(source).accepted
    assert manager.release(source).already_settled
    assert manager.release_group(source_group).accepted


@pytest.mark.parametrize(
    "fragment",
    (
        "self._tokens.pop", "lease._group._tokens.discard",
        "lease._version.tokens.discard", "lease._released = True",
    ),
)
def test_execution_settlement_reconciles_interrupted_token_release(
    tmp_path: Path, fragment: str,
) -> None:
    """Retry settlement with exact custody through every release boundary."""
    import inspect

    from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin

    manager, requests, policy = lease_fixture(tmp_path)
    candidate, source = captured_candidate(manager, requests, policy)
    activate(manager, candidate)
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None
    group = admitted.group
    execution = manager._tokens[next(iter(group._tokens))]
    version = execution._version
    method = ArtifactLeaseTransactionMixin._release_token
    source_lines, first_line = inspect.getsourcelines(method)
    target = first_line + next(
        index for index, line in enumerate(source_lines) if fragment in line
    )
    interruption = KeyboardInterrupt(fragment)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager._execution_port().settle(group)
    assert caught.value is interruption

    settled = manager._execution_port().settle(group)
    assert settled.accepted
    assert group.state == "settled" and not group._tokens
    assert execution.released and execution._token_id not in version.tokens
    assert execution._token_id not in manager._tokens
    assert manager.snapshot().live_tokens == 1
    assert not source.released
    assert manager.retire(candidate).accepted and source.released
    reclaimed = manager.reclaim(deadline=manager._clock() + 1.0, pressure=True)
    assert reclaimed.accepted and reclaimed.removed == 1
    assert manager.snapshot().stored_versions == 0


@pytest.mark.parametrize(
    ("fragment", "occurrence"),
    (
        ("self._release_token(lease)", 0), ("group._state = state", 0),
        ("group._terminal = True", 0), ("group._mutation = None", 2),
        ("self._remove_group_if_settled(group)", 1),
    ),
)
def test_execution_settlement_reconciles_interrupted_group_transition(
    tmp_path: Path, fragment: str, occurrence: int,
) -> None:
    """Finish the same exact-custody transaction before reporting settled."""
    import inspect

    from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin

    manager, requests, policy = lease_fixture(tmp_path)
    candidate, source = captured_candidate(manager, requests, policy)
    activate(manager, candidate)
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None
    group = admitted.group
    execution = manager._tokens[next(iter(group._tokens))]
    version = execution._version
    method = ArtifactLeaseTransactionMixin._reconcile_group_mutation
    source_lines, first_line = inspect.getsourcelines(method)
    matches = [
        index for index, line in enumerate(source_lines) if fragment in line
    ]
    target = first_line + matches[occurrence]
    interruption = KeyboardInterrupt(fragment)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager._execution_port().settle(group)
    assert caught.value is interruption

    settled = manager._execution_port().settle(group)
    assert settled.accepted
    assert group.state == "settled" and group._terminal and not group._tokens
    assert group._group_id not in manager._groups
    assert execution.released and execution._token_id not in version.tokens
    assert execution._token_id not in manager._tokens
    assert manager.snapshot().live_tokens == 1
    assert manager.begin_candidate().accepted
    assert manager.retire(candidate).accepted and source.released
    reclaimed = manager.reclaim(deadline=manager._clock() + 1.0, pressure=True)
    assert reclaimed.accepted and reclaimed.removed == 1
    extra_group = manager._groups[max(manager._groups)]
    assert manager.release_group(extra_group).accepted
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted
    assert manager.snapshot().manager_state == "closed"
    assert manager._groups == {} and manager.snapshot().stored_versions == 0


@pytest.mark.parametrize(
    ("fragment", "occurrence"),
    (
        ("group._state = state", 0),
        ("group._terminal = True", 0),
        ("self._remove_group_if_settled(group)", 1),
    ),
)
def test_close_retry_reconciles_interrupted_group_settlement(
    tmp_path: Path, fragment: str, occurrence: int,
) -> None:
    """Let close alone recover every interrupted terminal metadata boundary."""
    import inspect

    from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin

    manager, requests, policy = lease_fixture(tmp_path)
    candidate, source = captured_candidate(manager, requests, policy)
    activate(manager, candidate)
    method = ArtifactLeaseTransactionMixin._reconcile_group_mutation
    source_lines, first_line = inspect.getsourcelines(method)
    matches = [
        index for index, line in enumerate(source_lines) if fragment in line
    ]
    target = first_line + matches[occurrence]
    interruption = KeyboardInterrupt(fragment)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager.close(deadline=manager._clock() + 1.0)
    assert caught.value is interruption
    assert candidate._mutation is not None

    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    snapshot = manager.snapshot()
    assert source.released and candidate._mutation is None
    assert manager._groups == {}
    assert snapshot.stored_versions == 0
    assert snapshot.manager_state == "closed"

def test_reclaim_reports_interrupted_close_metadata_pending(tmp_path: Path) -> None:
    """Report a retained settlement journal until close alone reconciles it."""
    import inspect

    from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin

    manager, requests, policy = lease_fixture(tmp_path)
    candidate, source = captured_candidate(manager, requests, policy)
    activate(manager, candidate)
    method = ArtifactLeaseTransactionMixin._reconcile_group_mutation
    source_lines, first_line = inspect.getsourcelines(method)
    target = first_line + next(
        index for index, line in enumerate(source_lines)
        if "group._terminal = True" in line
    )
    interruption = KeyboardInterrupt("before terminal flag")
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager.close(deadline=manager._clock() + 1.0)
    assert caught.value is interruption
    assert source.released and candidate._mutation is not None

    reclaimed = manager.reclaim(deadline=manager._clock() + 1.0, pressure=True)
    assert reclaimed.accepted and reclaimed.removed == 1
    assert reclaimed.cleanup_pending
    assert reclaimed.errors == ("artifact_cleanup_pending",)
    assert manager.snapshot().stored_versions == 0
    assert manager._groups.get(candidate._group_id) is candidate

    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    assert candidate._mutation is None and manager._groups == {}
    snapshot = manager.snapshot()
    assert snapshot.stored_versions == 0
    assert snapshot.manager_state == "closed"

def test_capture_adoption_reconciles_interrupted_token_publication(
    monkeypatch, tmp_path: Path,
) -> None:
    """Finish an armed issue mutation before classifying adoption custody."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    original = manager._issue_token

    def interrupt_after_manager_registry(lease):
        manager._tokens[lease._token_id] = lease
        monkeypatch.setattr(manager, "_issue_token", original)
        raise KeyboardInterrupt("partial issue")

    monkeypatch.setattr(manager, "_issue_token", interrupt_after_manager_registry)
    with pytest.raises(KeyboardInterrupt):
        manager.capture(group, requests, policy=policy)
    monkeypatch.setattr(manager, "_issue_token", original)

    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.reserved_tokens == 0
    assert snapshot.live_tokens == snapshot.stored_versions == snapshot.capture_slots == 1
    assert not group._mutation and len(group._tokens) == 1
    assert manager.release_group(group).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 1

def test_staged_candidate_cannot_release_and_commit_revalidates_authority(
    tmp_path: Path,
) -> None:
    """Protect a staged candidate from lifecycle release until one decision."""
    from topsailai.hooks.artifact_publication import PublicationCell, PublicationImage

    manager, requests, policy = lease_fixture(tmp_path)
    candidate, _ = captured_candidate(manager, requests, policy)
    expected = PublicationImage(0, object(), ())
    replacement = PublicationImage(1, object(), (candidate,))
    cell = PublicationCell(expected)
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    assert manager.release_group(candidate).errors == ("artifact_lease_busy",)
    assert manager._commit_publication(staged.stage).accepted
    assert cell.current is replacement and candidate.state == "active"


def test_pending_capture_reservation_blocks_token_overcommit(tmp_path: Path) -> None:
    """Charge the pending token against both acquire and admission at 4096."""
    manager, requests, policy = lease_fixture(tmp_path)
    source_group, source = captured_candidate(manager, requests, policy)
    destination = manager.begin_candidate().group
    pending_group = manager.begin_candidate().group
    assert destination is not None and pending_group is not None
    for _ in range(4094):
        assert manager.acquire(destination, source).accepted
    assert manager.snapshot().live_tokens == 4095
    reserved = manager._reserve_capture(
        pending_group, requests, policy, manager._clock() + 1.0
    )
    assert reserved.accepted and reserved.receipt is not None
    assert manager.snapshot().reserved_tokens == 1
    assert manager.acquire(destination, source).errors == (
        "artifact_lease_capacity_exceeded",
    )
    activate(manager, source_group)
    assert manager.admit((source_group,)).errors == (
        "artifact_lease_capacity_exceeded",
    )
    manager._rollback_receipt(reserved.receipt)
    assert manager.release_group(destination).accepted
    assert manager.retire(source_group).accepted
    assert manager.release_group(pending_group).accepted


def test_snapshot_never_queries_owner_while_holding_manager_lock(
    monkeypatch, tmp_path: Path,
) -> None:
    """Keep owner observation outside the metadata lock to avoid lock inversion."""
    manager, _, _ = lease_fixture(tmp_path)
    original = manager._owner.cleanup_debts

    def checked_cleanup_debts():
        assert not manager._lock._is_owned()
        return original()

    monkeypatch.setattr(manager._owner, "cleanup_debts", checked_cleanup_debts)
    assert manager.snapshot().cleanup_debts == ()




def test_execution_debt_rejects_partial_release_and_settles_whole_group(tmp_path: Path) -> None:
    """Keep admitted bytes pinned until the trusted whole-group port settles."""
    manager, requests, policy = lease_fixture(tmp_path)
    candidate, source = captured_candidate(manager, requests, policy)
    activate(manager, candidate)
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None
    admitted_token = manager._tokens[next(iter(admitted.group._tokens))]
    assert manager.release(admitted_token).errors == ("invalid_execution_state",)
    assert manager.release_group(admitted.group).errors == ("invalid_execution_state",)
    port = manager._execution_port()
    assert port.retain_for_cleanup(admitted.group).accepted
    assert port.retain_for_cleanup(admitted.group).already_settled
    assert manager.snapshot().execution_debt_groups == 1
    assert port.settle(admitted.group).accepted
    duplicate = port.settle(admitted.group)
    assert duplicate.accepted and duplicate.already_settled
    assert manager.retire(candidate).accepted
    assert source.released


def test_execution_debt_keeps_bytes_on_early_return_and_rejects_foreign_port(
    tmp_path: Path,
) -> None:
    """Keep the whole union pinned until its exact trusted port settles it."""
    manager, requests, policy = lease_fixture(tmp_path / "local")
    foreign, _, _ = lease_fixture(tmp_path / "foreign")
    candidate, source = captured_candidate(manager, requests, policy)
    activate(manager, candidate)
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None
    group = admitted.group
    token = manager._tokens[next(iter(group._tokens))]
    stored_bytes = manager.snapshot().stored_bytes

    assert manager.release(token).errors == ("invalid_execution_state",)
    assert manager.release_group(group).errors == ("invalid_execution_state",)
    port = manager._execution_port()
    assert port.retain_for_cleanup(group).accepted
    assert port.retain_for_cleanup(group).already_settled
    foreign_port = foreign._execution_port()
    assert foreign_port.retain_for_cleanup(group).errors == ("invalid_execution_state",)
    assert foreign_port.settle(group).errors == ("invalid_execution_state",)
    assert manager.release(token).errors == ("invalid_execution_state",)
    assert manager.release_group(group).errors == ("invalid_execution_state",)

    early_return_snapshot = manager.snapshot()
    assert early_return_snapshot.execution_debt_groups == 1
    assert early_return_snapshot.live_tokens == 2
    assert early_return_snapshot.stored_bytes == stored_bytes
    assert not token.released and token.directory.is_dir()

    assert port.settle(group).accepted
    duplicate = port.settle(group)
    assert duplicate.accepted and duplicate.already_settled
    assert manager.snapshot().stored_bytes == stored_bytes
    assert manager.retire(candidate).accepted and source.released


def test_execution_port_rejects_retransfer_after_exact_settlement(tmp_path: Path) -> None:
    """Reject a debt transfer after exact whole-group settlement."""
    manager, requests, policy = lease_fixture(tmp_path)
    candidate, source = captured_candidate(manager, requests, policy)
    activate(manager, candidate)
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None
    port = manager._execution_port()
    assert port.settle(admitted.group).accepted
    assert port.retain_for_cleanup(admitted.group).errors == ("invalid_execution_state",)
    assert port.settle(admitted.group).already_settled
    assert manager.retire(candidate).accepted and source.released


def test_candidate_and_token_limits_use_fixed_production_boundaries(tmp_path: Path) -> None:
    """Reject adjacent 16/17 candidate and 4096/4097 token boundaries."""
    manager, requests, policy = lease_fixture(tmp_path)
    candidates = [manager.begin_candidate() for _ in range(16)]
    assert all(item.accepted for item in candidates)
    assert manager.begin_candidate().errors == ("artifact_lease_capacity_exceeded",)
    for item in candidates:
        assert item.group is not None and manager.release_group(item.group).accepted
    source_group, source = captured_candidate(manager, requests, policy)
    destination = manager.begin_candidate().group
    assert destination is not None
    for _ in range(4095):
        assert manager.acquire(destination, source).accepted
    assert manager.snapshot().live_tokens == 4096
    assert manager.acquire(destination, source).errors == ("artifact_lease_capacity_exceeded",)
    assert manager.release_group(destination).accepted
    assert manager.release(source).accepted
    assert manager.release_group(source_group).accepted


def test_candidate_renew_is_non_sliding_and_cannot_resurrect_expiry(tmp_path: Path) -> None:
    """Bound renewal by birth plus sixty seconds and reject expired groups."""
    clock = [10.0]
    manager, _, _ = lease_fixture(tmp_path, clock=lambda: clock[0])
    group = manager.begin_candidate(deadline=20.0).group
    assert group is not None and group.expires_at == 20.0
    assert manager.renew(group, expires_at=69.999).accepted
    assert group.expires_at == 69.999
    assert manager.renew(group, expires_at=70.001).errors == ("invalid_lease_argument",)
    assert manager.renew(group, expires_at=float("nan")).errors == ("invalid_lease_argument",)
    clock[0] = 69.999
    assert manager.renew(group, expires_at=70.0).errors == ("artifact_candidate_expired",)
    assert manager.release_group(group).accepted


def test_scoped_acquire_recovers_token_when_return_is_interrupted(
    monkeypatch, tmp_path: Path
) -> None:
    """Release the exact inserted inner token when acquisition never yields."""
    manager, requests, policy = lease_fixture(tmp_path)
    source_group, source = captured_candidate(manager, requests, policy)
    destination = manager.begin_candidate().group
    assert destination is not None
    original = manager._publish_token

    def interrupt_after_insertion(lease):
        original(lease)
        raise KeyboardInterrupt("after insertion")

    monkeypatch.setattr(manager, "_publish_token", interrupt_after_insertion)
    with pytest.raises(KeyboardInterrupt):
        with manager._lease_scope(destination, source):
            pytest.fail("scope must not yield")
    assert manager.snapshot().live_tokens == 1
    assert not source.released
    assert manager.release_group(destination).accepted
    assert manager.release(source).accepted
    assert manager.release_group(source_group).accepted


def test_group_scope_settles_only_its_exact_admission(tmp_path: Path) -> None:
    """Settle the admitted union on both normal and exceptional scope exits."""
    manager, requests, policy = lease_fixture(tmp_path)
    active, source = captured_candidate(manager, requests, policy)
    activate(manager, active)
    with manager._group_scope((active,)) as admitted:
        assert admitted.accepted and admitted.group is not None
        exact = admitted.group
        assert exact.state == "admitted"
    assert exact.state == "settled"
    duplicate = manager._execution_port().settle(exact)
    assert duplicate.accepted and duplicate.already_settled
    with pytest.raises(RuntimeError):
        with manager._group_scope((active,)) as second:
            assert second.accepted and second.group is not None
            second_exact = second.group
            raise RuntimeError("body")
    assert second_exact.state == "settled"
    assert manager.retire(active).accepted and source.released


def test_real_group_limit_rejects_group_4097(tmp_path: Path) -> None:
    """Exercise the fixed 4096/4097 metadata group boundary without lowering it."""
    manager, _, _ = lease_fixture(tmp_path)
    candidate = manager.begin_candidate().group
    assert candidate is not None
    activate(manager, candidate)
    admissions = []
    for _ in range(4095):
        result = manager.admit((candidate,))
        assert result.accepted and result.group is not None
        admissions.append(result.group)
    assert len(manager._groups) == 4096
    assert manager.admit((candidate,)).errors == ("artifact_lease_capacity_exceeded",)
    port = manager._execution_port()
    for group in admissions:
        assert port.settle(group).accepted
    assert manager.retire(candidate).accepted


@pytest.mark.parametrize("deadline", [True, 1, float("nan"), float("inf")])
def test_deadline_and_container_inputs_reject_before_mutation(
    tmp_path: Path, deadline: object
) -> None:
    """Reject malformed bounded inputs without creating lifecycle authority."""
    manager, _, _ = lease_fixture(tmp_path)
    before = manager.snapshot()
    assert manager.begin_candidate(deadline=deadline).errors == ("invalid_lease_argument",)
    assert manager.reclaim(deadline=deadline).errors == ("invalid_lease_argument",)
    assert manager.close(deadline=deadline).errors == ("invalid_lease_argument",)
    assert manager.snapshot() == before
    assert manager.admit([]).errors == ("invalid_lease_argument",)


def test_authority_objects_reject_serialization_and_released_locator(tmp_path: Path) -> None:
    """Keep lease and group capabilities opaque and unusable after release."""
    import pickle

    manager, requests, policy = lease_fixture(tmp_path)
    group, lease = captured_candidate(manager, requests, policy)
    assert lease.identity and lease.entries and lease.total_bytes > 0
    with pytest.raises(TypeError):
        pickle.dumps(lease)
    with pytest.raises(TypeError):
        pickle.dumps(group)
    assert manager.release(lease).accepted
    with pytest.raises(RuntimeError):
        _ = lease.directory
    assert manager.release_group(group).accepted
    assert manager.release_group(group).already_settled


def test_foreign_authority_and_invalid_state_mutations_are_rejected(tmp_path: Path) -> None:
    """Reject foreign groups, leases, ports, and state-incompatible release paths."""
    manager, requests, policy = lease_fixture(tmp_path / "one")
    foreign, foreign_requests, foreign_policy = lease_fixture(tmp_path / "two")
    group, lease = captured_candidate(manager, requests, policy)
    foreign_group, foreign_lease = captured_candidate(foreign, foreign_requests, foreign_policy)
    assert manager.acquire(group, foreign_lease).errors == ("invalid_artifact_lease",)
    assert manager.release(foreign_lease).errors == ("invalid_artifact_lease",)
    assert manager.release_group(foreign_group).errors == ("invalid_lease_group",)
    assert manager.retire(group).errors == ("invalid_execution_state",)
    activate(manager, group)
    assert manager.release(lease).errors == ("invalid_execution_state",)
    assert manager.release_group(group).errors == ("invalid_execution_state",)
    admitted = manager.admit((group,))
    assert admitted.accepted and admitted.group is not None
    foreign_port = foreign._execution_port()
    assert foreign_port.retain_for_cleanup(admitted.group).errors == ("invalid_execution_state",)
    assert foreign_port.settle(admitted.group).errors == ("invalid_execution_state",)
    assert manager._execution_port().retain_for_cleanup(group).errors == ("invalid_execution_state",)
    assert manager._execution_port().settle(group).errors == ("invalid_execution_state",)
    assert manager._execution_port().settle(admitted.group).accepted
    assert manager.retire(group).accepted
    assert manager.retire(group).already_settled


def test_capture_busy_and_failed_result_release_reservation(monkeypatch, tmp_path: Path) -> None:
    """Reject physical contention and settle reservations after ordinary capture failure."""
    from topsailai.hooks.artifact_contracts import ArtifactCaptureResult

    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    assert manager._physical.acquire(blocking=False)
    try:
        busy = manager.capture(group, requests, policy=policy)
    finally:
        manager._physical.release()
    assert busy.errors == ("artifact_lease_busy",)
    assert manager.snapshot().pending_captures == 0

    def reject(*args, **kwargs):
        return ArtifactCaptureResult(False, errors=("capture_rejected",))

    monkeypatch.setattr(manager._owner, "capture", reject)
    rejected = manager.capture(group, requests, policy=policy)
    assert rejected.errors == ("capture_rejected",)
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.reserved_tokens == snapshot.reserved_versions == 0
    assert manager.release_group(group).accepted


def test_closed_manager_and_invalid_capture_inputs_reject_without_io(tmp_path: Path) -> None:
    """Validate capture arguments and closed lifecycle before dependent work."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    assert manager.capture(group, list(requests), policy=policy).errors == ("invalid_lease_argument",)
    assert manager.capture(group, requests, policy=object()).errors == ("invalid_lease_argument",)
    assert manager.capture(group, requests, policy=policy, deadline=True).errors == ("invalid_lease_argument",)
    manager.release_group(group)
    assert manager.close(deadline=manager._clock() + 1.0).accepted
    assert manager.begin_candidate().errors == ("artifact_lease_manager_closed",)
    assert manager.admit(()).errors == ("artifact_lease_manager_closed",)


def test_capture_adoption_interruption_keeps_exact_group_owned_token(
    monkeypatch, tmp_path: Path
) -> None:
    """Reconcile a token inserted before adoption metadata can finish."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    primary = KeyboardInterrupt("after adoption token insertion")
    original = manager._publish_token

    def issue_then_interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise primary

    monkeypatch.setattr(manager, "_publish_token", issue_then_interrupt)
    with pytest.raises(KeyboardInterrupt) as raised:
        manager.capture(group, requests, policy=policy)
    assert raised.value is primary
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.reserved_tokens == 0
    assert snapshot.live_tokens == snapshot.stored_versions == snapshot.capture_slots == 1
    assert manager.release_group(group).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 1


def test_capture_return_handoff_interruption_leaves_group_cleanup_authority(
    monkeypatch, tmp_path: Path
) -> None:
    """Keep the successful lease group-owned when the return value is never received."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    primary = KeyboardInterrupt("capture return handoff")
    real_finish = manager._finish_capture

    def finish_then_interrupt(*args, **kwargs):
        result = real_finish(*args, **kwargs)
        assert result.accepted
        raise primary

    monkeypatch.setattr(manager, "_finish_capture", finish_then_interrupt)
    with pytest.raises(KeyboardInterrupt) as raised:
        manager.capture(group, requests, policy=policy)
    assert raised.value is primary
    assert manager.snapshot().live_tokens == 1
    assert manager.release_group(group).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 1


def test_capture_caller_first_instruction_interruption_is_group_recoverable(
    tmp_path: Path,
) -> None:
    """Retain exact cleanup authority when caller code interrupts immediately after return."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    primary = KeyboardInterrupt("caller first instruction")

    def caller() -> None:
        result = manager.capture(group, requests, policy=policy)
        assert result.accepted
        raise primary

    with pytest.raises(KeyboardInterrupt) as raised:
        caller()
    assert raised.value is primary
    assert manager.snapshot().live_tokens == 1
    assert manager.release_group(group).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 1


def test_close_timeout_can_be_followed_by_finite_new_epoch(tmp_path):
    """Pending close retains its epoch until explicit bounded recovery completes."""
    manager, requests, policy = lease_fixture(tmp_path)
    group, lease = captured_candidate(manager, requests, policy)
    captured_directory = lease.directory
    expired = manager._clock() - 1
    first = manager.close(deadline=expired)
    assert not first.accepted and first.cleanup_pending
    assert manager._close_deadline == expired
    assert manager.recovery().retry(deadline=manager._clock() + 1).accepted
    assert not captured_directory.exists()
    assert manager.snapshot().manager_state == "closed"
    assert manager._close_deadline is None
    assert manager.close(deadline=expired).accepted


def test_concurrent_close_can_only_tighten_active_epoch(monkeypatch, tmp_path):
    """A reentrant fresh budget cannot extend physical cleanup in progress."""
    manager, requests, policy = lease_fixture(tmp_path)
    captured_candidate(manager, requests, policy)
    original = manager._owner.dispose
    observed = []
    def dispose(artifact):
        """Attempt a nested longer budget while the exact physical lock is held."""
        before = manager._close_deadline
        nested = manager.close(deadline=manager._clock() + 100)
        observed.append((before, manager._close_deadline, nested))
        return original(artifact)
    monkeypatch.setattr(manager._owner, "dispose", dispose)
    assert manager.close(deadline=manager._clock() + 1).accepted
    assert len(observed) == 1
    before, after, nested = observed[0]
    assert before == after
    assert not nested.accepted and nested.cleanup_pending
    assert manager._close_deadline is None
    assert manager._close_attempts == 0
