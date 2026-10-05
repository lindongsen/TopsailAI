"""Focused U07 public-boundary and fail-closed branch tests."""

from __future__ import annotations

import hashlib
import math
import os
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks import (
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
    ExecutablePlatformPolicy,
)
from topsailai.hooks.artifact_cleanup import (
    DescriptorLedger,
    close_descriptor_chain,
    open_directory_chain,
    remove_owned_artifact,
    require_fd_metadata_absent,
)
from topsailai.hooks.artifact_store import (
    _fsync_directory,
    _valid_root_spelling,
    _validate_call,
    _validate_resource_free,
)
from topsailai.hooks.artifact_validation import (
    ArtifactValidationError,
    _compatible_elf_bytes,
    _script_runtime,
    _validate_interpreter_status,
    _validate_source_status,
    _validated_ancestry,
    assertion_for_request,
    hash_descriptor,
    revalidate_source,
    validate_artifact_root,
    validate_capture_trust_structure,
    validate_request_structure,
    validate_source_roots,
)


@pytest.mark.parametrize(
    "trust",
    (
        object(),
        ArtifactCaptureTrust((), ()),
        ArtifactCaptureTrust(tuple(Path(f"/r/{index}") for index in range(33)), ()),
        ArtifactCaptureTrust((Path("/r"),), tuple(Path(f"/i/{index}") for index in range(33))),
        ArtifactCaptureTrust((Path("/r"),), (), 1),
        ArtifactCaptureTrust((Path("/r"),), (), False, tuple(object() for _ in range(4097))),
        ArtifactCaptureTrust((Path("/r"),), (), False, (), object()),
        ArtifactCaptureTrust((Path("relative"),), ()),
        ArtifactCaptureTrust((Path("/same"), Path("/same")), ()),
        ArtifactCaptureTrust((Path("/r"),), (), False, (object(),)),
        ArtifactCaptureTrust(
            (Path("/r"),), (), False,
            (
                ArtifactClosureAssertion(Path("/r/a"), "script", "a", "0" * 64, "1" * 64, "2" * 64),
                ArtifactClosureAssertion(Path("/r/a"), "script", "a", "3" * 64, "4" * 64, "5" * 64),
            ),
        ),
        ArtifactCaptureTrust(
            (Path("/r"),), (), False, (),
            ArtifactPythonRuntimeAuthority(Path("relative"), "0" * 64),
        ),
        ArtifactCaptureTrust(
            (Path("/r"),), (), False, (),
            ArtifactPythonRuntimeAuthority(Path("/python"), "bad", "wrong"),
        ),
    ),
)
def test_trust_structure_rejects_malformed_authority(trust: object) -> None:
    """Reject every malformed detached authority before filesystem access."""
    assert validate_capture_trust_structure(trust) is False


@pytest.mark.parametrize(
    "candidate",
    (
        object(),
        ArtifactCaptureRequest(Path("relative"), "script", "tool", ExecutablePlatformPolicy("posix")),
        ArtifactCaptureRequest(Path("/tool"), "unknown", "tool"),
        ArtifactCaptureRequest(Path("/tool"), "script", "tool"),
        ArtifactCaptureRequest(Path("/tool"), "script", "other", ExecutablePlatformPolicy("posix")),
        ArtifactCaptureRequest(Path("/tool.py"), "python_source", "__init__"),
        ArtifactCaptureRequest(Path("/tool.py"), "python_source", "not-valid-name"),
        ArtifactCaptureRequest(Path("/tool.py"), "python_source", "tool", ExecutablePlatformPolicy("posix")),
        ArtifactCaptureRequest(Path("/tool.py"), "python_source", "x" * 256),
    ),
)
def test_request_structure_rejects_malformed_values(candidate: object) -> None:
    """Reject malformed request variants at the resource-free boundary."""
    assert validate_request_structure(candidate) is False


