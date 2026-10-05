"""Focused U07 ownership, cleanup, and deadline tests."""

from __future__ import annotations

import hashlib
import platform
import struct
import threading
import time
from pathlib import Path

from topsailai.hooks import (
    ArtifactCaptureOwner,
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ExecutablePlatformPolicy,
)
from topsailai.hooks.artifact_identity import native_runtime_fingerprint
from topsailai.hooks.artifact_cleanup import DescriptorLedger
from topsailai.hooks.artifact_store import get_artifact_recovery_owner


def _fixture(tmp_path: Path):
    root = tmp_path / "source"
    artifacts = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    artifacts.mkdir(mode=0o700)
    source = root / "native"
    machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
    data = b"\x7fELF" + bytes([2 if struct.calcsize("P") == 8 else 1]) + b"\x00" * 13 + machine.to_bytes(2, "little") + b"data"
    source.write_bytes(data)
    source.chmod(0o500)
    policy = ExecutablePlatformPolicy("posix")
    request = ArtifactCaptureRequest(source, "script", "native", policy)
    assertion = ArtifactClosureAssertion(source, "script", "native", hashlib.sha256(data).hexdigest(), native_runtime_fingerprint(), "5" * 64)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), True, (assertion,)))
    return owner, request, artifacts


def test_capture_dispose_close_and_retry_contract(tmp_path: Path) -> None:
    """Dispose exact handles idempotently and reject foreign handles."""
    owner, request, _ = _fixture(tmp_path)
    result = owner.capture((request,))
    assert result.artifact is not None
    disposed = owner.dispose(result.artifact)
    assert disposed.accepted and not disposed.cleanup_pending
    repeated = owner.dispose(result.artifact)
    assert repeated.accepted and repeated.already_disposed
    assert owner.retry_cleanup("unknown") is False
    assert owner.close().accepted
    assert owner.close().already_disposed


def test_capture_cleanup_preserves_foreign_replacements(tmp_path: Path) -> None:
    """Retain debt rather than remove an unexpected child."""
    owner, request, _ = _fixture(tmp_path)
    result = owner.capture((request,))
    assert result.artifact is not None
    directory = result.artifact.directory
    directory.chmod(0o700)
    sentinel = directory / "sentinel"
    sentinel.write_text("foreign", encoding="utf-8")
    dispose = owner.dispose(result.artifact)
    assert dispose.cleanup_pending
    debts = owner.cleanup_debts()
    assert len(debts) == 1 and debts[0].category == "artifact_cleanup_pending"
    assert sentinel.exists()
    sentinel.unlink()
    assert owner.retry_cleanup(debts[0].debt_id)


def test_capture_shared_deadline_and_cancel_precedence(tmp_path: Path) -> None:
    """Reject initial cancellation before expiry and reject elapsed deadlines."""
    owner, request, _ = _fixture(tmp_path)
    event = threading.Event()
    event.set()
    assert owner.capture((request,), cancellation=event, deadline=time.monotonic() - 1).errors == ("artifact_capture_cancelled",)
    assert owner.capture((request,), deadline=time.monotonic() - 1.0).errors == ("artifact_capture_timeout",)
    owner.close()


def test_capture_owner_capacity_includes_live_and_debt(tmp_path: Path) -> None:
    """Count live empty artifacts against the fixed slot capacity."""
    owner, _, _ = _fixture(tmp_path)
    artifacts = [owner.capture(()) for _ in range(16)]
    assert all(item.accepted for item in artifacts)
    assert owner.capture(()).errors == ("artifact_capacity_exceeded",)
    owner.dispose(artifacts[0].artifact)
    assert owner.capture(()).accepted
    owner.close()


def test_capture_finalization_rechecks_liveness(tmp_path: Path) -> None:
    """Reject an already elapsed absolute deadline without creating output."""
    owner, request, artifacts = _fixture(tmp_path)
    result = owner.capture((request,), policy=ArtifactCapturePolicy(timeout_ms=1), deadline=time.monotonic() - 0.1)
    assert result.errors == ("artifact_capture_timeout",)
    assert not list(artifacts.iterdir())
    owner.close()


