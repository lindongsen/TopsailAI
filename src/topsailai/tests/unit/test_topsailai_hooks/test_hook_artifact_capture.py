"""Focused API and bounded capture tests for U07 immutable artifacts."""

from __future__ import annotations

import hashlib
import os
import platform
import struct
import threading
from pathlib import Path

import pytest

from topsailai.hooks import (
    ArtifactCaptureOwner,
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    CapturedArtifact,
    ExecutablePlatformPolicy,
    get_artifact_recovery_owner,
)
from topsailai.hooks.artifact_identity import native_runtime_fingerprint

def _owner(tmp_path: Path, data: bytes = b"payload"):
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    source_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    source = source_root / "native"
    machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
    header = b"\x7fELF" + bytes([2 if struct.calcsize("P") == 8 else 1])
    content = header + b"\x00" * 13 + machine.to_bytes(2, "little") + data
    source.write_bytes(content)
    source.chmod(0o500)
    script_policy = ExecutablePlatformPolicy("posix")
    request = ArtifactCaptureRequest(source, "script", "native", script_policy)
    assertion = ArtifactClosureAssertion(
        source, "script", "native", hashlib.sha256(content).hexdigest(),
        native_runtime_fingerprint(), "1" * 64,
    )
    trust = ArtifactCaptureTrust((source_root,), (), True, (assertion,))
    return ArtifactCaptureOwner(artifact_root=str(artifact_root), trust=trust), request, content

def test_capture_public_contract_and_export_identity(tmp_path: Path) -> None:
    """Expose exact frozen records, method signatures, exports, and opaque handles."""
    from tests.unit.test_topsailai_hooks.artifact_contract_helpers import (
        assert_artifact_public_contract,
    )

    owner, request, _ = _owner(tmp_path)
    assert_artifact_public_contract()
    assert "source" not in repr(request)
    with pytest.raises(TypeError):
        CapturedArtifact(object(), "x", (), 0, None)
    owner.close()

def test_capture_validation_precedes_io(tmp_path: Path) -> None:
    """Reject malformed requests before physical root admission."""
    owner, _, _ = _owner(tmp_path)
    result = owner.capture((object(),))
    assert result.errors == ("invalid_artifact_request",)
    assert not list((tmp_path / "artifacts").iterdir())
    owner.close()

def test_empty_capture_is_complete_and_bounded(tmp_path: Path) -> None:
    """Issue deterministic empty artifacts without an output directory."""
    owner, _, _ = _owner(tmp_path)
    first = owner.capture(())
    second = owner.capture(())
    assert first.accepted and second.accepted
    assert first.artifact is not None and second.artifact is not None
    assert first.artifact.identity == second.artifact.identity
    assert first.artifact.entries == () and first.artifact.total_bytes == 0
    try:
        first.artifact.directory
    except RuntimeError as exc:
        assert str(exc) == "empty artifact has no directory"
    owner.close()

def test_capture_inventory_and_byte_boundaries(monkeypatch, tmp_path: Path) -> None:
    """Prove request and owner count/byte boundaries before admission I/O."""
    from tests.unit.test_topsailai_hooks.artifact_capacity_helpers import (
        assert_byte_and_owner_capacity_boundaries,
    )
    owner, request, content = _owner(tmp_path / "single")
    for limit, accepted in (
        (len(content) + 1, True), (len(content), True), (len(content) - 1, False),
    ):
        result = owner.capture(
            (request,), policy=ArtifactCapturePolicy(
                max_entries=1, max_file_bytes=limit, max_total_bytes=limit,
            ),
        )
        assert result.accepted is accepted
        if result.artifact is not None:
            owner.dispose(result.artifact)
    owner.close()
    assert_byte_and_owner_capacity_boundaries(monkeypatch, tmp_path)

def test_capture_all_kinds_from_real_files(tmp_path: Path) -> None:
    """Capture a real native file without executing it."""
    owner, request, content = _owner(tmp_path)
    result = owner.capture((request,))
    assert result.accepted and result.artifact is not None
    captured = result.artifact.directory / result.artifact.entries[0].relative_path
    assert captured.read_bytes() == content
    assert result.artifact.entries[0].content_sha256 == hashlib.sha256(content).hexdigest()
    owner.close()