def test_call_boundary_returns_exact_validation_tokens() -> None:
    """Return exact stable tokens for every malformed call-level category."""
    request = ArtifactCaptureRequest(Path("/tool"), "script", "tool", ExecutablePlatformPolicy("posix"))
    assert _validate_call([], ArtifactCapturePolicy(), None, None) == "invalid_artifact_request"
    assert _validate_call((), object(), None, None) == "invalid_artifact_policy"
    assert _validate_call((), ArtifactCapturePolicy(timeout_ms=0), None, None) == "invalid_artifact_policy"
    assert _validate_call((), ArtifactCapturePolicy(), object(), None) == "invalid_artifact_cancellation"
    assert _validate_call((), ArtifactCapturePolicy(), threading.Event(), math.inf) == "invalid_artifact_deadline"
    assert _validate_call((request, request), ArtifactCapturePolicy(max_entries=1), None, None) is None
    assert _validate_call((object(),), ArtifactCapturePolicy(), None, None) == "invalid_artifact_request"


def test_resource_free_boundary_rejects_duplicates_closure_and_policy() -> None:
    """Reject duplicates, missing closure, and unauthorized script policy."""
    path = Path("/root/tool")
    request = ArtifactCaptureRequest(path, "script", "tool", ExecutablePlatformPolicy("posix"))
    assertion = ArtifactClosureAssertion(path, "script", "tool", "0" * 64, "1" * 64, "2" * 64)
    trust = ArtifactCaptureTrust((Path("/root"),), (), True, (assertion,))
    assert _validate_resource_free((request, request), ArtifactCapturePolicy(), trust) == "invalid_artifact_request"
    assert _validate_resource_free((request,), ArtifactCapturePolicy(), ArtifactCaptureTrust((Path("/root"),), (), True)) == "unsupported_artifact_closure"
    unauthorized = ArtifactCaptureRequest(
        path, "script", "tool", ExecutablePlatformPolicy("posix", ("/bin/sh",))
    )
    unauthorized_assertion = ArtifactClosureAssertion(
        path, "script", "tool", "0" * 64, "1" * 64, "2" * 64
    )
    unauthorized_trust = ArtifactCaptureTrust(
        (Path("/root"),), (), True, (unauthorized_assertion,)
    )
    assert _validate_resource_free((unauthorized,), ArtifactCapturePolicy(), unauthorized_trust) == "trust_rejected"


def test_assertion_lookup_root_spelling_and_elf_fail_closed() -> None:
    """Fail closed for ambiguous closure, malformed roots, and invalid ELF."""
    path = Path("/root/tool")
    request = ArtifactCaptureRequest(path, "script", "tool", ExecutablePlatformPolicy("posix"))
    assertion = ArtifactClosureAssertion(path, "script", "tool", "0" * 64, "1" * 64, "2" * 64)
    duplicate = ArtifactCaptureTrust((Path("/root"),), (), True, (assertion, assertion))
    with pytest.raises(ArtifactValidationError, match="unsupported_artifact_closure"):
        assertion_for_request(duplicate, request)
    assert not _valid_root_spelling(None)
    assert not _valid_root_spelling("")
    assert not _valid_root_spelling("relative")
    assert not _valid_root_spelling("/root/../other")
    assert not _compatible_elf_bytes(b"")
    assert not _compatible_elf_bytes(b"not-an-elf" + b"\0" * 20)


