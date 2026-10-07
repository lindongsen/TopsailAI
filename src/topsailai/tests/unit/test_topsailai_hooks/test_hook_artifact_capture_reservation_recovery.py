"""Capture reservation regressions for interrupted receipt handoff."""

from __future__ import annotations

import inspect
import threading
from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    captured_candidate,
    lease_fixture,
)
from tests.unit.test_topsailai_hooks.artifact_trace_helpers import (
    composed_line_interruption,
)
from topsailai.hooks.artifact_lease_receipts import ArtifactLeaseReceiptMixin
from topsailai.hooks.artifact_leases import ArtifactLeaseManager
from topsailai.hooks.artifact_physical_lock import ExactPhysicalLock
from topsailai.hooks.artifact_publication import PublicationCell, PublicationImage


@pytest.mark.parametrize(
    ("method", "fragment"),
    (
        (ArtifactLeaseReceiptMixin._reserve_capture, "group._pending_capture = receipt"),
        (ArtifactLeaseReceiptMixin._reserve_capture, "self._receipt = receipt"),
        (
            ArtifactLeaseReceiptMixin._reserve_capture,
            "return CaptureReceiptResult(True, receipt)",
        ),
        (ArtifactLeaseManager.capture, "receipt = reserved.receipt"),
        (ArtifactLeaseManager.capture, "self._acquire_physical(physical_owner)"),
        (ArtifactLeaseManager.capture, "manager_deadline = ("),
    ),
)
def test_capture_rolls_back_interrupted_reservation_handoff(
    tmp_path: Path, method, fragment: str,
) -> None:
    """Preserve the host interruption without leaving capture ownership."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    before_groups = tuple(manager._groups.values())
    before_tokens = tuple(manager._tokens.values())
    lines, first = inspect.getsourcelines(method)
    target = first + next(
        index for index, text in enumerate(lines) if fragment in text
    )
    interruption = KeyboardInterrupt(fragment)

    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager.capture(group, requests, policy=policy)

    assert caught.value is interruption
    assert tuple(manager._groups.values()) == before_groups
    assert tuple(manager._tokens.values()) == before_tokens
    assert group.state == "candidate" and not group._pending_capture
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == 0
    assert snapshot.reserved_tokens == snapshot.reserved_versions == 0
    assert snapshot.capture_slots == snapshot.stored_versions == 0
    assert not manager._physical.locked()
    retried = manager.capture(group, requests, policy=policy)
    assert retried.accepted and retried.lease is not None
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups and final.stored_versions == 0


@pytest.mark.parametrize(
    ("method", "fragment"),
    (
        (ExactPhysicalLock.release_if_owned, "return True"),
        (ArtifactLeaseManager.capture, "if not result.accepted"),
    ),
)
def test_capture_reconciles_interrupted_physical_release_handoff(
    tmp_path: Path, method, fragment: str,
) -> None:
    """Keep exact receipt recovery armed through release and adoption handoff."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    sibling = manager.begin_candidate().group
    assert group is not None and sibling is not None
    before_sibling = sibling
    lines, first = inspect.getsourcelines(method)
    target = first + next(
        index for index, text in enumerate(lines) if fragment in text
    )
    interruption = KeyboardInterrupt(fragment)

    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager.capture(group, requests, policy=policy)

    assert caught.value is interruption
    assert not manager._physical.locked()
    assert manager._receipt is None and not group._pending_capture
    assert sibling is before_sibling and sibling.state == "candidate"
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == 0
    assert snapshot.reserved_tokens == snapshot.reserved_versions == 0
    assert snapshot.capture_slots == snapshot.stored_versions == 0
    retried = manager.capture(group, requests, policy=policy)
    assert retried.accepted and retried.lease is not None
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups and final.stored_versions == 0


def test_capture_release_interruption_recovers_bound_slot_without_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover the exact bound slot when release interrupts before artifact assignment."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    original_release = manager._release_physical
    interruption = KeyboardInterrupt("physical release interrupted")
    interrupted = False

    def interrupt_after_release(owner: object) -> bool:
        """Inject once after releasing the exact physical owner."""
        nonlocal interrupted
        released = original_release(owner)
        if released and not interrupted:
            interrupted = True
            raise interruption
        return released

    monkeypatch.setattr(manager, "_release_physical", interrupt_after_release)
    with pytest.raises(KeyboardInterrupt) as caught:
        manager.capture(group, requests, policy=policy)

    assert caught.value is interruption
    assert not manager._physical.locked()
    assert manager._receipt is None and not group._pending_capture
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.capture_slots == 0
    assert snapshot.stored_versions == 0
    monkeypatch.setattr(manager, "_release_physical", original_release)
    retried = manager.capture(group, requests, policy=policy)
    assert retried.accepted and retried.lease is not None
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups and final.stored_versions == 0