def test_mixed_capture_is_atomic(tmp_path: Path) -> None:
    """Expose no partial artifact when a later closure is absent."""
    owner, request, _ = _owner(tmp_path)
    missing = ArtifactCaptureRequest(request.source_path.with_name("other"), "script", "other", request.script_policy)
    result = owner.capture((request, missing))
    assert not result.accepted and result.artifact is None
    assert result.errors == ("unsupported_artifact_closure",)
    assert not list((tmp_path / "artifacts").iterdir())
    owner.close()

def test_capture_streaming_overflow_and_short_writes(monkeypatch, tmp_path: Path) -> None:
    """Complete partial writes and reject a source that grows after admission."""
    owner, request, content = _owner(tmp_path)
    real_write = __import__("os").write

    def partial_write(descriptor: int, value) -> int:
        return real_write(descriptor, value[: max(1, len(value) // 2)])

    monkeypatch.setattr("topsailai.hooks.artifact_store.os.write", partial_write)
    result = owner.capture(
        (request,),
        policy=ArtifactCapturePolicy(
            max_file_bytes=len(content), max_total_bytes=len(content)
        ),
    )
    assert result.accepted and result.artifact is not None
    captured = result.artifact.directory / result.artifact.entries[0].relative_path
    assert captured.read_bytes() == content
    owner.dispose(result.artifact)
    owner.close()

    owner, request, content = _owner(tmp_path / "growing")
    real_read = __import__("os").read
    source_reads = 0

    def grow_before_copy(descriptor: int, size: int) -> bytes:
        nonlocal source_reads
        target = __import__("os").readlink(f"/proc/self/fd/{descriptor}")
        if target == str(request.source_path):
            source_reads += 1
            if source_reads == 2:
                with request.source_path.open("ab") as stream:
                    stream.write(b"x")
        return real_read(descriptor, size)

    monkeypatch.setattr("topsailai.hooks.artifact_store.os.read", grow_before_copy)
    rejected = owner.capture(
        (request,),
        policy=ArtifactCapturePolicy(
            max_file_bytes=len(content), max_total_bytes=len(content)
        ),
    )
    assert rejected.errors == ("artifact_byte_limit",)
    assert not list((tmp_path / "growing" / "artifacts").iterdir())
    owner.close()

def test_capture_zero_write_enospc_and_readback_corruption(monkeypatch, tmp_path: Path) -> None:
    """Map non-progress, ENOSPC, and independent read-back corruption safely."""
    import errno
    import os

    owner, request, _ = _owner(tmp_path / "zero")
    monkeypatch.setattr("topsailai.hooks.artifact_store.os.write", lambda *_: 0)
    result = owner.capture((request,))
    assert result.errors == ("artifact_storage_unavailable",)
    assert result.recovery_owner is None
    owner.close()

    owner, request, _ = _owner(tmp_path / "enospc")

    def no_space(*args):
        raise OSError(errno.ENOSPC, "fixture disk full")

    monkeypatch.setattr("topsailai.hooks.artifact_store.os.write", no_space)
    result = owner.capture((request,))
    assert result.errors == ("artifact_storage_unavailable",)
    assert result.recovery_owner is None
    owner.close()

    owner, request, _ = _owner(tmp_path / "corrupt")
    real_read = os.read

    def corrupt_captured_read(descriptor: int, size: int) -> bytes:
        value = real_read(descriptor, size)
        target = os.readlink(f"/proc/self/fd/{descriptor}")
        if value and "/capture-" in target:
            return bytes([value[0] ^ 1]) + value[1:]
        return value

    monkeypatch.setattr("topsailai.hooks.artifact_store.os.read", corrupt_captured_read)
    result = owner.capture((request,))
    assert result.errors == ("artifact_storage_unavailable",)
    assert result.recovery_owner is None
    owner.close()

def test_failed_capture_preserves_prior_success(monkeypatch, tmp_path: Path) -> None:
    """Keep an earlier live artifact usable after an unrelated I/O failure."""
    import errno

    owner, request, content = _owner(tmp_path)
    prior = owner.capture((request,))
    assert prior.accepted and prior.artifact is not None
    prior_path = prior.artifact.directory / prior.artifact.entries[0].relative_path

    def no_space(*args):
        raise OSError(errno.ENOSPC, "fixture disk full")

    monkeypatch.setattr("topsailai.hooks.artifact_store.os.write", no_space)
    failed = owner.capture(
        (request,),
        policy=ArtifactCapturePolicy(
            max_file_bytes=len(content), max_total_bytes=len(content)
        ),
    )
    assert failed.errors == ("artifact_storage_unavailable",)
    assert prior_path.read_bytes() == content
    assert not prior.artifact.disposed
    owner.close()

def test_mixed_late_io_failure_exposes_no_partial_artifact(monkeypatch, tmp_path: Path) -> None:
    """Reject a second-entry write failure without publishing partial inventory."""
    import errno
    import os

    initial_owner, first_request, first_content = _owner(tmp_path)
    initial_owner.close()
    source_root = first_request.source_path.parent
    artifact_root = tmp_path / "artifacts"
    second_source = source_root / "native-two"
    second_content = first_content + b"two"
    second_source.write_bytes(second_content)
    second_source.chmod(0o500)
    second_request = ArtifactCaptureRequest(
        second_source, "script", "native-two", first_request.script_policy
    )
    assertions = (
        ArtifactClosureAssertion(
            first_request.source_path,
            "script",
            "native",
            hashlib.sha256(first_content).hexdigest(),
            native_runtime_fingerprint(),
            "1" * 64,
        ),
        ArtifactClosureAssertion(
            second_source,
            "script",
            "native-two",
            hashlib.sha256(second_content).hexdigest(),
            native_runtime_fingerprint(),
            "2" * 64,
        ),
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifact_root),
        trust=ArtifactCaptureTrust((source_root,), (), True, assertions),
    )
    real_write = os.write

    def fail_second_entry(descriptor: int, value) -> int:
        target = os.readlink(f"/proc/self/fd/{descriptor}")
        if "/entry-000001/" in target:
            raise OSError(errno.ENOSPC, "fixture second-entry failure")
        return real_write(descriptor, value)

    monkeypatch.setattr("topsailai.hooks.artifact_store.os.write", fail_second_entry)
    result = owner.capture((first_request, second_request))
    assert result.errors == ("artifact_storage_unavailable",)
    assert result.artifact is None
    assert not list(artifact_root.iterdir())
    owner.close()

def test_capture_does_not_mutate_runtime_or_execute_target(monkeypatch, tmp_path: Path) -> None:
    """Preserve active Runtime authority without importing or launching targets."""
    import sys
    from topsailai.hooks.artifact_identity import python_runtime_fingerprint
    from topsailai.hooks.artifact_contracts import ArtifactPythonRuntimeAuthority
    from tests.unit.test_topsailai_hooks.artifact_runtime_helpers import (
        assert_capture_preserves_active_runtime,
    )

    owner, _, _ = _owner(tmp_path)
    owner.close()
    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    marker = tmp_path / "executed"
    module = source_root / "danger.py"
    content = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n".encode()
    module.write_bytes(content)
    module.chmod(0o400)
    executable = Path(sys.executable).resolve(strict=True)
    executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    executable_status = executable.stat()
    runtime_digest = python_runtime_fingerprint(
        executable, executable_digest,
        device=executable_status.st_dev, inode=executable_status.st_ino,
    )
    request = ArtifactCaptureRequest(module, "python_source", "danger")
    assertion = ArtifactClosureAssertion(
        module, "python_source", "danger", hashlib.sha256(content).hexdigest(),
        runtime_digest, "9" * 64,
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifact_root),
        trust=ArtifactCaptureTrust(
            (source_root,), (), False, (assertion,),
            ArtifactPythonRuntimeAuthority(executable, executable_digest),
        ),
    )
    assert_capture_preserves_active_runtime(monkeypatch, tmp_path, owner, request)
    assert not marker.exists() and "danger" not in sys.modules
    owner.close()

def test_capture_tokens_and_diagnostics_are_secret_safe(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    """Expose one fixed token without secret paths in enabled logs or diagnostics."""
    import logging
    import topsailai.hooks.artifact_store as store

    owner, request, _ = _owner(tmp_path)
    secret = "secret-fixture-path-and-message"

    def fail(*args, **kwargs):
        raise RuntimeError(secret + str(request.source_path))

    with caplog.at_level(logging.DEBUG):
        monkeypatch.setattr(store, "open_validated_source", fail)
        result = owner.capture((request,))
    assert result.errors == ("artifact_storage_unavailable",)
    rendered = repr(result)
    assert secret not in rendered and str(request.source_path) not in rendered
    assert secret not in caplog.text and str(request.source_path) not in caplog.text
    assert result.artifact is None and result.recovery_owner is None
    owner.close()


@pytest.mark.parametrize(
    ("boundary", "operation_error", "liveness", "expected_token"),
    (
        ("directory-fsync", KeyboardInterrupt("directory host"), "deadline", None),
        ("directory-fsync", OSError("directory ordinary"), "cancellation", "artifact_capture_cancelled"),
        ("captured-read", SystemExit("read host"), "cancellation", None),
        ("captured-read", OSError("read ordinary"), "deadline", "artifact_capture_timeout"),
        ("captured-fsync", KeyboardInterrupt("file host"), "deadline", None),
        ("captured-fsync", OSError("file ordinary"), "cancellation", "artifact_capture_cancelled"),
        ("sealed-validation", SystemExit("validation host"), "cancellation", None),
        ("sealed-validation", OSError("validation ordinary"), "deadline", "artifact_capture_timeout"),
    ),
)
def test_capture_finalization_preserves_host_and_arbitrates_ordinary_error(
    monkeypatch,
    tmp_path: Path,
    boundary: str,
    operation_error: BaseException,
    liveness: str,
    expected_token: str | None,
) -> None:
    """Preserve host identity while liveness arbitrates finalization I/O errors."""
    import topsailai.hooks.artifact_store as store

    owner, request, _ = _owner(tmp_path)
    artifact_root = tmp_path / "artifacts"
    clock = [0.0]
    cancellation = threading.Event()
    issued = 0
    captured_fsyncs = 0
    real_fsync = os.fsync
    real_read = os.read
    real_issue = store.ArtifactCaptureOwner._issue
    real_validate = store.validate_sealed_artifact

    def interrupt() -> None:
        if liveness == "deadline":
            clock[0] = 2.0
        else:
            cancellation.set()
        raise operation_error

    def descriptor_path(descriptor: int) -> str:
        return os.readlink(f"/proc/self/fd/{descriptor}")

    def observed_fsync(descriptor: int) -> None:
        nonlocal captured_fsyncs
        target = descriptor_path(descriptor)
        if boundary == "directory-fsync" and target.endswith("/entry-000000"):
            interrupt()
        if "/capture-" in target and target.endswith("/native"):
            captured_fsyncs += 1
            if boundary == "captured-fsync" and captured_fsyncs == 2:
                interrupt()
        real_fsync(descriptor)

    def observed_read(descriptor: int, size: int) -> bytes:
        target = descriptor_path(descriptor)
        if boundary == "captured-read" and "/capture-" in target:
            interrupt()
        return real_read(descriptor, size)

    def observed_validate(*args, **kwargs) -> None:
        if boundary != "sealed-validation":
            real_validate(*args, **kwargs)
            return
        real_fstat = os.fstat

        def interrupted_fstat(descriptor: int):
            target = descriptor_path(descriptor)
            if "/capture-" in target:
                interrupt()
            return real_fstat(descriptor)

        monkeypatch.setattr(os, "fstat", interrupted_fstat)
        try:
            real_validate(*args, **kwargs)
        finally:
            monkeypatch.setattr(os, "fstat", real_fstat)

    def observed_issue(*args, **kwargs):
        nonlocal issued
        issued += 1
        return real_issue(*args, **kwargs)

    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(store.os, "fsync", observed_fsync)
    monkeypatch.setattr(store.os, "read", observed_read)
    monkeypatch.setattr(store, "validate_sealed_artifact", observed_validate)
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_issue", observed_issue)
    if expected_token is None:
        with pytest.raises(type(operation_error)) as raised:
            owner.capture(
                (request,), policy=ArtifactCapturePolicy(timeout_ms=1000),
                cancellation=cancellation, deadline=1.0,
            )
        assert raised.value is operation_error
    else:
        result = owner.capture(
            (request,), policy=ArtifactCapturePolicy(timeout_ms=1000),
            cancellation=cancellation, deadline=1.0,
        )
        assert result.errors == (expected_token,) and result.artifact is None
    assert issued == 0
    assert not list(artifact_root.iterdir())
    assert owner.cleanup_debts() == ()
    owner.close()


@pytest.mark.parametrize(
    "cleanup_error",
    (SystemExit("cleanup host"), OSError("cleanup ordinary")),
    ids=("host-cleanup", "ordinary-cleanup"),
)
def test_capture_host_primary_survives_outer_cleanup_failure(
    monkeypatch,
    tmp_path: Path,
    cleanup_error: BaseException,
) -> None:
    """Keep the finalization host primary and expose bounded cleanup recovery."""
    import topsailai.hooks.artifact_store as store

    owner, request, _ = _owner(tmp_path)
    artifact_root = tmp_path / "artifacts"
    primary = KeyboardInterrupt("finalization host")
    clock = [0.0]
    finalization_failed = False
    issued = 0
    sealed_validations = 0
    real_fsync = os.fsync
    real_open = os.open
    real_issue = store.ArtifactCaptureOwner._issue
    real_validate = store.validate_sealed_artifact

    def descriptor_path(descriptor: int) -> str:
        return os.readlink(f"/proc/self/fd/{descriptor}")

    def interrupted_fsync(descriptor: int) -> None:
        nonlocal finalization_failed
        target = descriptor_path(descriptor)
        if target.endswith("/entry-000000"):
            finalization_failed = True
            clock[0] = 2.0
            raise primary
        real_fsync(descriptor)

    def interrupted_cleanup_open(path, flags, mode=0o777, *, dir_fd=None):
        if finalization_failed and Path(path) == artifact_root:
            raise cleanup_error
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def observed_validate(*args, **kwargs) -> None:
        nonlocal sealed_validations
        sealed_validations += 1
        real_validate(*args, **kwargs)

    def observed_issue(*args, **kwargs):
        nonlocal issued
        issued += 1
        return real_issue(*args, **kwargs)

    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(os, "fsync", interrupted_fsync)
    monkeypatch.setattr(os, "open", interrupted_cleanup_open)
    monkeypatch.setattr(store, "validate_sealed_artifact", observed_validate)
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_issue", observed_issue)

    with pytest.raises(KeyboardInterrupt) as raised:
        owner.capture(
            (request,),
            policy=ArtifactCapturePolicy(timeout_ms=1000),
            deadline=1.0,
        )
    assert raised.value is primary
    assert get_artifact_recovery_owner(primary) is owner
    assert issued == 0
    assert sealed_validations == 0
    debts = owner.cleanup_debts()
    assert len(debts) == 1
    assert list(artifact_root.iterdir())

    monkeypatch.setattr(os, "open", real_open)
    if isinstance(cleanup_error, SystemExit):
        assert not owner.retry_cleanup(debts[0].debt_id)
        assert owner.cleanup_debts() == debts
        assert len(owner.cleanup_debts()) == 1
    else:
        assert owner.retry_cleanup(debts[0].debt_id)
        assert owner.cleanup_debts() == ()
        assert not list(artifact_root.iterdir())
    owner.close()


@pytest.mark.parametrize(
    "close_error",
    (SystemExit("close host"), OSError("close ordinary")),
    ids=("host-close", "ordinary-close"),
)
def test_capture_copy_host_primary_survives_descriptor_close_failure(
    monkeypatch,
    tmp_path: Path,
    close_error: BaseException,
) -> None:
    """Preserve a copy host primary across ambiguous target descriptor close."""
    import topsailai.hooks.artifact_store as store

    owner, request, _ = _owner(tmp_path)
    artifact_root = tmp_path / "artifacts"
    primary = KeyboardInterrupt("copy host")
    clock = [0.0]
    target_descriptor: int | None = None
    close_attempts = 0
    issued = 0
    sealed_validations = 0
    later_noncleanup_io = 0
    real_open = os.open
    real_close = os.close
    real_fsync = os.fsync
    real_issue = store.ArtifactCaptureOwner._issue

    def observed_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal target_descriptor
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path).name == request.source_path.name and flags & os.O_WRONLY:
            target_descriptor = descriptor
        return descriptor

    def interrupted_write(descriptor: int, value) -> int:
        if descriptor == target_descriptor:
            raise primary
        raise AssertionError("unexpected write after copy interruption")

    def interrupted_close(descriptor: int) -> None:
        nonlocal close_attempts
        if descriptor == target_descriptor:
            close_attempts += 1
            real_close(descriptor)
            raise close_error
        real_close(descriptor)

    def observed_fsync(descriptor: int) -> None:
        nonlocal later_noncleanup_io
        if descriptor == target_descriptor:
            later_noncleanup_io += 1
        real_fsync(descriptor)

    def observed_chmod(*args, **kwargs) -> None:
        nonlocal later_noncleanup_io
        later_noncleanup_io += 1
        raise AssertionError("chmod followed copy interruption")

    def observed_validate(*args, **kwargs) -> None:
        nonlocal sealed_validations
        sealed_validations += 1
        raise AssertionError("sealed validation followed copy interruption")

    def observed_issue(*args, **kwargs):
        nonlocal issued
        issued += 1
        return real_issue(*args, **kwargs)

    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(os, "open", observed_open)
    monkeypatch.setattr(os, "close", interrupted_close)
    monkeypatch.setattr(store.os, "write", interrupted_write)
    monkeypatch.setattr(store.os, "fsync", observed_fsync)
    monkeypatch.setattr(store.os, "chmod", observed_chmod)
    monkeypatch.setattr(store, "validate_sealed_artifact", observed_validate)
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_issue", observed_issue)

    with pytest.raises(KeyboardInterrupt) as raised:
        owner.capture((request,), policy=ArtifactCapturePolicy(timeout_ms=1000))
    assert raised.value is primary
    assert get_artifact_recovery_owner(primary) is owner
    assert close_attempts == 1
    assert issued == 0
    assert sealed_validations == 0
    assert later_noncleanup_io == 0
    debts = owner.cleanup_debts()
    assert len(debts) == 1
    assert not list(artifact_root.iterdir())

    assert not owner.retry_cleanup(debts[0].debt_id)
    assert close_attempts == 1
    assert owner.cleanup_debts() == debts
    owner.close()


@pytest.mark.parametrize("spelling", ("canonical", "dot", "double-separator"))
def test_public_capture_rejects_noncanonical_shebang_before_interpreter_io(
    monkeypatch, tmp_path: Path, spelling: str
) -> None:
    """Accept a trusted canonical shebang and reject equivalent raw aliases pre-I/O."""
    import topsailai.hooks.artifact_validation as validation
    from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint

    case = tmp_path / spelling
    root, artifacts = case / "source", case / "artifacts"
    root.mkdir(parents=True, mode=0o700)
    artifacts.mkdir(mode=0o700)
    interpreter = Path("/bin/sh").resolve(strict=True)
    declaration = str(interpreter)
    if spelling == "dot":
        declaration = f"{interpreter.parent}/./{interpreter.name}"
    elif spelling == "double-separator":
        declaration = f"{interpreter.parent}//{interpreter.name}"
    script = root / "hook"
    content = f"#!{declaration}\nexit 0\n".encode()
    script.write_bytes(content)
    script.chmod(0o500)
    status = interpreter.stat()
    runtime = shebang_runtime_fingerprint(
        interpreter, hashlib.sha256(interpreter.read_bytes()).hexdigest(),
        device=status.st_dev, inode=status.st_ino,
    )
    request = ArtifactCaptureRequest(
        script, "script", "hook",
        ExecutablePlatformPolicy("posix", (str(interpreter),)),
    )
    assertion = ArtifactClosureAssertion(
        script, "script", "hook", hashlib.sha256(content).hexdigest(), runtime, "a" * 64
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (interpreter,), False, (assertion,)),
    )
    calls = 0
    real_validate = validation._validate_script_interpreter

    def observed_validate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(validation, "_validate_script_interpreter", observed_validate)
    result = owner.capture((request,))
    if spelling == "canonical":
        assert result.accepted and calls == 1
    else:
        assert result.errors == ("trust_rejected",) and calls == 0
    owner.close()
