"""Managed recovery isolation tests for U08 artifact leases."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    captured_candidate,
    lease_fixture,
)
from topsailai.hooks.artifact_leases import get_artifact_lease_recovery
from topsailai.hooks.artifact_store import get_artifact_recovery_owner


def test_managed_capture_exception_exposes_facade_not_physical_owner(
    monkeypatch, tmp_path: Path
) -> None:
    """Route framework-created recovery authority through the restricted facade."""
    manager, requests, policy = lease_fixture(tmp_path)
    primary = KeyboardInterrupt("managed capture")

    def fail(*args, **kwargs):
        raise primary

    monkeypatch.setattr(manager._owner, "_capture_reserved", fail)
    group = manager.begin_candidate().group
    assert group is not None
    with pytest.raises(KeyboardInterrupt) as raised:
        manager.capture(group, requests, policy=policy)
    assert raised.value is primary
    assert get_artifact_recovery_owner(primary) is None
    assert get_artifact_lease_recovery(primary) is manager.recovery()
    assert not hasattr(manager.recovery(), "close")


def test_managed_recovery_of_failed_b_cannot_release_live_a(
    monkeypatch, tmp_path: Path
) -> None:
    """Keep A readable and charged while permitted recovery handles failed B."""
    manager, requests, policy = lease_fixture(tmp_path)
    _, lease_a = captured_candidate(manager, requests, policy)
    path_a = lease_a.directory / lease_a.entries[0].relative_path
    primary = SystemExit("B interrupted")
    real_capture = manager._owner._capture_reserved

    def fail_b(*args, **kwargs):
        raise primary

    monkeypatch.setattr(manager._owner, "_capture_reserved", fail_b)
    group_b = manager.begin_candidate().group
    assert group_b is not None
    with pytest.raises(SystemExit):
        manager.capture(group_b, requests, policy=policy)
    facade = get_artifact_lease_recovery(primary)
    assert facade is manager.recovery()
    monkeypatch.setattr(manager._owner, "_capture_reserved", real_capture)
    facade.retry(deadline=manager._clock() + 1.0)
    assert path_a.read_bytes() and not lease_a.released
    assert manager.snapshot().live_tokens == 1


def test_interruption_after_physical_issue_settles_b_without_touching_a(
    monkeypatch, tmp_path: Path
) -> None:
    """Recover B by its bound receipt when U07 cannot return the issued artifact."""
    manager, requests, policy = lease_fixture(tmp_path)
    _, lease_a = captured_candidate(manager, requests, policy)
    path_a = lease_a.directory / lease_a.entries[0].relative_path
    primary = KeyboardInterrupt("after physical issue")
    real_issue = manager._owner._issue

    def issue_then_interrupt(*args, **kwargs):
        real_issue(*args, **kwargs)
        raise primary

    monkeypatch.setattr(manager._owner, "_issue", issue_then_interrupt)
    group_b = manager.begin_candidate().group
    assert group_b is not None
    with pytest.raises(KeyboardInterrupt) as raised:
        manager.capture(group_b, requests, policy=policy)
    assert raised.value is primary
    assert get_artifact_recovery_owner(primary) is None
    assert get_artifact_lease_recovery(primary) is manager.recovery()
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.reserved_tokens == 0
    assert snapshot.live_tokens == snapshot.stored_versions == snapshot.capture_slots == 1
    assert path_a.read_bytes() and not lease_a.released


def test_capture_completion_revalidates_terminal_group_without_resurrection(
    monkeypatch, tmp_path: Path
) -> None:
    """Reject a late physical result after release terminalizes its candidate."""
    manager, requests, policy = lease_fixture(tmp_path)
    group = manager.begin_candidate().group
    assert group is not None
    real_capture = manager._owner.capture

    def capture_after_release(*args, **kwargs):
        result = real_capture(*args, **kwargs)
        assert manager.release_group(group).accepted
        return result

    monkeypatch.setattr(manager._owner, "capture", capture_after_release)
    result = manager.capture(group, requests, policy=policy)
    assert result.errors == ("invalid_lease_group",)
    assert group.state == "settled"
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.live_tokens == 0
    assert snapshot.capture_slots == snapshot.stored_versions == 0


def test_capture_completion_revalidates_expiry_and_close(tmp_path: Path, monkeypatch) -> None:
    """Never restore candidate authority after expiry or manager close during capture."""
    for action, expected in (
        ("expire", "artifact_candidate_expired"),
        ("close", "artifact_lease_manager_closed"),
    ):
        clock = [10.0]
        manager, requests, policy = lease_fixture(
            tmp_path / action, clock=lambda: clock[0]
        )
        group = manager.begin_candidate().group
        assert group is not None
        real_capture = manager._owner.capture

        def mutate_after_capture(*args, _action=action, **kwargs):
            result = real_capture(*args, **kwargs)
            if _action == "expire":
                clock[0] = group.expires_at
            else:
                manager._state = "closing"
            return result

        monkeypatch.setattr(manager._owner, "capture", mutate_after_capture)
        result = manager.capture(group, requests, policy=policy)
        assert result.errors == (expected,)
        assert manager.snapshot().live_tokens == 0
        assert manager.snapshot().capture_slots == 0
        monkeypatch.setattr(manager._owner, "capture", real_capture)

def test_capture_completion_rechecks_shorter_call_deadline(
    tmp_path: Path, monkeypatch,
) -> None:
    """Reject a successful physical result that returns after the call deadline."""
    clock = [0.0]
    manager, requests, policy = lease_fixture(tmp_path, clock=lambda: clock[0])
    group = manager.begin_candidate().group
    assert group is not None
    real_capture = manager._owner.capture

    def finish_after_deadline(*args, **kwargs):
        result = real_capture(*args, **kwargs)
        clock[0] = 2.0
        return result

    monkeypatch.setattr(manager._owner, "capture", finish_after_deadline)
    result = manager.capture(group, requests, policy=policy, deadline=1.0)
    assert result.errors == ("artifact_lease_timeout",)
    snapshot = manager.snapshot()
    assert snapshot.pending_captures == snapshot.reserved_tokens == 0
    assert snapshot.live_tokens == snapshot.capture_slots == 0



def test_capture_busy_keeps_existing_pending_receipt_charged(tmp_path: Path) -> None:
    """Reject another candidate while one receipt is pending without losing its charge."""
    manager, requests, policy = lease_fixture(tmp_path)
    first = manager.begin_candidate().group
    second = manager.begin_candidate().group
    assert first is not None and second is not None
    reserved = manager._reserve_capture(first, requests, policy, None)
    assert reserved.accepted and reserved.receipt is not None
    before = manager.snapshot()
    result = manager.capture(second, requests, policy=policy)
    assert result.errors == ("artifact_lease_busy",)
    after = manager.snapshot()
    assert after.pending_captures == before.pending_captures == 1
    assert after.reserved_tokens == before.reserved_tokens == 1
    manager._rollback_receipt(reserved.receipt)
    assert manager.snapshot().pending_captures == 0