def test_capture_interruption_before_artifact_assignment_recovers_bound_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover the bound slot when capture returns before receipt assignment."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    original_capture = manager._owner.capture
    interruption = KeyboardInterrupt("artifact assignment interrupted")
    interrupted = False

    def interrupt_after_capture(*args, **kwargs):
        """Return from physical capture once, then interrupt manager assignment."""
        nonlocal interrupted
        result = original_capture(*args, **kwargs)
        if result.accepted and not interrupted:
            interrupted = True
            raise interruption
        return result

    monkeypatch.setattr(manager._owner, "capture", interrupt_after_capture)
    with pytest.raises(KeyboardInterrupt) as caught:
        manager.capture(group, requests, policy=policy)

    assert caught.value is interruption
    assert manager._receipt is None and not group._pending_capture
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.capture_slots == 0
    assert snapshot.stored_versions == 0
    monkeypatch.setattr(manager._owner, "capture", original_capture)
    retried = manager.capture(group, requests, policy=policy)
    assert retried.accepted and retried.lease is not None
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups and final.stored_versions == 0


def test_stale_receipt_does_not_clear_new_same_candidate_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep new pending custody when an adopted old receipt loses its return."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    original_finish = manager._finish_capture
    original_capture = manager._owner.capture
    second_entered = threading.Event()
    allow_second = threading.Event()
    second_results = []
    worker_errors: list[BaseException] = []
    calls = 0

    def pause_second_capture(*args, **kwargs):
        """Pause the second physical operation after its exact ownership begins."""
        nonlocal calls
        calls += 1
        if calls == 2:
            second_entered.set()
            if not allow_second.wait(timeout=5):
                raise RuntimeError("second capture was not released")
        return original_capture(*args, **kwargs)

    def run_second_capture() -> None:
        """Run the overlapping capture and retain its public result."""
        try:
            second_results.append(manager.capture(group, requests, policy=policy))
        except BaseException as error:
            worker_errors.append(error)

    worker = threading.Thread(target=run_second_capture)
    interruption = KeyboardInterrupt("old adoption return interrupted")
    old_receipts = []

    def interrupt_after_adoption(receipt, cancellation):
        """Start a new capture after old adoption, then lose the old return."""
        result = original_finish(receipt, cancellation)
        if old_receipts:
            return result
        old_receipts.append(receipt)
        worker.start()
        if not second_entered.wait(timeout=5):
            raise RuntimeError("second capture did not reach physical operation")
        raise interruption

    monkeypatch.setattr(manager._owner, "capture", pause_second_capture)
    monkeypatch.setattr(manager, "_finish_capture", interrupt_after_adoption)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            manager.capture(group, requests, policy=policy)

        assert caught.value is interruption
        assert len(old_receipts) == 1
        old_receipt = old_receipts[0]
        new_receipt = manager._receipt
        assert new_receipt is not None and new_receipt is not old_receipt
        assert group._pending_capture is new_receipt
        assert new_receipt._state == "reserved"
        assert new_receipt._reserved_token and new_receipt._reserved_version
        assert new_receipt._artifact is None and new_receipt._slot is None
        new_owner = manager._physical._owner
        assert new_owner is not None
        source = next(iter(manager._tokens.values()))
        renewed = manager.renew(group, expires_at=group.expires_at)
        acquired = manager.acquire(group, source)
        expected = PublicationImage(0, object(), ())
        cell = PublicationCell(expected)
        replacement = PublicationImage(1, object(), (group,))
        staged = manager._stage_publication(
            cell, group, expected=expected, replacement=replacement,
            old_groups=(), changed=True,
        )
        for rejected in (renewed, acquired, staged):
            assert not rejected.accepted
            assert rejected.errors == ("artifact_lease_busy",)
        assert manager._receipt is new_receipt
        assert group._pending_capture is new_receipt
        assert manager._physical._owner is new_owner
        assert manager._publication_stage is None
    finally:
        allow_second.set()
        if worker.ident is not None:
            worker.join(timeout=5)

    assert not worker.is_alive() and not worker_errors
    assert len(second_results) == 1
    assert second_results[0].accepted and second_results[0].lease is not None
    assert manager._receipt is None and not group._pending_capture
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == 0
    assert snapshot.live_tokens == snapshot.stored_versions == snapshot.capture_slots == 2
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups
    assert final.stored_versions == final.capture_slots == 0


