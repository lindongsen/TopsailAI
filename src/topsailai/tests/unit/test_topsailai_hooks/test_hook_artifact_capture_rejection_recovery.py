"""Capture completion-rejection cleanup serialization regressions."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import lease_fixture


def test_completion_rejection_defers_disposal_behind_new_physical_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep rejected cleanup non-blocking behind a newer physical capture."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    cancellation = threading.Event()
    original_capture = manager._owner.capture
    original_dispose = manager._dispose_retired_version
    second_entered = threading.Event()
    allow_second = threading.Event()
    second_results = []
    second_errors: list[BaseException] = []
    calls = 0

    def coordinate_captures(*args, **kwargs):
        """Cancel after the first I/O and pause the second under its permit."""
        nonlocal calls
        calls += 1
        if calls == 2:
            second_entered.set()
            if not allow_second.wait(timeout=5):
                raise RuntimeError("second capture was not released")
        result = original_capture(*args, **kwargs)
        if calls == 1:
            cancellation.set()
        return result

    def run_second_capture() -> None:
        """Run the newer capture and retain its public result."""
        try:
            second_results.append(manager.capture(group, requests, policy=policy))
        except BaseException as error:
            second_errors.append(error)

    second_worker = threading.Thread(target=run_second_capture)
    cleanup_observations = []

    def dispose_while_second_owns(version) -> None:
        """Attempt ordinary rejection cleanup during the newer capture."""
        second_worker.start()
        if not second_entered.wait(timeout=5):
            raise RuntimeError("second capture did not reach physical operation")
        new_receipt = manager._receipt
        new_owner = manager._physical._owner
        original_dispose(version)
        cleanup_observations.append(
            (
                new_receipt,
                new_owner,
                manager._receipt,
                group._pending_capture,
                manager._physical._owner,
            )
        )

    monkeypatch.setattr(manager._owner, "capture", coordinate_captures)
    monkeypatch.setattr(manager, "_dispose_retired_version", dispose_while_second_owns)
    try:
        rejected = manager.capture(
            group, requests, policy=policy, cancellation=cancellation
        )

        assert not rejected.accepted
        assert rejected.errors == ("artifact_lease_cancelled",)
        assert len(cleanup_observations) == 1
        new_receipt, new_owner, current_receipt, pending, current_owner = (
            cleanup_observations[0]
        )
        assert new_receipt is not None
        assert current_receipt is new_receipt
        assert pending is new_receipt
        assert current_owner is new_owner and new_owner is not None
        assert new_receipt._state == "reserved"
        assert new_receipt._reserved_token and new_receipt._reserved_version
        assert new_receipt._artifact is None and new_receipt._slot is None
        snapshot = manager.snapshot()
        assert snapshot.pending_captures == 1
        assert snapshot.stored_versions == snapshot.capture_slots == 1
        assert snapshot.retired_versions == 1
    finally:
        allow_second.set()
        if second_worker.ident is not None:
            second_worker.join(timeout=5)

    assert not second_worker.is_alive() and not second_errors
    assert len(second_results) == 1
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


def test_late_completion_defers_cleanup_after_expired_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require a fresh cleanup budget after an expired close sees late capture."""
    clock = [100.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group = manager.begin_candidate().group
    assert group is not None
    original_capture = manager._owner.capture
    original_dispose = manager._owner.dispose
    close_results = []
    disposed = []

    def capture_then_close(*args, **kwargs):
        """Expire close after real I/O but before lease-layer completion."""
        result = original_capture(*args, **kwargs)
        close_results.append(manager.close(deadline=99.0))
        return result

    def observed_dispose(artifact):
        """Record every physical disposal pass."""
        disposed.append(artifact)
        return original_dispose(artifact)

    monkeypatch.setattr(manager._owner, "capture", capture_then_close)
    monkeypatch.setattr(manager._owner, "dispose", observed_dispose)
    rejected = manager.capture(group, requests, policy=policy)

    assert not close_results[0].accepted
    assert close_results[0].errors == ("artifact_lease_timeout",)
    assert rejected.errors == ("artifact_lease_manager_closed",)
    assert disposed == []
    pending = manager.snapshot()
    assert pending.manager_state == "closing"
    assert pending.stored_versions == pending.retired_versions == 1
    assert pending.capture_slots == 1

    reclaimed = manager.reclaim(deadline=101.0, pressure=True)
    assert reclaimed.accepted and reclaimed.removed == 1
    assert len(disposed) == 1
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups
    assert final.stored_versions == final.capture_slots == 0



@pytest.mark.parametrize("recovery_path", ("ordinary_rejection", "interruption_recovery"))
@pytest.mark.parametrize("deadline_case", ("expired_close", "clock_crossing"))
def test_disposal_revalidates_close_budget_after_physical_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovery_path: str,
    deadline_case: str,
) -> None:
    """Defer a newly acquired disposal pass when its close budget has expired."""
    clock = [100.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group = manager.begin_candidate().group
    assert group is not None
    cancellation = threading.Event()
    original_capture = manager._owner.capture
    original_dispose_version = manager._dispose_retired_version
    retained = []

    def capture_then_cancel(*args, **kwargs):
        """Cancel only after the real physical capture succeeds."""
        result = original_capture(*args, **kwargs)
        cancellation.set()
        return result

    monkeypatch.setattr(manager._owner, "capture", capture_then_cancel)
    monkeypatch.setattr(manager, "_dispose_retired_version", retained.append)
    rejected = manager.capture(
        group, requests, policy=policy, cancellation=cancellation
    )
    assert rejected.errors == ("artifact_lease_cancelled",)
    assert len(retained) == 1
    monkeypatch.setattr(manager, "_dispose_retired_version", original_dispose_version)

    original_acquire = manager._acquire_physical
    original_dispose = manager._owner.dispose
    close_results = []
    disposed = []

    def acquire_then_close(owner):
        """Close after exact acquisition and expire authorization before return."""
        acquired = original_acquire(owner)
        assert acquired
        deadline = 99.0 if deadline_case == "expired_close" else 101.0
        close_results.append(manager.close(deadline=deadline))
        if deadline_case == "clock_crossing":
            clock[0] = deadline
        return acquired

    def observed_dispose(artifact):
        """Reject metadata-locked physical I/O and record every disposal pass."""
        assert not manager._lock._is_owned()
        disposed.append(artifact)
        return original_dispose(artifact)

    monkeypatch.setattr(manager, "_acquire_physical", acquire_then_close)
    monkeypatch.setattr(manager._owner, "dispose", observed_dispose)
    if recovery_path == "ordinary_rejection":
        manager._dispose_retired_version(retained[0])
    else:
        interruption = KeyboardInterrupt("post-acquisition close")
        with pytest.raises(KeyboardInterrupt) as caught:
            try:
                raise interruption
            except BaseException as primary:
                manager._dispose_after_interruption(retained[0], primary)
                raise
        assert caught.value is interruption

    assert len(close_results) == 1
    assert not close_results[0].accepted
    expected_error = (
        "artifact_lease_timeout"
        if deadline_case == "expired_close"
        else "artifact_lease_busy"
    )
    assert close_results[0].errors == (expected_error,)
    assert disposed == []
    assert not manager._physical.locked()
    pending = manager.snapshot()
    assert pending.manager_state == "closing"
    assert pending.stored_versions == pending.retired_versions == 1
    assert pending.capture_slots == 1

    monkeypatch.setattr(manager, "_acquire_physical", original_acquire)
    reclaimed = manager.reclaim(deadline=clock[0] + 1.0, pressure=True)
    assert reclaimed.accepted and reclaimed.removed == 1
    assert len(disposed) == 1
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups
    assert final.stored_versions == final.capture_slots == 0

@pytest.mark.parametrize("boundary", ("owner_publication", "callee_return", "caller_instruction"))
def test_disposal_acquisition_interruption_releases_exact_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str,
) -> None:
    """Release exact disposal ownership across every acquisition handoff window."""
    import inspect

    from tests.unit.test_topsailai_hooks.artifact_trace_helpers import (
        composed_line_interruption,
    )
    from topsailai.hooks.artifact_lease_receipts import ArtifactLeaseReceiptMixin
    from topsailai.hooks.artifact_physical_lock import ExactPhysicalLock

    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    cancellation = threading.Event()
    original_capture = manager._owner.capture
    original_dispose = manager._dispose_retired_version
    retained = []

    def capture_then_cancel(*args, **kwargs):
        """Cancel only after the real physical capture completes."""
        result = original_capture(*args, **kwargs)
        cancellation.set()
        return result

    def retain_version(version) -> None:
        """Keep the real rejected version for the interruption boundary."""
        retained.append(version)

    monkeypatch.setattr(manager._owner, "capture", capture_then_cancel)
    monkeypatch.setattr(manager, "_dispose_retired_version", retain_version)
    rejected = manager.capture(
        group, requests, policy=policy, cancellation=cancellation
    )
    assert rejected.errors == ("artifact_lease_cancelled",)
    assert len(retained) == 1
    monkeypatch.setattr(manager, "_dispose_retired_version", original_dispose)
    interruption = KeyboardInterrupt(boundary)

    if boundary == "callee_return":
        original_acquire = manager._acquire_physical

        def acquire_then_interrupt(owner):
            """Lose the successful acquisition return before caller assignment."""
            assert original_acquire(owner)
            raise interruption

        monkeypatch.setattr(manager, "_acquire_physical", acquire_then_interrupt)
        with pytest.raises(KeyboardInterrupt) as caught:
            manager._dispose_retired_version(retained[0])
        monkeypatch.setattr(manager, "_acquire_physical", original_acquire)
    else:
        method = (
            ExactPhysicalLock.acquire
            if boundary == "owner_publication"
            else ArtifactLeaseReceiptMixin._dispose_retired_version
        )
        fragment = "return True" if boundary == "owner_publication" else "result = self._owner.dispose"
        lines, first = inspect.getsourcelines(method)
        target = first + next(
            index for index, text in enumerate(lines) if fragment in text
        )
        with pytest.raises(KeyboardInterrupt) as caught:
            with composed_line_interruption(method.__code__, target, interruption):
                manager._dispose_retired_version(retained[0])

    assert caught.value is interruption
    assert not manager._physical.locked()
    pending = manager.snapshot()
    assert pending.stored_versions == pending.retired_versions == 1
    assert pending.capture_slots == 1
    reclaimed = manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True
    )
    assert reclaimed.accepted and reclaimed.removed == 1
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups
    assert final.stored_versions == final.capture_slots == 0