class _DirectDescriptorOwner:
    """Provide direct descriptor ownership for validation-unit boundaries."""

    def open_descriptor(
        self, path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        """Open one descriptor with the requested descriptor-relative arguments."""
        return os.open(path, flags, mode, dir_fd=dir_fd)

    def close_descriptor(self, descriptor: int) -> None:
        """Close one exact descriptor."""
        os.close(descriptor)


def _status(mode: int, *, uid: int | None = None, size: int = 1) -> SimpleNamespace:
    """Build the stat fields consumed by focused status validators."""
    return SimpleNamespace(
        st_mode=mode,
        st_uid=os.getuid() if uid is None else uid,
        st_gid=os.getgid(),
        st_dev=1,
        st_ino=2,
        st_size=size,
        st_mtime_ns=3,
        st_ctime_ns=4,
        st_nlink=1,
    )


@pytest.mark.parametrize(
    "status",
    (
        _status(stat.S_IFDIR | 0o700),
        _status(stat.S_IFREG | 0o500, uid=os.getuid() + 1),
        _status(stat.S_IFREG | 0o520),
        _status(stat.S_IFREG | 0o400),
    ),
)
def test_interpreter_status_rejects_non_executable_authority(status: SimpleNamespace) -> None:
    """Reject non-file, foreign, writable, and non-executable interpreters."""
    with pytest.raises(ArtifactValidationError, match="trust_rejected"):
        _validate_interpreter_status(status, os.getuid())


def test_source_status_rejects_nonregular_foreign_writable_and_nonexec() -> None:
    """Reject every unsafe source status class."""
    script = ArtifactCaptureRequest(
        Path("/root/tool"), "script", "tool", ExecutablePlatformPolicy("posix")
    )
    module = ArtifactCaptureRequest(Path("/root/tool.py"), "python_source", "tool")
    rejected = (
        (module, _status(stat.S_IFDIR | 0o400)),
        (module, _status(stat.S_IFREG | 0o400, uid=os.getuid() + 1)),
        (module, _status(stat.S_IFREG | 0o420)),
        (script, _status(stat.S_IFREG | 0o400)),
    )
    for request, status in rejected:
        with pytest.raises(ArtifactValidationError, match="trust_rejected"):
            _validate_source_status(request, status, os.getuid())


def test_hash_descriptor_limit_plus_one(tmp_path: Path) -> None:
    """Reject a descriptor only after observing limit plus one byte."""
    source = tmp_path / "oversized"
    source.write_bytes(b"ab")
    descriptor = os.open(source, os.O_RDONLY)
    try:
        with pytest.raises(ArtifactValidationError, match="artifact_byte_limit"):
            hash_descriptor(descriptor, 1, lambda: None)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("payload", "allow_native", "token"),
    (
        (b"#!/bin/sh\r\n", False, "unsupported_artifact_closure"),
        (b"#!\xff\n", False, "unsupported_artifact_closure"),
        (b"#!/bin/sh extra\n", False, "unsupported_artifact_closure"),
        (b"#!relative\n", False, "trust_rejected"),
        (b"plain text", False, "trust_rejected"),
        (b"plain text", True, "unsupported_artifact_closure"),
    ),
)
def test_script_runtime_rejects_malformed_or_unauthorized_payload(
    tmp_path: Path, payload: bytes, allow_native: bool, token: str
) -> None:
    """Reject malformed shebang and unauthorized native script forms."""
    source = tmp_path / "tool"
    source.write_bytes(payload)
    descriptor = os.open(source, os.O_RDONLY)
    request = ArtifactCaptureRequest(
        source, "script", "tool", ExecutablePlatformPolicy("posix", ("/bin/sh",))
    )
    try:
        with pytest.raises(ArtifactValidationError, match=token):
            _script_runtime(
                descriptor,
                request,
                os.getuid(),
                lambda: None,
                allow_native,
                _DirectDescriptorOwner(),
            )
    finally:
        os.close(descriptor)


def test_root_validators_reject_root_overlap_and_nested_roots(tmp_path: Path) -> None:
    """Reject artifact/source overlap, filesystem root, and nested source roots."""
    root = tmp_path / "private"
    child = root / "child"
    root.mkdir(mode=0o700)
    child.mkdir(mode=0o700)
    owner = _DirectDescriptorOwner()
    with pytest.raises(ArtifactValidationError, match="artifact_storage_unavailable"):
        validate_artifact_root(root, (root,), os.getuid(), lambda: None, owner)
    with pytest.raises(ArtifactValidationError, match="trust_rejected"):
        validate_source_roots((Path("/"),), os.getuid(), lambda: None, owner)
    with pytest.raises(ArtifactValidationError, match="trust_rejected"):
        validate_source_roots((root, child), os.getuid(), lambda: None, owner)


def test_descriptor_ledger_rejects_unknown_close_and_settles_open_error(
    tmp_path: Path,
) -> None:
    """Reject foreign close authority and settle an ordinary failed open."""
    ledger = DescriptorLedger()
    with pytest.raises(RuntimeError, match="not owned"):
        ledger.close(-1)
    with pytest.raises(OSError):
        ledger.open(tmp_path / "missing", os.O_RDONLY)
    assert ledger.count == 0