def test_interrupted_adoption_defers_disposal_behind_new_physical_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defer old cleanup without waiting for a newer physical operation."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    original_finish = manager._finish_capture
    original_capture = manager._owner.capture
    second_entered = threading.Event()
    allow_second = threading.Event()
    first_finished = threading.Event()
    first_errors: list[BaseException] = []
    second_results = []
    second_errors: list[BaseException] = []
    calls = 0
    interruption = KeyboardInterrupt("old adoption return interrupted")

    def pause_second_capture(*args, **kwargs):
        """Pause the second capture while it owns physical serialization."""
        nonlocal calls
        calls += 1
        if calls == 2:
            second_entered.set()
            if not allow_second.wait(timeout=5):
                raise RuntimeError("second capture was not released")
        return original_capture(*args, **kwargs)

    def run_second_capture() -> None:
        """Run the newer capture and retain its public result."""
        try:
            second_results.append(manager.capture(group, requests, policy=policy))
        except BaseException as error:
            second_errors.append(error)

    second_worker = threading.Thread(target=run_second_capture)
    old_receipts = []

    def interrupt_after_released_adoption(receipt, cancellation):
        """Release the old lease, start the newer capture, then lose return."""
        result = original_finish(receipt, cancellation)
        if old_receipts:
            return result
        old_receipts.append(receipt)
        assert result.lease is not None
        assert manager.release(result.lease).accepted
        second_worker.start()
        if not second_entered.wait(timeout=5):
            raise RuntimeError("second capture did not reach physical operation")
        raise interruption

    def run_first_capture() -> None:
        """Run old capture recovery while the newer capture remains paused."""
        try:
            manager.capture(group, requests, policy=policy)
        except BaseException as error:
            first_errors.append(error)
        finally:
            first_finished.set()

    monkeypatch.setattr(manager._owner, "capture", pause_second_capture)
    monkeypatch.setattr(manager, "_finish_capture", interrupt_after_released_adoption)
    first_worker = threading.Thread(target=run_first_capture)
    first_worker.start()
    try:
        assert first_finished.wait(timeout=5)
        assert first_errors == [interruption]
        assert len(old_receipts) == 1
        new_receipt = manager._receipt
        assert new_receipt is not None and new_receipt is not old_receipts[0]
        assert group._pending_capture is new_receipt
        assert new_receipt._state == "reserved"
        assert new_receipt._reserved_token and new_receipt._reserved_version
        assert new_receipt._artifact is None and new_receipt._slot is None
        new_owner = manager._physical._owner
        assert new_owner is not None
        snapshot = manager.snapshot()
        assert snapshot.stored_versions == snapshot.capture_slots == 1
        assert snapshot.retired_versions == 1
        assert snapshot.pending_captures == 1
        assert manager._receipt is new_receipt
        assert group._pending_capture is new_receipt
        assert manager._physical._owner is new_owner
    finally:
        allow_second.set()
        first_worker.join(timeout=5)
        if second_worker.ident is not None:
            second_worker.join(timeout=5)

    assert not first_worker.is_alive() and not second_worker.is_alive()
    assert not second_errors and len(second_results) == 1
    assert second_results[0].accepted and second_results[0].lease is not None
    assert manager._receipt is None and not group._pending_capture
    before_close = manager.snapshot()
    assert before_close.stored_versions == before_close.capture_slots == 2
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups
    assert final.stored_versions == final.capture_slots == 0