def test_descriptor_obligation_precedes_open_and_limit_plus_one(monkeypatch, tmp_path: Path) -> None:
    """Reserve before open and reject record 4097 without another open."""
    ledger = DescriptorLedger()
    for _ in range(4096):
        ledger.reserve_uncertain()
    calls = 0

    def fail_if_opened(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("open must not run")

    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.open", fail_if_opened)
    try:
        ledger.open(tmp_path, 0)
    except Exception as exc:
        assert getattr(exc, "token", None) == "artifact_capacity_exceeded"
    else:
        raise AssertionError("descriptor limit accepted")
    assert calls == 0 and ledger.count == 4096


def test_uncertain_open_retains_debt_without_descriptor_authority(monkeypatch, tmp_path: Path) -> None:
    """Keep one uncertain record without inventing a descriptor after interruption."""
    ledger = DescriptorLedger()
    interruption = KeyboardInterrupt("open interrupted")

    def interrupt(*args, **kwargs):
        raise interruption

    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.open", interrupt)
    try:
        ledger.open(tmp_path, 0)
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("interruption was swallowed")
    assert ledger.count == 1 and ledger.has_outstanding()
    assert ledger.close_all() == () and ledger.count == 1




def test_validation_close_failure_retains_uncertain_debt(monkeypatch, tmp_path: Path) -> None:
    """Retain bounded uncertainty without retrying a failed close number."""
    import os

    owner, _, _ = _fixture(tmp_path)
    real_close = os.close
    blocked: set[int] = set()

    def fail_one_descriptor(descriptor: int) -> None:
        blocked.add(descriptor)
        raise OSError("fixture close failure")

    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.close", fail_one_descriptor)
    result = owner.capture(())
    assert result.errors == ("artifact_cleanup_pending",)
    assert result.recovery_owner is owner
    debts = owner.cleanup_debts()
    assert len(debts) == 1 and blocked

    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.close", real_close)
    assert not owner.retry_cleanup(debts[0].debt_id)
    assert owner.cleanup_debts() == debts
    for descriptor in blocked:
        real_close(descriptor)


def test_descriptor_relative_validation_and_cleanup(monkeypatch, tmp_path: Path) -> None:
    """Use pinned parent descriptors for component traversal and cleanup."""
    import os

    owner, request, _ = _fixture(tmp_path)
    real_open = os.open
    relative_opens: list[tuple[object, int | None]] = []

    def observe_open(path, flags, mode=0o777, *, dir_fd=None):
        relative_opens.append((path, dir_fd))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.open", observe_open)
    result = owner.capture((request,))
    assert result.accepted and result.artifact is not None
    assert any(dir_fd is not None and not Path(path).is_absolute() for path, dir_fd in relative_opens)
    before_dispose = len(relative_opens)
    assert owner.dispose(result.artifact).accepted
    assert any(
        dir_fd is not None and not Path(path).is_absolute()
        for path, dir_fd in relative_opens[before_dispose:]
    )
    owner.close()


def test_uncertain_creation_does_not_authorize_deletion(monkeypatch, tmp_path: Path) -> None:
    """Retain debt without deleting a directory whose creation continuity is unknown."""
    owner, request, artifacts = _fixture(tmp_path)
    real_mkdir = Path.mkdir
    interruption = KeyboardInterrupt("creation outcome unknown")

    def create_then_interrupt(path: Path, *args, **kwargs):
        if path.parent == artifacts and path.name.startswith("capture-"):
            real_mkdir(path, *args, **kwargs)
            raise interruption
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", create_then_interrupt)
    try:
        owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is interruption
        assert get_artifact_recovery_owner(exc) is owner
    else:
        raise AssertionError("creation interruption was swallowed")
    created = tuple(artifacts.iterdir())
    assert len(created) == 1 and created[0].is_dir()
    assert owner.close().cleanup_pending
    assert created[0].exists()


def test_close_aggregates_ordinary_failures_and_continues(monkeypatch, tmp_path: Path) -> None:
    """Attempt later slots after one cleanup raises an ordinary exception."""
    owner, _, _ = _fixture(tmp_path)
    first = owner.capture(())
    second = owner.capture(())
    assert first.accepted and second.accepted
    real_cleanup = owner._cleanup_slot
    calls: list[str] = []

    def fail_first(slot):
        calls.append(slot.debt_id)
        if len(calls) == 1:
            raise OSError("fixture cleanup failure")
        return real_cleanup(slot)

    monkeypatch.setattr(owner, "_cleanup_slot", fail_first)
    result = owner.close()
    assert result.cleanup_pending
    assert len(calls) == 2
    monkeypatch.setattr(owner, "_cleanup_slot", real_cleanup)
    assert owner.close().accepted


def test_close_preserves_host_interruption_identity(monkeypatch, tmp_path: Path) -> None:
    """Propagate the exact host interruption and retain unattempted slots."""
    owner, _, _ = _fixture(tmp_path)
    assert owner.capture(()).accepted
    assert owner.capture(()).accepted
    interruption = KeyboardInterrupt("cleanup interrupted")
    calls = 0

    def interrupt(slot):
        nonlocal calls
        calls += 1
        raise interruption

    monkeypatch.setattr(owner, "_cleanup_slot", interrupt)
    try:
        owner.close()
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("cleanup interruption was swallowed")
    assert calls == 1
def test_host_interruption_keeps_primary_identity_and_recovery_owner(monkeypatch, tmp_path: Path) -> None:
    """Propagate the exact interruption while exposing bounded recovery authority."""
    owner, request, _ = _fixture(tmp_path)
    interruption = KeyboardInterrupt("mkdir interrupted")

    def interrupt(*args, **kwargs):
        raise interruption

    monkeypatch.setattr(Path, "mkdir", interrupt)
    try:
        owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is interruption
        assert get_artifact_recovery_owner(exc) is owner
    else:
        raise AssertionError("interruption was swallowed")
    assert len(owner.cleanup_debts()) == 1



def test_uncertain_close_debts_exhaust_slots_without_more_io(
    monkeypatch, tmp_path: Path
) -> None:
    """Keep sixteen uncertain-close slots and reject before more filesystem I/O."""
    import os

    owner, _, _ = _fixture(tmp_path)
    real_open = os.open
    real_close = os.close
    open_calls = 0
    blocked: set[int] = set()

    def observe_open(*args, **kwargs):
        nonlocal open_calls
        open_calls += 1
        return real_open(*args, **kwargs)

    def reject_close(descriptor: int) -> None:
        blocked.add(descriptor)
        raise OSError("fixture close failure")

    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.open", observe_open)
    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.close", reject_close)
    policy = ArtifactCapturePolicy(max_file_bytes=1, max_total_bytes=1)
    failures = [owner.capture((), policy=policy) for _ in range(16)]
    assert all(item.errors == ("artifact_cleanup_pending",) for item in failures)
    assert all(item.recovery_owner is owner for item in failures)
    assert len(owner.cleanup_debts()) == 16

    before_rejection = open_calls
    rejected = owner.capture((), policy=policy)
    assert rejected.errors == ("artifact_capacity_exceeded",)
    assert open_calls == before_rejection

    debt_id = owner.cleanup_debts()[0].debt_id
    monkeypatch.setattr("topsailai.hooks.artifact_cleanup.os.close", real_close)
    assert not owner.retry_cleanup(debt_id)
    assert len(owner.cleanup_debts()) == 16
    assert owner.capture((), policy=policy).errors == ("artifact_capacity_exceeded",)
    assert open_calls == before_rejection
    for descriptor in blocked:
        real_close(descriptor)



def test_capture_interruption_after_issuance_confirms_cleanup(monkeypatch, tmp_path: Path) -> None:
    """Propagate an issuance interruption after confirmed exact cleanup."""
    owner, request, artifacts = _fixture(tmp_path)
    real_issue = owner._issue
    interruption = KeyboardInterrupt("issued object handoff interrupted")

    def issue_then_interrupt(*args, **kwargs):
        artifact = real_issue(*args, **kwargs)
        assert artifact._issuer is owner
        raise interruption

    monkeypatch.setattr(owner, "_issue", issue_then_interrupt)
    try:
        owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is interruption
        assert get_artifact_recovery_owner(exc) is None
    else:
        raise AssertionError("handoff interruption was swallowed")
    assert owner.cleanup_debts() == ()
    assert not list(artifacts.iterdir())
    assert owner.close().accepted


def test_context_cleanup_preserves_body_exception(monkeypatch, tmp_path: Path) -> None:
    """Keep the body exception primary and expose cleanup recovery diagnostics."""
    owner, _, _ = _fixture(tmp_path)
    assert owner.capture(()).accepted
    body_error = RuntimeError("body failure")
    cleanup_error = KeyboardInterrupt("cleanup interruption")

    def interrupt_cleanup():
        raise cleanup_error

    monkeypatch.setattr(owner, "close", interrupt_cleanup)
    try:
        with owner:
            raise body_error
    except RuntimeError as exc:
        assert exc is body_error
        assert get_artifact_recovery_owner(exc) is owner
        assert any("KeyboardInterrupt" in note for note in exc.__notes__)
    else:
        raise AssertionError("body exception was suppressed")


def test_deadline_covers_lock_validation_copy_fsync_and_finalization(
    monkeypatch, tmp_path: Path
) -> None:
    """Reject late results at each cooperative operation boundary and clean up."""
    import topsailai.hooks.artifact_store as store

    phases = ("lock", "validation", "copy", "fsync", "finalization")
    for phase in phases:
        case = tmp_path / phase
        case.mkdir()
        owner, request, artifacts = _fixture(case)
        clock = [0.0]
        monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
        if phase == "lock":
            real_lock = owner._lock

            class LateLock:
                """Advance the controlled clock while lock acquisition waits."""

                def __enter__(self):
                    real_lock.acquire()
                    clock[0] = 2.0
                    return self

                def __exit__(self, *args):
                    real_lock.release()

            owner._lock = LateLock()
        elif phase == "validation":
            real_validation = store.validate_artifact_root

            def late_validation(*args, **kwargs):
                value = real_validation(*args, **kwargs)
                clock[0] = 2.0
                return value

            monkeypatch.setattr(store, "validate_artifact_root", late_validation)
        elif phase == "copy":
            real_read = store.os.read

            def late_read(descriptor: int, size: int):
                value = real_read(descriptor, size)
                if store.os.readlink(f"/proc/self/fd/{descriptor}") == str(request.source_path):
                    clock[0] = 2.0
                return value

            monkeypatch.setattr(store.os, "read", late_read)
        elif phase == "fsync":
            real_fsync = store.os.fsync

            def late_fsync(descriptor: int):
                real_fsync(descriptor)
                clock[0] = 2.0

            monkeypatch.setattr(store.os, "fsync", late_fsync)
        else:
            real_finalization = store.validate_sealed_artifact

            def late_finalization(*args, **kwargs):
                value = real_finalization(*args, **kwargs)
                clock[0] = 2.0
                return value

            monkeypatch.setattr(store, "validate_sealed_artifact", late_finalization)
        result = owner.capture(
            (request,), policy=ArtifactCapturePolicy(timeout_ms=1000), deadline=1.0
        )
        assert result.errors == ("artifact_capture_timeout",), phase
        assert result.artifact is None and not list(artifacts.iterdir()), phase
        assert owner.cleanup_debts() == (), phase
        owner.close()
        monkeypatch.undo()


def test_deadline_covers_interpreter_hashing(monkeypatch, tmp_path: Path) -> None:
    """Reject an expired result returned by bounded interpreter hashing."""
    import os
    import topsailai.hooks.artifact_store as store
    import topsailai.hooks.artifact_validation as validation
    from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint

    owner, _, artifacts = _fixture(tmp_path)
    owner.close()
    root = tmp_path / "source"
    interpreter = Path("/bin/sh").resolve(strict=True)
    script = root / "deadline-script"
    content = f"#!{interpreter}\nexit 0\n".encode()
    script.write_bytes(content)
    script.chmod(0o500)
    status = interpreter.stat()
    interpreter_digest = hashlib.sha256(interpreter.read_bytes()).hexdigest()
    runtime = shebang_runtime_fingerprint(
        interpreter, interpreter_digest, device=status.st_dev, inode=status.st_ino
    )
    policy = __import__("topsailai.hooks", fromlist=["ExecutablePlatformPolicy"]).ExecutablePlatformPolicy(
        "posix", (str(interpreter),)
    )
    request = ArtifactCaptureRequest(script, "script", script.name, policy)
    assertion = ArtifactClosureAssertion(
        script, "script", script.name, hashlib.sha256(content).hexdigest(), runtime, "6" * 64
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (interpreter,), False, (assertion,)),
    )
    clock = [0.0]
    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    real_hash = validation.hash_descriptor

    def late_hash(*args, **kwargs):
        value = real_hash(*args, **kwargs)
        clock[0] = 2.0
        return value

    monkeypatch.setattr(validation, "hash_descriptor", late_hash)
    result = owner.capture(
        (request,), policy=ArtifactCapturePolicy(timeout_ms=1000), deadline=1.0
    )
    assert result.errors == ("artifact_capture_timeout",)
    assert result.artifact is None and not list(artifacts.iterdir())
    assert owner.cleanup_debts() == ()
    owner.close()