def test_directory_chain_failure_closes_open_prefix(tmp_path: Path) -> None:
    """Close an already-open chain when a later component cannot be opened."""
    root = tmp_path / "root"
    child = root / "missing"
    root.mkdir()

    class FailingOwner:
        def __init__(self) -> None:
            self.ledger = DescriptorLedger()
            self.calls = 0

        def open_descriptor(self, path, flags, mode=0o777, *, dir_fd=None):
            self.calls += 1
            if self.calls == 3:
                raise OSError("injected")
            return self.ledger.open_descriptor(path, flags, mode, dir_fd=dir_fd)

        def close_descriptor(self, descriptor: int) -> None:
            self.ledger.close_descriptor(descriptor)

    owner = FailingOwner()
    with pytest.raises(OSError, match="injected"):
        open_directory_chain(child, owner)
    assert owner.ledger.count == 0


def test_close_descriptor_chain_reports_first_ordinary_failure() -> None:
    """Attempt every close and report the first ordinary close failure."""
    closed: list[int] = []

    class Owner:
        def close_descriptor(self, descriptor: int) -> None:
            closed.append(descriptor)
            if descriptor == 2:
                raise OSError("first")
            if descriptor == 1:
                raise OSError("second")

    with pytest.raises(OSError, match="first"):
        close_descriptor_chain((1, 2, 3), Owner())
    assert closed == [3, 2, 1]


def test_remove_owned_artifact_without_directory_observes_ledger_state(tmp_path: Path) -> None:
    """Settle a directory-free cleanup only when no descriptor debt remains."""
    ledger = DescriptorLedger()
    assert remove_owned_artifact(tmp_path, None, None, None, (), "none", ledger)
    ledger.reserve_uncertain()
    assert not remove_owned_artifact(tmp_path, None, None, None, (), "none", ledger)


class _LateCheckpoint:
    """Raise after one injected operation advances the controlled clock."""

    def __init__(self) -> None:
        self.late = False

    def __call__(self) -> None:
        if self.late:
            raise TimeoutError("late operation")


def test_late_directory_open_skips_fsync_and_closes_descriptor(monkeypatch) -> None:
    """Do not fsync after a directory open returns beyond the deadline."""
    checkpoint = _LateCheckpoint()
    closed: list[int] = []

    class Ledger:
        def open(self, *args, **kwargs):
            checkpoint.late = True
            return 41

        def close(self, descriptor):
            closed.append(descriptor)

    monkeypatch.setattr(os, "fsync", lambda descriptor: pytest.fail("unexpected fsync"))
    with pytest.raises(TimeoutError, match="late operation"):
        _fsync_directory(Path("/unused"), Ledger(), checkpoint)
    assert closed == [41]


@pytest.mark.parametrize("late_operation", ("lseek", "read"))
def test_late_shebang_io_stops_before_next_operation(
    monkeypatch, tmp_path: Path, late_operation: str
) -> None:
    """Check liveness after seek and read before later shebang work."""
    source = tmp_path / "tool"
    source.write_bytes(b"plain text")
    descriptor = os.open(source, os.O_RDONLY)
    request = ArtifactCaptureRequest(
        source, "script", "tool", ExecutablePlatformPolicy("posix")
    )
    checkpoint = _LateCheckpoint()
    real_lseek = os.lseek
    real_read = os.read
    reads = 0

    def late_lseek(*args):
        result = real_lseek(*args)
        if late_operation == "lseek":
            checkpoint.late = True
        return result

    def late_read(*args):
        nonlocal reads
        reads += 1
        result = real_read(*args)
        if late_operation == "read":
            checkpoint.late = True
        return result

    monkeypatch.setattr(os, "lseek", late_lseek)
    monkeypatch.setattr(os, "read", late_read)
    try:
        with pytest.raises(TimeoutError, match="late operation"):
            _script_runtime(
                descriptor, request, os.getuid(), checkpoint, True, _DirectDescriptorOwner()
            )
    finally:
        os.close(descriptor)
    assert reads == (0 if late_operation == "lseek" else 1)


def test_late_xattr_query_stops_before_next_attribute(monkeypatch) -> None:
    """Do not query a second attribute after the first query returns late."""
    checkpoint = _LateCheckpoint()
    calls: list[str] = []

    def late_getxattr(descriptor, name):
        calls.append(name)
        checkpoint.late = True
        raise OSError(getattr(__import__("errno"), "ENODATA"), "absent")

    monkeypatch.setattr(os, "getxattr", late_getxattr)
    with pytest.raises(TimeoutError, match="late operation"):
        require_fd_metadata_absent(9, directory=True, checkpoint=checkpoint)
    assert calls == ["system.posix_acl_access"]


