"""Focused regressions for U07 artifact cleanup lifecycle retries."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from topsailai.hooks import (
    ArtifactCaptureOwner,
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ExecutablePlatformPolicy,
)
from topsailai.hooks.artifact_identity import native_runtime_fingerprint


def _native_bytes() -> bytes:
    """Return a minimal native-script header matching this host."""
    machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
    return (
        b"\x7fELF"
        + bytes([2 if struct.calcsize("P") == 8 else 1])
        + b"\x00" * 13
        + machine.to_bytes(2, "little")
        + b"data"
    )


def _owner(tmp_path: Path, count: int = 1):
    """Create one native-script owner with an exact multi-entry inventory."""
    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    source_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    data = _native_bytes()
    policy = ExecutablePlatformPolicy("posix")
    requests = []
    assertions = []
    for index in range(count):
        name = f"native-{index}"
        source = source_root / name
        source.write_bytes(data)
        source.chmod(0o500)
        requests.append(ArtifactCaptureRequest(source, "script", name, policy))
        assertions.append(
            ArtifactClosureAssertion(
                source,
                "script",
                name,
                hashlib.sha256(data).hexdigest(),
                native_runtime_fingerprint(),
                f"{index + 1:x}" * 64,
            )
        )
    trust = ArtifactCaptureTrust(
        (source_root,), (), True, tuple(assertions)
    )
    return (
        ArtifactCaptureOwner(artifact_root=str(artifact_root), trust=trust),
        tuple(requests),
        artifact_root,
    )


def test_cleanup_retry_continues_after_partial_multi_entry_removal(
    monkeypatch, tmp_path: Path
) -> None:
    """Retry only exact remaining entries after a later directory removal fails."""
    import topsailai.hooks.artifact_cleanup as cleanup

    owner, requests, artifact_root = _owner(tmp_path, count=2)
    result = owner.capture(requests)
    assert result.accepted and result.artifact is not None
    capture_directory = result.artifact.directory
    real_rmdir = cleanup.os.rmdir
    failed = False

    def fail_second_entry(path, *args, **kwargs):
        nonlocal failed
        if path == "entry-000001" and not failed:
            failed = True
            raise OSError("fixture later-entry removal failure")
        return real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(cleanup.os, "rmdir", fail_second_entry)
    disposed = owner.dispose(result.artifact)
    assert disposed.cleanup_pending
    assert not (capture_directory / "entry-000000").exists()
    assert (capture_directory / "entry-000001").exists()
    debt_id = owner.cleanup_debts()[0].debt_id

    monkeypatch.setattr(cleanup.os, "rmdir", real_rmdir)
    assert owner.retry_cleanup(debt_id)
    assert owner.cleanup_debts() == ()
    assert not capture_directory.exists() and not list(artifact_root.iterdir())


def test_tree_removal_close_error_retains_nonretryable_uncertainty(
    monkeypatch, tmp_path: Path
) -> None:
    """Keep bounded close uncertainty after the artifact tree is removed."""
    import topsailai.hooks.artifact_cleanup as cleanup

    owner, requests, artifact_root = _owner(tmp_path)
    result = owner.capture(requests)
    assert result.accepted and result.artifact is not None
    capture_directory = result.artifact.directory
    real_close = cleanup.os.close
    blocked: set[int] = set()

    def fail_root_close_after_removal(descriptor: int) -> None:
        if not capture_directory.exists() and not blocked:
            blocked.add(descriptor)
            raise OSError("fixture post-removal close failure")
        real_close(descriptor)

    monkeypatch.setattr(cleanup.os, "close", fail_root_close_after_removal)
    disposed = owner.dispose(result.artifact)
    assert disposed.cleanup_pending and not capture_directory.exists()
    debt = owner.cleanup_debts()
    assert len(debt) == 1 and blocked

    monkeypatch.setattr(cleanup.os, "close", real_close)
    assert not owner.retry_cleanup(debt[0].debt_id)
    assert owner.cleanup_debts() == debt and not list(artifact_root.iterdir())
    for descriptor in blocked:
        real_close(descriptor)


def test_nonprivileged_capture_dispose_removes_sealed_artifact(tmp_path: Path) -> None:
    """Complete capture and disposal under a real nonprivileged identity."""
    setpriv = shutil.which("setpriv")
    assert setpriv is not None
    case = tmp_path / "nonprivileged-cleanup"
    case.mkdir(mode=0o755)
    for parent in (tmp_path.parent, tmp_path):
        parent.chmod(0o755)
    os.chown(case, 65534, 65534)
    source_root = Path(__file__).resolve().parents[3]
    probe = r'''
import hashlib
import pathlib
import platform
import struct
from topsailai.hooks import ArtifactCaptureOwner, ArtifactCaptureRequest, ArtifactCaptureTrust, ArtifactClosureAssertion, ExecutablePlatformPolicy
from topsailai.hooks.artifact_identity import native_runtime_fingerprint
base = pathlib.Path(__import__("sys").argv[1])
source_root = base / "source"
artifact_root = base / "artifacts"
source_root.mkdir(mode=0o700)
artifact_root.mkdir(mode=0o700)
machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
data = b"\x7fELF" + bytes([2 if struct.calcsize("P") == 8 else 1]) + b"\x00" * 13 + machine.to_bytes(2, "little") + b"data"
source = source_root / "native"
source.write_bytes(data)
source.chmod(0o500)
policy = ExecutablePlatformPolicy("posix")
request = ArtifactCaptureRequest(source, "script", "native", policy)
assertion = ArtifactClosureAssertion(source, "script", "native", hashlib.sha256(data).hexdigest(), native_runtime_fingerprint(), "a" * 64)
owner = ArtifactCaptureOwner(artifact_root=str(artifact_root), trust=ArtifactCaptureTrust((source_root,), (), True, (assertion,)))
result = owner.capture((request,))
assert result.accepted and result.artifact is not None
capture = result.artifact.directory
disposed = owner.dispose(result.artifact)
assert disposed.accepted and not disposed.cleanup_pending
assert owner.cleanup_debts() == () and not capture.exists() and not list(artifact_root.iterdir())
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[4])
    environment["TOPSAILAI_HOME"] = str(case / "home")
    environment["TOPSAILAI_WORK_FOLDER"] = str(case)
    completed = subprocess.run(
        [
            setpriv,
            "--reuid=65534",
            "--regid=65534",
            "--clear-groups",
            sys.executable,
            "-c",
            probe,
            str(case),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr


def test_cleanup_chain_prioritizes_host_interruption_in_both_orders(
    monkeypatch, tmp_path: Path
) -> None:
    """Keep the exact host interruption across multi-descriptor public cleanup."""
    import pytest
    import topsailai.hooks.artifact_cleanup as cleanup
    from topsailai.hooks import get_artifact_recovery_owner

    for order in ("ordinary-host", "host-ordinary"):
        case = tmp_path / order
        case.mkdir()
        owner, requests, _ = _owner(case, count=2)
        result = owner.capture(requests)
        assert result.artifact is not None
        real_close = cleanup.os.close
        errors = (
            (OSError("ordinary close"), KeyboardInterrupt("host close"))
            if order == "ordinary-host"
            else (KeyboardInterrupt("host close"), OSError("ordinary close"))
        )
        raised_errors: list[BaseException] = []

        def ordered_close(descriptor: int) -> None:
            real_close(descriptor)
            if len(raised_errors) < len(errors):
                error = errors[len(raised_errors)]
                raised_errors.append(error)
                raise error

        monkeypatch.setattr(cleanup.os, "close", ordered_close)
        with pytest.raises(KeyboardInterrupt) as raised:
            owner.close()
        host = next(error for error in errors if isinstance(error, KeyboardInterrupt))
        assert raised.value is host
        assert get_artifact_recovery_owner(host) is owner
        assert len(raised_errors) == 2
        assert len(owner.cleanup_debts()) == 1
        monkeypatch.setattr(cleanup.os, "close", real_close)


def test_nonprivileged_public_capture_rejects_nonexecutable_source(tmp_path: Path) -> None:
    """Prove real nonprivileged public admission rejects missing execute authority."""
    setpriv = shutil.which("setpriv")
    assert setpriv is not None
    case = tmp_path / "nonprivileged-execute-negative"
    case.mkdir(mode=0o755)
    for parent in (tmp_path.parent, tmp_path):
        parent.chmod(0o755)
    os.chown(case, 65534, 65534)
    probe = r'''
import hashlib
import pathlib
from topsailai.hooks import ArtifactCaptureOwner, ArtifactCaptureRequest, ArtifactCaptureTrust, ArtifactClosureAssertion, ExecutablePlatformPolicy
from topsailai.hooks.artifact_identity import native_runtime_fingerprint
base = pathlib.Path(__import__("sys").argv[1])
source_root, artifact_root = base / "source", base / "artifacts"
source_root.mkdir(mode=0o700); artifact_root.mkdir(mode=0o700)
data = b"not-executable"
source = source_root / "native"; source.write_bytes(data); source.chmod(0o400)
request = ArtifactCaptureRequest(source, "script", "native", ExecutablePlatformPolicy("posix"))
assertion = ArtifactClosureAssertion(source, "script", "native", hashlib.sha256(data).hexdigest(), native_runtime_fingerprint(), "b" * 64)
owner = ArtifactCaptureOwner(artifact_root=str(artifact_root), trust=ArtifactCaptureTrust((source_root,), (), True, (assertion,)))
result = owner.capture((request,))
assert result.errors == ("trust_rejected",) and result.artifact is None
assert not list(artifact_root.iterdir()) and owner.cleanup_debts() == ()
owner.close()
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[4])
    environment["TOPSAILAI_HOME"] = str(case / "home")
    environment["TOPSAILAI_WORK_FOLDER"] = str(case)
    completed = subprocess.run(
        [setpriv, "--reuid=65534", "--regid=65534", "--clear-groups",
         sys.executable, "-c", probe, str(case)],
        check=False, capture_output=True, text=True, env=environment,
    )
    assert completed.returncode == 0, completed.stderr

def test_public_capture_ignores_unrelated_outer_host_exception(
    monkeypatch, tmp_path: Path
) -> None:
    """Treat only the current capture scope as primary exception authority."""
    import pytest
    import topsailai.hooks.artifact_cleanup as cleanup

    owner, requests, _ = _owner(tmp_path)
    close_primary = SystemExit("current close interruption")
    real_close = cleanup.os.close
    injected = False

    def interrupt_close(descriptor: int) -> None:
        nonlocal injected
        real_close(descriptor)
        if not injected:
            injected = True
            raise close_primary

    monkeypatch.setattr(cleanup.os, "close", interrupt_close)
    try:
        raise KeyboardInterrupt("unrelated caller exception")
    except KeyboardInterrupt:
        with pytest.raises(SystemExit) as raised:
            owner.capture(requests)
    assert raised.value is close_primary


def test_ordinary_failure_cleanup_host_interruptions_remain_recoverable(
    monkeypatch, tmp_path: Path
) -> None:
    """Attach recovery authority for host interruption in each failure-cleanup phase."""
    import pytest
    import topsailai.hooks.artifact_cleanup as cleanup
    import topsailai.hooks.artifact_store as store
    from topsailai.hooks import get_artifact_recovery_owner
    from topsailai.hooks.artifact_validation import ArtifactValidationError

    for phase in ("source-close", "cleanup-root-open"):
        case = tmp_path / phase
        case.mkdir()
        owner, requests, artifact_root = _owner(case)
        primary = KeyboardInterrupt(f"{phase} interruption")
        real_copy = store.ArtifactCaptureOwner._copy_source
        real_close = cleanup.os.close
        real_open = cleanup.os.open
        copy_failed = False
        injected = False

        def fail_copy(*args, **kwargs):
            nonlocal copy_failed
            copy_failed = True
            raise ArtifactValidationError("trust_rejected")

        def interrupt_source_close(descriptor: int) -> None:
            nonlocal injected
            real_close(descriptor)
            if phase == "source-close" and copy_failed and not injected:
                injected = True
                raise primary

        def interrupt_cleanup_open(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal injected
            if (
                phase == "cleanup-root-open"
                and copy_failed
                and not injected
                and Path(path) == artifact_root
            ):
                injected = True
                raise primary
            return real_open(path, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(store.ArtifactCaptureOwner, "_copy_source", fail_copy)
        monkeypatch.setattr(cleanup.os, "close", interrupt_source_close)
        monkeypatch.setattr(cleanup.os, "open", interrupt_cleanup_open)
        with pytest.raises(KeyboardInterrupt) as raised:
            owner.capture(requests)
        assert raised.value is primary
        assert get_artifact_recovery_owner(primary) is owner
        debts = owner.cleanup_debts()
        assert len(debts) == 1
        assert owner._slots[debts[0].debt_id].ledger.has_outstanding()
        monkeypatch.setattr(store.ArtifactCaptureOwner, "_copy_source", real_copy)
        monkeypatch.setattr(cleanup.os, "close", real_close)
        monkeypatch.setattr(cleanup.os, "open", real_open)



def test_ordinary_failure_checkpoint_interruption_keeps_cleanup_authority(
    monkeypatch, tmp_path: Path
) -> None:
    """Arm cleanup before post-failure arbitration can host-interrupt."""
    import pytest
    import topsailai.hooks.artifact_store as store
    from topsailai.hooks.artifact_validation import ArtifactValidationError

    owner, requests, artifact_root = _owner(tmp_path)
    primary = KeyboardInterrupt("post-failure checkpoint interruption")
    copy_failed = checkpoint_reached = False
    later_io: list[str] = []
    real_open = store.os.open

    class InterruptingEvent(__import__("threading").Event):
        """Interrupt only the checkpoint after the ordinary copy failure."""

        def is_set(self) -> bool:
            nonlocal checkpoint_reached
            if copy_failed:
                checkpoint_reached = True
                raise primary
            return False

    def fail_copy(*args, **kwargs):
        nonlocal copy_failed
        copy_failed = True
        raise ArtifactValidationError("trust_rejected")

    def observe_open(*args, **kwargs):
        if checkpoint_reached:
            later_io.append("open")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(store.ArtifactCaptureOwner, "_copy_source", fail_copy)
    monkeypatch.setattr(store.os, "open", observe_open)
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_issue", lambda *a, **k: pytest.fail("issue"))
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_seal_and_sync", lambda *a, **k: pytest.fail("seal"))
    with pytest.raises(KeyboardInterrupt) as raised:
        owner.capture(requests, cancellation=InterruptingEvent())
    assert raised.value is primary and checkpoint_reached
    assert owner.cleanup_debts() == () and not list(artifact_root.iterdir())
    assert later_io == ["open", "open"]


def test_real_source_close_failure_blocks_seal_and_retains_debt(
    monkeypatch, tmp_path: Path
) -> None:
    """Exercise a real ambiguous source close through the public capture API."""
    import topsailai.hooks.artifact_cleanup as cleanup
    import topsailai.hooks.artifact_store as store

    owner, requests, _ = _owner(tmp_path)
    source_path = requests[0].source_path
    real_close = cleanup.os.close
    close_attempts = seal_calls = 0

    def ambiguous_source_close(descriptor: int) -> None:
        nonlocal close_attempts
        target = os.readlink(f"/proc/self/fd/{descriptor}")
        if target == str(source_path):
            close_attempts += 1
            real_close(descriptor)
            raise OSError("ambiguous source close")
        real_close(descriptor)

    def forbidden_seal(*args, **kwargs):
        nonlocal seal_calls
        seal_calls += 1
        raise AssertionError("seal followed unconfirmed source close")

    monkeypatch.setattr(cleanup.os, "close", ambiguous_source_close)
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_seal_and_sync", forbidden_seal)
    result = owner.capture(requests)
    assert result.errors == ("artifact_cleanup_pending",)
    assert close_attempts == 1 and seal_calls == 0
    debts = owner.cleanup_debts()
    assert len(debts) == 1
    records = tuple(owner._slots[debts[0].debt_id].ledger._records.values())
    assert len(records) == 1 and records[0].uncertain_close
    assert not owner.retry_cleanup(debts[0].debt_id) and close_attempts == 1


@pytest.mark.parametrize("liveness", ("deadline", "cancellation"))
def test_empty_capture_checks_liveness_after_descriptor_close(
    monkeypatch, tmp_path: Path, liveness: str
) -> None:
    """Issue no empty artifact when descriptor settlement returns after liveness."""
    import threading
    import topsailai.hooks.artifact_cleanup as cleanup
    import topsailai.hooks.artifact_store as store

    owner, _, _ = _owner(tmp_path)
    clock, cancellation, issued = [0.0], threading.Event(), [0]
    real_close_all = cleanup.DescriptorLedger.close_all

    def late_close_all(self):
        result = real_close_all(self)
        clock[0] = 2.0
        if liveness == "cancellation":
            cancellation.set()
        return result

    def observed_issue(*args, **kwargs):
        issued[0] += 1
        return real_issue(*args, **kwargs)

    real_issue = store.ArtifactCaptureOwner._issue
    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cleanup.DescriptorLedger, "close_all", late_close_all)
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_issue", observed_issue)
    result = owner.capture(
        (), policy=ArtifactCapturePolicy(timeout_ms=1000),
        cancellation=cancellation, deadline=1.0,
    )
    expected = "artifact_capture_cancelled" if liveness == "cancellation" else "artifact_capture_timeout"
    assert result.errors == (expected,) and issued == [0]
    assert owner.cleanup_debts() == ()


@pytest.mark.parametrize("use_boundary_alias", (False, True), ids=("close", "close-descriptor"))
def test_direct_uncertain_close_reentry_is_nonretryable(
    monkeypatch, tmp_path: Path, use_boundary_alias: bool
) -> None:
    """Reject both individual close entry points after close authority is uncertain."""
    from .artifact_handoff_helpers import assert_direct_uncertain_close_is_nonretryable

    assert_direct_uncertain_close_is_nonretryable(
        monkeypatch, tmp_path, use_boundary_alias=use_boundary_alias
    )


def test_direct_reuse_mismatch_closes_only_acquired_external_fd(
    monkeypatch, tmp_path: Path
) -> None:
    """Close the acquired fixture fd when deterministic reuse validation fails."""
    from .artifact_handoff_helpers import assert_direct_uncertain_close_is_nonretryable

    unrelated_path = tmp_path / "direct-close-unrelated"
    unrelated_path.write_bytes(b"unrelated")
    opened: dict[str, int] = {}

    def force_reuse_mismatch(path, flags) -> int:
        """Occupy the historical integer and return a second owned descriptor."""
        opened["unrelated"] = os.open(unrelated_path, os.O_RDONLY)
        opened["external"] = os.open(path, flags)
        return opened["external"]

    try:
        with pytest.raises(AssertionError):
            assert_direct_uncertain_close_is_nonretryable(
                monkeypatch,
                tmp_path,
                use_boundary_alias=False,
                external_open=force_reuse_mismatch,
            )
        assert os.read(opened["unrelated"], 9) == b"unrelated"
        with pytest.raises(OSError):
            os.fstat(opened["external"])
    finally:
        if "unrelated" in opened:
            os.close(opened["unrelated"])


def test_public_source_close_reentry_retains_owner_bound_debt(
    monkeypatch, tmp_path: Path
) -> None:
    """Keep public recovery authority when source-finalization close is re-entered."""
    from .artifact_handoff_helpers import (
        assert_public_source_close_reentry_is_nonretryable,
    )
    from .test_hook_artifact_ownership import _fixture

    owner, request, artifact_root = _fixture(tmp_path)
    assert_public_source_close_reentry_is_nonretryable(
        monkeypatch, tmp_path, owner, request, artifact_root
    )