def test_finalization_rejects_mode_link_and_inventory_changes(monkeypatch, tmp_path: Path) -> None:
    """Reject altered sealed metadata, extra hard links, and undeclared children."""
    import os
    import topsailai.hooks.artifact_store as store

    for mutation in ("mode", "hardlink", "inventory"):
        case = tmp_path / mutation
        case.mkdir()
        owner, request, artifacts = _fixture(case)
        real_finalization = store.validate_sealed_artifact

        def mutate_then_validate(directory, identity, entries, children, uid, ledger, checkpoint):
            target = directory / entries[0].relative_path
            if mutation == "mode":
                target.chmod(0o400)
            elif mutation == "hardlink":
                os.link(target, target.with_name("alias"))
            else:
                (directory / "unexpected").write_bytes(b"x")
            return real_finalization(
                directory, identity, entries, children, uid, ledger, checkpoint
            )

        monkeypatch.setattr(store, "validate_sealed_artifact", mutate_then_validate)
        result = owner.capture((request,))
        if mutation == "mode":
            assert result.errors == ("artifact_storage_unavailable",), mutation
            assert owner.cleanup_debts() == () and not list(artifacts.iterdir())
        else:
            assert result.errors == ("artifact_cleanup_pending",), mutation
            assert owner.cleanup_debts(), mutation
        assert result.artifact is None, mutation
        owner.close()
        monkeypatch.undo()