def test_capture_busy_does_not_release_another_physical_owner(tmp_path: Path) -> None:
    """Keep an existing physical owner locked when another capture is rejected."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    other_owner = object()
    assert manager._physical.acquire(blocking=False, owner=other_owner)

    result = manager.capture(group, requests, policy=policy)

    assert not result.accepted and result.errors == ("artifact_lease_busy",)
    assert manager._physical.locked()
    snapshot = manager.snapshot()
    assert not group._pending_capture and snapshot.pending_captures == 0
    assert snapshot.reserved_tokens == snapshot.reserved_versions == 0
    assert manager._physical.release_if_owned(other_owner)
    retried = manager.capture(group, requests, policy=policy)
    assert retried.accepted and retried.lease is not None
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    assert manager.snapshot().manager_state == "closed"



def test_capture_operation_interruption_releases_exact_physical_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release exact physical ownership when the capture operation interrupts."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    interruption = KeyboardInterrupt("capture operation interrupted")
    original_capture = manager._owner.capture

    def interrupt_capture(*args, **kwargs):
        """Interrupt after exact physical ownership has been established."""
        raise interruption

    monkeypatch.setattr(manager._owner, "capture", interrupt_capture)
    with pytest.raises(KeyboardInterrupt) as caught:
        manager.capture(group, requests, policy=policy)

    assert caught.value is interruption
    assert not manager._physical.locked()
    assert not group._pending_capture and manager._receipt is None
    monkeypatch.setattr(manager._owner, "capture", original_capture)
    retried = manager.capture(group, requests, policy=policy)
    assert retried.accepted and retried.lease is not None
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    assert manager.snapshot().manager_state == "closed"


def test_capture_adoption_interruption_releases_physical_owner_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconcile the issued receipt after physical ownership is released."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    interruption = KeyboardInterrupt("capture adoption interrupted")
    original_finish = manager._finish_capture

    def interrupt_finish(*args, **kwargs):
        """Interrupt before adoption publishes a lease token."""
        raise interruption

    monkeypatch.setattr(manager, "_finish_capture", interrupt_finish)
    with pytest.raises(KeyboardInterrupt) as caught:
        manager.capture(group, requests, policy=policy)

    assert caught.value is interruption
    assert not manager._physical.locked()
    assert not group._pending_capture and manager._receipt is None
    assert manager.snapshot().stored_versions == 0
    monkeypatch.setattr(manager, "_finish_capture", original_finish)
    retried = manager.capture(group, requests, policy=policy)
    assert retried.accepted and retried.lease is not None
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    assert manager.snapshot().manager_state == "closed"

@pytest.mark.parametrize("rollback_fails", (False, True))
def test_interrupted_reservation_rollback_preserves_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rollback_fails: bool,
) -> None:
    """Keep the host primary while handling exact rollback outcomes."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    reserved = manager._reserve_capture(group, requests, policy, None)
    assert reserved.accepted and reserved.receipt is not None
    receipt = reserved.receipt
    original_rollback = manager._rollback_receipt
    if rollback_fails:
        def fail_rollback(_receipt) -> None:
            """Inject one ordinary rollback failure."""
            raise RuntimeError("rollback failed")

        monkeypatch.setattr(manager, "_rollback_receipt", fail_rollback)
    primary = KeyboardInterrupt("capture interrupted")

    manager._rollback_receipt_after_interruption(receipt, primary)

    if rollback_fails:
        assert primary.__notes__ == ["receipt rollback interrupted: RuntimeError"]
        original_rollback(receipt)
    else:
        assert not hasattr(primary, "__notes__")
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    assert manager.snapshot().manager_state == "closed"


class _UnannotatablePrimary(BaseException):
    """Reject diagnostic notes to exercise fail-safe cleanup reporting."""

    def add_note(self, note: str) -> None:
        """Reject one diagnostic note."""
        raise RuntimeError(note)


def test_interrupted_reservation_ignores_note_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not replace a host primary when rollback diagnostics also fail."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    reserved = manager._reserve_capture(group, requests, policy, None)
    assert reserved.accepted and reserved.receipt is not None
    receipt = reserved.receipt
    original_rollback = manager._rollback_receipt

    def fail_rollback(_receipt) -> None:
        """Inject one rollback failure."""
        raise RuntimeError("rollback failed")

    monkeypatch.setattr(manager, "_rollback_receipt", fail_rollback)
    primary = _UnannotatablePrimary()
    manager._rollback_receipt_after_interruption(receipt, primary)

    original_rollback(receipt)
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    assert manager.snapshot().manager_state == "closed"


@pytest.mark.parametrize(
    ("method", "fragment"),
    (
        (ExactPhysicalLock.acquire, "self._owner = token"),
        (ExactPhysicalLock.acquire, "return True"),
        (ArtifactLeaseManager.reclaim, "examined = removed = 0"),
    ),
)
def test_reclaim_releases_interrupted_physical_handoff(
    tmp_path: Path, method, fragment: str,
) -> None:
    """Release exact reclaim ownership across publication and return boundaries."""
    manager, requests, policy = lease_fixture(tmp_path)
    group, lease = captured_candidate(manager, requests, policy)
    assert manager.release(lease).accepted
    assert manager.release_group(group).accepted
    assert manager.snapshot().stored_versions == 1
    lines, first = inspect.getsourcelines(method)
    target = first + next(
        index for index, text in enumerate(lines) if fragment in text
    )
    interruption = KeyboardInterrupt(fragment)

    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager.reclaim(
                deadline=manager._clock() + 1.0, pressure=True
            )

    assert caught.value is interruption
    assert not manager._physical.locked()
    retried = manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True
    )
    assert retried.accepted and not retried.cleanup_pending
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups and final.stored_versions == 0


def test_reclaim_busy_does_not_release_another_physical_owner(
    tmp_path: Path,
) -> None:
    """Keep an existing exact owner when reclaim observes physical contention."""
    manager, requests, policy = lease_fixture(tmp_path)
    group, lease = captured_candidate(manager, requests, policy)
    assert manager.release(lease).accepted
    assert manager.release_group(group).accepted
    other_owner = object()
    assert manager._physical.acquire(blocking=False, owner=other_owner)

    busy = manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True
    )

    assert not busy.accepted and busy.errors == ("artifact_lease_busy",)
    assert busy.cleanup_pending and manager._physical.locked()
    assert manager.snapshot().stored_versions == 1
    assert manager._physical.release_if_owned(other_owner)
    retried = manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True
    )
    assert retried.accepted and not retried.cleanup_pending
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups and final.stored_versions == 0