def test_completion_rejection_recovers_disposal_acquire_lost_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the primary while rejection recovery releases disposal ownership."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    cancellation = threading.Event()
    original_capture = manager._owner.capture
    original_acquire = manager._acquire_physical
    interruption = KeyboardInterrupt("disposal acquisition lost return")
    acquisitions = 0

    def capture_then_cancel(*args, **kwargs):
        """Cancel only after real physical I/O succeeds."""
        result = original_capture(*args, **kwargs)
        cancellation.set()
        return result

    def interrupt_second_acquisition(owner):
        """Interrupt the disposal acquisition after exact owner publication."""
        nonlocal acquisitions
        acquisitions += 1
        acquired = original_acquire(owner)
        if acquisitions == 2:
            assert acquired
            raise interruption
        return acquired

    monkeypatch.setattr(manager._owner, "capture", capture_then_cancel)
    monkeypatch.setattr(manager, "_acquire_physical", interrupt_second_acquisition)
    with pytest.raises(KeyboardInterrupt) as caught:
        manager.capture(
            group, requests, policy=policy, cancellation=cancellation
        )

    assert caught.value is interruption
    assert acquisitions >= 3
    assert not manager._physical.locked()
    monkeypatch.setattr(manager, "_acquire_physical", original_acquire)
    reclaimed = manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True
    )
    assert reclaimed.accepted and not reclaimed.cleanup_pending
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups
    assert final.stored_versions == final.capture_slots == 0