def test_cancellation_and_timeout_override_ordinary_failure_but_not_cleanup(
    monkeypatch, tmp_path: Path
) -> None:
    """Apply cleanup-pending then cancellation then timeout arbitration."""
    import topsailai.hooks.artifact_store as store

    cancel_case = tmp_path / "cancel"
    cancel_case.mkdir()
    owner, request, _ = _fixture(cancel_case)
    event = threading.Event()

    def cancel_and_fail(*args, **kwargs):
        event.set()
        raise OSError("ordinary fixture failure")

    monkeypatch.setattr(store, "open_validated_source", cancel_and_fail)
    result = owner.capture((request,), cancellation=event)
    assert result.errors == ("artifact_capture_cancelled",)
    owner.close()
    monkeypatch.undo()

    timeout_case = tmp_path / "timeout"
    timeout_case.mkdir()
    owner, request, _ = _fixture(timeout_case)
    clock = [0.0]
    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])

    def expire_and_fail(*args, **kwargs):
        clock[0] = 2.0
        raise OSError("ordinary fixture failure")

    monkeypatch.setattr(store, "open_validated_source", expire_and_fail)
    result = owner.capture(
        (request,), policy=ArtifactCapturePolicy(timeout_ms=1000), deadline=1.0
    )
    assert result.errors == ("artifact_capture_timeout",)
    owner.close()
    monkeypatch.undo()

    cleanup_case = tmp_path / "cleanup"
    cleanup_case.mkdir()
    owner, request, _ = _fixture(cleanup_case)
    event = threading.Event()
    real_cleanup = owner._cleanup_slot

    def cancel_fail_with_debt(*args, **kwargs):
        event.set()
        raise OSError("ordinary fixture failure")

    monkeypatch.setattr(store, "open_validated_source", cancel_fail_with_debt)
    monkeypatch.setattr(owner, "_cleanup_slot", lambda slot: False)
    result = owner.capture((request,), cancellation=event)
    assert result.errors == ("artifact_cleanup_pending",)
    assert result.recovery_owner is owner
    monkeypatch.setattr(owner, "_cleanup_slot", real_cleanup)
    owner.close()

    monkeypatch.undo()

    ordinary_cleanup_case = tmp_path / "ordinary-cleanup"
    ordinary_cleanup_case.mkdir()
    owner, request, _ = _fixture(ordinary_cleanup_case)
    real_cleanup = owner._cleanup_slot

    def ordinary_fail_with_debt(*args, **kwargs):
        raise OSError("ordinary fixture failure")

    monkeypatch.setattr(store, "open_validated_source", ordinary_fail_with_debt)
    monkeypatch.setattr(owner, "_cleanup_slot", lambda slot: False)
    result = owner.capture((request,))
    assert result.errors == ("artifact_cleanup_pending",)
    assert result.recovery_owner is owner
    monkeypatch.setattr(owner, "_cleanup_slot", real_cleanup)
    owner.close()
    monkeypatch.undo()

    timeout_cleanup_case = tmp_path / "timeout-cleanup"
    timeout_cleanup_case.mkdir()
    owner, request, _ = _fixture(timeout_cleanup_case)
    real_cleanup = owner._cleanup_slot
    clock = [0.0]
    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])

    def expire_fail_with_debt(*args, **kwargs):
        clock[0] = 2.0
        raise OSError("ordinary fixture failure")

    monkeypatch.setattr(store, "open_validated_source", expire_fail_with_debt)
    monkeypatch.setattr(owner, "_cleanup_slot", lambda slot: False)
    result = owner.capture(
        (request,), policy=ArtifactCapturePolicy(timeout_ms=1000), deadline=1.0
    )
    assert result.errors == ("artifact_cleanup_pending",)
    assert result.recovery_owner is owner
    monkeypatch.setattr(owner, "_cleanup_slot", real_cleanup)
    owner.close()