def test_late_ancestor_stat_stops_before_next_stat(monkeypatch) -> None:
    """Do not stat another ancestor after the first stat returns late."""
    checkpoint = _LateCheckpoint()
    calls: list[int] = []

    def late_fstat(descriptor):
        calls.append(descriptor)
        checkpoint.late = True
        return _status(stat.S_IFDIR | 0o700)

    monkeypatch.setattr(os, "fstat", late_fstat)
    with pytest.raises(TimeoutError, match="late operation"):
        _validated_ancestry((11, 12), os.getuid(), checkpoint)
    assert calls == [11]


@pytest.mark.parametrize("late_operation", ("source-fstat", "named-stat"))
def test_capture_late_source_stat_stops_revalidation_io(
    monkeypatch, tmp_path: Path, late_operation: str
) -> None:
    """Return timeout without starting I/O after a late source stat."""
    import platform
    import struct
    import topsailai.hooks.artifact_store as store
    import topsailai.hooks.artifact_validation as validation
    from topsailai.hooks import ArtifactCaptureOwner
    from topsailai.hooks.artifact_identity import native_runtime_fingerprint

    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    source_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    source = source_root / "tool"
    machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
    payload = b"\x7fELF" + bytes([2 if struct.calcsize("P") == 8 else 1]) + b"\0" * 13
    payload += machine.to_bytes(2, "little")
    source.write_bytes(payload)
    source.chmod(0o500)
    request = ArtifactCaptureRequest(
        source, "script", "tool", ExecutablePlatformPolicy("posix")
    )
    assertion = ArtifactClosureAssertion(
        source,
        "script",
        "tool",
        hashlib.sha256(payload).hexdigest(),
        native_runtime_fingerprint(),
        "d" * 64,
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifact_root),
        trust=ArtifactCaptureTrust((source_root,), (), True, (assertion,)),
    )
    clock = [0.0]
    named_stats = 0
    file_metadata_checks = 0
    real_revalidate = store.revalidate_source

    def late_revalidate(validated, checkpoint):
        nonlocal named_stats, file_metadata_checks
        real_fstat = validation.os.fstat
        real_stat = validation.os.stat
        real_metadata = validation._require_fd_metadata_absent

        def observed_fstat(descriptor):
            result = real_fstat(descriptor)
            if late_operation == "source-fstat" and descriptor == validated.descriptor:
                clock[0] = 2.0
            return result

        def observed_stat(path, *args, **kwargs):
            nonlocal named_stats
            result = real_stat(path, *args, **kwargs)
            if kwargs.get("dir_fd") is not None and path == validated.basename:
                named_stats += 1
                if late_operation == "named-stat":
                    clock[0] = 2.0
            return result

        def observed_metadata(descriptor, *, directory, checkpoint=None):
            nonlocal file_metadata_checks
            if not directory:
                file_metadata_checks += 1
            return real_metadata(descriptor, directory=directory, checkpoint=checkpoint)

        monkeypatch.setattr(validation.os, "fstat", observed_fstat)
        monkeypatch.setattr(validation.os, "stat", observed_stat)
        monkeypatch.setattr(validation, "_require_fd_metadata_absent", observed_metadata)
        try:
            real_revalidate(validated, checkpoint)
        finally:
            monkeypatch.setattr(validation.os, "fstat", real_fstat)
            monkeypatch.setattr(validation.os, "stat", real_stat)
            monkeypatch.setattr(validation, "_require_fd_metadata_absent", real_metadata)

    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(store, "revalidate_source", late_revalidate)
    result = owner.capture(
        (request,), policy=ArtifactCapturePolicy(timeout_ms=1000), deadline=1.0
    )
    assert result.errors == ("artifact_capture_timeout",)
    assert result.artifact is None and not list(artifact_root.iterdir())
    assert owner.cleanup_debts() == ()
    assert named_stats == (0 if late_operation == "source-fstat" else 1)
    assert file_metadata_checks == 0
    owner.close()