def test_disposal_busy_does_not_release_another_physical_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a sibling physical owner when retired cleanup observes contention."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    cancellation = threading.Event()
    original_capture = manager._owner.capture
    original_dispose = manager._dispose_retired_version
    retained = []

    def capture_then_cancel(*args, **kwargs):
        """Create one real rejected version without bypassing physical capture."""
        result = original_capture(*args, **kwargs)
        cancellation.set()
        return result

    monkeypatch.setattr(manager._owner, "capture", capture_then_cancel)
    monkeypatch.setattr(manager, "_dispose_retired_version", retained.append)
    rejected = manager.capture(
        group, requests, policy=policy, cancellation=cancellation
    )
    assert rejected.errors == ("artifact_lease_cancelled",)
    assert len(retained) == 1
    monkeypatch.setattr(manager, "_dispose_retired_version", original_dispose)
    other_owner = object()
    assert manager._physical.acquire(blocking=False, owner=other_owner)

    manager._dispose_retired_version(retained[0])

    assert manager._physical.locked()
    assert manager._physical._owner is other_owner
    assert manager.snapshot().stored_versions == 1
    assert manager._physical.release_if_owned(other_owner)
    reclaimed = manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True
    )
    assert reclaimed.accepted and reclaimed.removed == 1
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert not manager._groups
    assert final.stored_versions == final.capture_slots == 0