def test_capture_late_python_readlink_skips_resolve(monkeypatch, tmp_path: Path) -> None:
    """Return timeout without resolving the executable after a late readlink."""
    import sys
    import topsailai.hooks.artifact_store as store
    import topsailai.hooks.artifact_validation as validation
    from topsailai.hooks import ArtifactCaptureOwner

    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    source_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    executable = Path(sys.executable).resolve(strict=True)
    executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    module = source_root / "plugin.py"
    payload = b"VALUE = 1\n"
    module.write_bytes(payload)
    module.chmod(0o400)
    request = ArtifactCaptureRequest(module, "python_source", "plugin")
    assertion = ArtifactClosureAssertion(
        module, "python_source", "plugin", hashlib.sha256(payload).hexdigest(),
        "0" * 64, "e" * 64,
    )
    trust = ArtifactCaptureTrust(
        (source_root,), (), False, (assertion,),
        ArtifactPythonRuntimeAuthority(executable, executable_digest),
    )
    owner = ArtifactCaptureOwner(artifact_root=str(artifact_root), trust=trust)
    clock = [0.0]
    resolves = 0
    real_readlink = validation.os.readlink
    real_resolve = Path.resolve

    def late_readlink(path):
        result = real_readlink(path)
        if path == "/proc/self/exe":
            clock[0] = 2.0
        return result

    def observed_resolve(self, *args, **kwargs):
        nonlocal resolves
        resolves += 1
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(validation.os, "readlink", late_readlink)
    monkeypatch.setattr(Path, "resolve", observed_resolve)
    result = owner.capture(
        (request,), policy=ArtifactCapturePolicy(timeout_ms=1000), deadline=1.0
    )
    assert result.errors == ("artifact_capture_timeout",)
    assert result.artifact is None and not list(artifact_root.iterdir())
    assert owner.cleanup_debts() == () and resolves == 0
    owner.close()


def _native_capture_case(tmp_path: Path):
    """Build one public native-script capture for checked-I/O arbitration."""
    import platform
    import struct
    from topsailai.hooks import ArtifactCaptureOwner
    from topsailai.hooks.artifact_identity import native_runtime_fingerprint

    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    source_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    source = source_root / "tool"
    machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
    payload = b"\x7fELF" + bytes([2 if struct.calcsize("P") == 8 else 1]) + b"\0" * 13
    payload += machine.to_bytes(2, "little")
    source.write_bytes(payload)
    source.chmod(0o500)
    request = ArtifactCaptureRequest(
        source, "script", "tool", ExecutablePlatformPolicy("posix")
    )
    assertion = ArtifactClosureAssertion(
        source, "script", "tool", hashlib.sha256(payload).hexdigest(),
        native_runtime_fingerprint(), "f" * 64,
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifact_root),
        trust=ArtifactCaptureTrust((source_root,), (), True, (assertion,)),
    )
    return owner, artifact_root, request


@pytest.mark.parametrize(
    ("liveness", "operation_error", "expected_token"),
    (
        ("deadline", KeyboardInterrupt("host deadline"), None),
        ("cancellation", SystemExit("host cancellation"), None),
        ("deadline", OSError("ordinary deadline"), "artifact_capture_timeout"),
        ("cancellation", OSError("ordinary cancellation"), "artifact_capture_cancelled"),
    ),
)
def test_capture_checked_io_preserves_host_interrupt_and_arbitrates_ordinary_error(
    monkeypatch, tmp_path: Path, liveness: str,
    operation_error: BaseException, expected_token: str | None,
) -> None:
    """Preserve host identity while liveness overrides an ordinary I/O error."""
    import topsailai.hooks.artifact_store as store
    import topsailai.hooks.artifact_validation as validation

    owner, artifact_root, request = _native_capture_case(tmp_path)
    clock = [0.0]
    cancellation = threading.Event()
    real_revalidate = store.revalidate_source

    def interrupted_revalidate(validated, checkpoint):
        real_fstat = validation.os.fstat

        def interrupted_fstat(descriptor):
            if descriptor != validated.descriptor:
                return real_fstat(descriptor)
            if liveness == "deadline":
                clock[0] = 2.0
            else:
                cancellation.set()
            raise operation_error

        monkeypatch.setattr(validation.os, "fstat", interrupted_fstat)
        try:
            real_revalidate(validated, checkpoint)
        finally:
            monkeypatch.setattr(validation.os, "fstat", real_fstat)

    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(store, "revalidate_source", interrupted_revalidate)
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
    assert not list(artifact_root.iterdir())
    assert owner.cleanup_debts() == ()
    owner.close()
