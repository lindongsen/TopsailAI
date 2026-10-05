"""Regressions for U07 deadline, structure, and interpreter review findings."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
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
from topsailai.hooks.artifact_cleanup import open_directory_chain
from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint

def _script_fixture(tmp_path: Path):
    """Create one script with a private copied interpreter authority."""
    root = tmp_path / "source"
    artifacts = tmp_path / "artifacts"
    interpreters = tmp_path / "interpreters"
    root.mkdir(mode=0o700)
    artifacts.mkdir(mode=0o700)
    interpreters.mkdir(mode=0o700)
    interpreter = interpreters / "shell"
    interpreter.write_bytes(Path("/bin/sh").resolve(strict=True).read_bytes())
    interpreter.chmod(0o500)
    script = root / "hook"
    content = f"#!{interpreter}\nexit 0\n".encode()
    script.write_bytes(content)
    script.chmod(0o500)
    status = interpreter.stat()
    digest = hashlib.sha256(interpreter.read_bytes()).hexdigest()
    runtime = shebang_runtime_fingerprint(
        interpreter, digest, device=status.st_dev, inode=status.st_ino)
    policy = ExecutablePlatformPolicy("posix", (str(interpreter),))
    request = ArtifactCaptureRequest(script, "script", "hook", policy)
    assertion = ArtifactClosureAssertion(
        script, "script", "hook", hashlib.sha256(content).hexdigest(), runtime, "d" * 64
    )
    trust = ArtifactCaptureTrust((root,), (interpreter,), False, (assertion,))
    return ArtifactCaptureOwner(artifact_root=str(artifacts), trust=trust), request, interpreter
def test_malformed_request_returns_token_before_io(monkeypatch, tmp_path: Path) -> None:
    """Reject malformed scalar and nested policy types without touching files."""
    owner, request, _ = _script_fixture(tmp_path)
    requests = (
        replace(request, kind=[]),
        replace(request, logical_name=None),
        replace(request, script_policy=object()),
    )

    class PolicyLookalike:
        """Expose policy attributes without owning policy authority."""

        platform = "posix"
        allowed_interpreters = request.script_policy.allowed_interpreters
        native_suffixes = ()

    requests += (replace(request, script_policy=PolicyLookalike()),)
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("unexpected I/O"))
    for malformed in requests:
        result = owner.capture((malformed,))
        assert result.errors == ("invalid_artifact_request",)
    assert owner.cleanup_debts() == ()
    owner.close()
def test_late_open_stops_directory_chain(monkeypatch, tmp_path: Path) -> None:
    """Start no second directory open after the prior open returns late."""
    calls: list[object] = []
    expired = [False]

    class Owner:
        """Model descriptor ownership while making the first open late."""

        def open_descriptor(self, path, flags, mode=0o777, *, dir_fd=None):
            calls.append(path)
            expired[0] = True
            return 91

        def close_descriptor(self, descriptor):
            return None

    def checkpoint() -> None:
        if expired[0]:
            raise TimeoutError("late open")

    with pytest.raises(TimeoutError, match="late open"):
        open_directory_chain(tmp_path / "child", Owner(), checkpoint)
    assert len(calls) == 1
def test_late_write_and_fsync_start_no_later_noncleanup_io(monkeypatch, tmp_path: Path) -> None:
    """Stop copy work immediately after a late write or fsync while cleanup proceeds."""
    import topsailai.hooks.artifact_store as store

    for phase in ("write", "fsync"):
        case = tmp_path / phase
        case.mkdir()
        owner, request, _ = _script_fixture(case)
        clock = [0.0]
        later_calls: list[str] = []
        monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
        real_write = store.os.write
        real_fsync = store.os.fsync
        real_chmod = store.os.chmod

        def late_write(descriptor, value):
            written = real_write(descriptor, value)
            if phase == "write":
                clock[0] = 2.0
            return written

        def late_fsync(descriptor):
            if clock[0] >= 2.0:
                later_calls.append("fsync")
            real_fsync(descriptor)
            if phase == "fsync" and clock[0] < 2.0:
                clock[0] = 2.0

        def observe_chmod(*args, **kwargs):
            if clock[0] >= 2.0:
                later_calls.append("chmod")
            return real_chmod(*args, **kwargs)

        monkeypatch.setattr(store.os, "write", late_write)
        monkeypatch.setattr(store.os, "fsync", late_fsync)
        monkeypatch.setattr(store.os, "chmod", observe_chmod)
        result = owner.capture(
            (request,), policy=ArtifactCapturePolicy(timeout_ms=1000), deadline=1.0)
        assert result.errors == ("artifact_capture_timeout",), phase
        assert later_calls == [], phase
        assert owner.cleanup_debts() == (), phase
        owner.close()
        monkeypatch.undo()
def test_interpreter_revalidation_rejects_mutation_and_replacement(
    monkeypatch, tmp_path: Path
) -> None:
    """Reject changed bytes, security metadata, named paths, and ancestry."""
    import topsailai.hooks.artifact_validation as validation

    mutations = ("same-size", "mode", "acl", "named-path", "ancestor",
                 "ancestor-mode", "ancestor-acl")
    for mutation in mutations:
        case = tmp_path / mutation
        case.mkdir()
        owner, request, interpreter = _script_fixture(case)
        globals_map = validation.open_validated_source.__globals__
        real_revalidate = globals_map["_revalidate_interpreter"]
        real_metadata = globals_map["_require_fd_metadata_absent"]
        called = []

        def mutate_then_revalidate(*args, _mutation=mutation, **kwargs):
            called.append(_mutation)
            if _mutation == "same-size":
                data = bytearray(interpreter.read_bytes())
                data[-1] ^= 1
                interpreter.write_bytes(data)
                interpreter.chmod(0o500)
            elif _mutation == "mode":
                interpreter.chmod(0o700)
            elif _mutation in ("acl", "ancestor-acl"):
                descriptor = args[1] if _mutation == "acl" else args[4][-1]

                def changed_metadata(candidate, *, directory, checkpoint=None):
                    if candidate == descriptor and directory == (_mutation == "ancestor-acl"):
                        raise validation.ArtifactValidationError("trust_rejected")
                    return real_metadata(
                        candidate, directory=directory, checkpoint=checkpoint
                    )

                monkeypatch.setitem(globals_map, "_require_fd_metadata_absent", changed_metadata)
            elif _mutation == "named-path":
                replacement = interpreter.with_name("replacement")
                replacement.write_bytes(interpreter.read_bytes())
                replacement.chmod(0o500)
                interpreter.unlink()
                replacement.rename(interpreter)
            elif _mutation == "ancestor-mode":
                interpreter.parent.chmod(0o770)
            else:
                parent = interpreter.parent
                moved = parent.with_name("interpreters-moved")
                parent.rename(moved)
                parent.mkdir(mode=0o700)
                replacement = parent / interpreter.name
                replacement.write_bytes((moved / interpreter.name).read_bytes())
                replacement.chmod(0o500)
            return real_revalidate(*args, **kwargs)

        monkeypatch.setitem(globals_map, "_revalidate_interpreter", mutate_then_revalidate)
        result = owner.capture((request,))
        assert called == [mutation]
        assert result.errors == ("artifact_source_changed",), (mutation, result.errors)
        assert result.artifact is None and owner.cleanup_debts() == (), mutation
        owner.close()
        monkeypatch.undo()
def test_validation_finalizer_preserves_host_primary(monkeypatch) -> None:
    """Keep a host primary when descriptor close and liveness also fail."""
    from topsailai.hooks.artifact_cleanup import finalize_descriptor_chain

    primary = KeyboardInterrupt("validation primary")
    closes: list[int] = []

    class Owner:
        def close_descriptor(self, descriptor: int) -> None:
            closes.append(descriptor)
            raise SystemExit("validation close")

    def checkpoint() -> None:
        raise TimeoutError("late validation cleanup")

    def operation() -> None:
        try:
            raise primary
        except BaseException as scope_primary:
            finalize_descriptor_chain((17,), Owner(), checkpoint, scope_primary)
            raise

    with pytest.raises(KeyboardInterrupt) as raised:
        operation()
    assert raised.value is primary and closes == [17]
def test_public_dispose_preserves_removal_primary_and_queryable_debt(
    monkeypatch, tmp_path: Path
) -> None:
    """Keep unlink interruption primary across a secondary descriptor close."""
    import topsailai.hooks.artifact_cleanup as cleanup
    from topsailai.hooks import get_artifact_recovery_owner

    owner, request, _ = _script_fixture(tmp_path)
    captured = owner.capture((request,))
    assert captured.accepted and captured.artifact is not None
    primary = KeyboardInterrupt("unlink primary")
    secondary = SystemExit("close secondary")
    real_close = cleanup.os.close
    unlink_started = False
    close_failed = False

    def interrupted_unlink(*args, **kwargs):
        nonlocal unlink_started
        unlink_started = True
        raise primary

    def interrupted_close(descriptor: int) -> None:
        nonlocal close_failed
        if unlink_started and not close_failed:
            close_failed = True
            real_close(descriptor)
            raise secondary
        real_close(descriptor)

    monkeypatch.setattr(cleanup.os, "unlink", interrupted_unlink)
    monkeypatch.setattr(cleanup.os, "close", interrupted_close)
    with pytest.raises(KeyboardInterrupt) as raised:
        owner.dispose(captured.artifact)
    assert raised.value is primary
    assert get_artifact_recovery_owner(primary) is owner
    assert captured.artifact.disposed and close_failed
    debts = owner.cleanup_debts()
    assert len(debts) == 1
def test_close_invalidates_all_handles_before_interrupted_cleanup(
    monkeypatch, tmp_path: Path
) -> None:
    """Invalidate every issued handle before the first cleanup interruption."""
    import topsailai.hooks.artifact_store as store
    from topsailai.hooks import get_artifact_recovery_owner

    owner, _, _ = _script_fixture(tmp_path)
    first = owner.capture(())
    second = owner.capture(())
    assert first.artifact is not None and second.artifact is not None
    primary = KeyboardInterrupt("first cleanup")
    calls = 0
    real_cleanup = store.ArtifactCaptureOwner._cleanup_slot

    def interrupted_cleanup(self, slot):
        nonlocal calls
        calls += 1
        slot.cleanup_pending = True
        if calls == 1:
            raise primary
        return real_cleanup(self, slot)

    monkeypatch.setattr(store.ArtifactCaptureOwner, "_cleanup_slot", interrupted_cleanup)
    with pytest.raises(KeyboardInterrupt) as raised:
        owner.close()
    assert raised.value is primary
    assert get_artifact_recovery_owner(primary) is owner
    assert first.artifact.disposed and second.artifact.disposed
    assert len(owner.cleanup_debts()) >= 1 and calls == 1
def test_diagnostic_failures_never_replace_body_primary(monkeypatch, tmp_path: Path) -> None:
    """Suppress host failures from recovery attachment and secondary notes."""
    import topsailai.hooks.artifact_store as store

    owner, _, _ = _script_fixture(tmp_path)

    class RefusingPrimary(KeyboardInterrupt):
        def __setattr__(self, name, value):
            if name == "_topsailai_artifact_recovery_owner":
                raise SystemExit("attribute refused")
            return super().__setattr__(name, value)

        def add_note(self, note: str) -> None:
            raise SystemExit("note refused")

    primary = RefusingPrimary("body primary")
    monkeypatch.setattr(
        store.ArtifactCaptureOwner,
        "close",
        lambda self: (_ for _ in ()).throw(SystemExit("cleanup secondary")),
    )
    with pytest.raises(RefusingPrimary) as raised:
        with owner:
            raise primary
    assert raised.value is primary


def test_unexpected_ordinary_and_source_read_errors_use_fixed_tokens(
    monkeypatch, tmp_path: Path
) -> None:
    """Map ordinary implementation and pinned-source read errors exactly."""
    import topsailai.hooks.artifact_store as store

    internal_case = tmp_path / "internal"
    internal_case.mkdir()
    owner, request, _ = _script_fixture(internal_case)
    monkeypatch.setattr(
        store,
        "open_validated_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("secret ordinary")),
    )
    result = owner.capture((request,))
    assert result.errors == ("artifact_internal_error",)
    assert "secret ordinary" not in repr(result)

    monkeypatch.undo()
    source_read_case = tmp_path / "source-read"
    source_read_case.mkdir()
    owner, request, _ = _script_fixture(source_read_case)
    real_read = store.os.read

    def denied_read(descriptor: int, size: int) -> bytes:
        if os.readlink(f"/proc/self/fd/{descriptor}") == str(request.source_path):
            raise OSError("secret source read")
        return real_read(descriptor, size)

    monkeypatch.setattr(store.os, "read", denied_read)
    result = owner.capture((request,))
    assert result.errors == ("trust_rejected",)
    assert "secret source read" not in repr(result)
def test_readback_rejects_excess_after_one_bounded_read(monkeypatch, tmp_path: Path) -> None:
    """Stop captured-file read-back immediately after expected length plus one."""
    import topsailai.hooks.artifact_store as store

    owner, request, _ = _script_fixture(tmp_path)
    real_read = store.os.read
    captured_reads = 0

    def excess_read(descriptor: int, size: int) -> bytes:
        nonlocal captured_reads
        target = os.readlink(f"/proc/self/fd/{descriptor}")
        if "/capture-" in target:
            captured_reads += 1
            return b"x" * size
        return real_read(descriptor, size)

    monkeypatch.setattr(store.os, "read", excess_read)
    result = owner.capture((request,))
    assert result.errors == ("artifact_storage_unavailable",)
    assert captured_reads == 1
def test_structure_precedence_event_subclass_and_literal_types(
    monkeypatch, tmp_path: Path
) -> None:
    """Enforce request-first precedence and exact detached authority scalars."""
    import threading
    from dataclasses import replace
    import topsailai.hooks.artifact_store as store
    from topsailai.hooks.artifact_structure import (
        validate_capture_call, validate_capture_trust_structure,
    )

    owner, request, interpreter = _script_fixture(tmp_path)
    assert validate_capture_call(
        (object(),), ArtifactCapturePolicy(timeout_ms=0), None, None
    ) == "invalid_artifact_request"

    class EventSubclass(threading.Event):
        pass

    assert validate_capture_call(
        (request,), ArtifactCapturePolicy(), EventSubclass(), None
    ) is None
    assertion = owner._trust.closure_assertions[0]

    class Text(str):
        pass

    invalid_assertions = (
        replace(assertion, closure=Text(assertion.closure)),
        replace(assertion, logical_name="x" * 256),
        replace(assertion, logical_name="other"),
    )
    for invalid in invalid_assertions:
        assert not validate_capture_trust_structure(
            replace(owner._trust, closure_assertions=(invalid,))
        )
    canonical = owner.capture((request,))
    assert canonical.accepted and canonical.artifact is not None
    assert owner.dispose(canonical.artifact).accepted
    admission_opens = 0

    def forbidden_open(*args, **kwargs):
        nonlocal admission_opens
        admission_opens += 1
        pytest.fail("noncanonical request policy reached admission I/O")

    monkeypatch.setattr(store.os, "open", forbidden_open)
    aliases = (
        f"{interpreter.parent}/./{interpreter.name}",
        f"{interpreter.parent}//{interpreter.name}",
    )
    for alias in aliases:
        aliased = replace(
            request,
            script_policy=replace(request.script_policy, allowed_interpreters=(alias,)),
        )
        assert owner.capture((aliased,)).errors == ("trust_rejected",)
    assert admission_opens == 0
    monkeypatch.undo()
    second = replace(
        request, source_path=request.source_path.with_name("hook-2"), logical_name="hook-2"
    )
    malformed_tail = (request, second, object())
    limited = ArtifactCapturePolicy(max_entries=1)
    assert validate_capture_call(malformed_tail, limited, None, None) is None
    assert owner.capture(malformed_tail, policy=limited).errors == (
        "artifact_inventory_limit",
    )
def test_unconfirmed_source_close_starts_no_seal_io(monkeypatch, tmp_path: Path) -> None:
    """Stop admission before sealed read-back after source-close uncertainty."""
    import topsailai.hooks.artifact_store as store

    owner, request, _ = _script_fixture(tmp_path)
    seal_calls = 0
    real_close_sources = store.ArtifactCaptureOwner._close_sources

    def unsettled_close(self, slot, sources, checkpoint=None):
        if checkpoint is not None:
            slot.cleanup_pending = True
            return False
        return real_close_sources(self, slot, sources, checkpoint)

    def forbidden_seal(*args, **kwargs):
        nonlocal seal_calls
        seal_calls += 1
        pytest.fail("sealed admission followed an unconfirmed source close")

    monkeypatch.setattr(store.ArtifactCaptureOwner, "_close_sources", unsettled_close)
    monkeypatch.setattr(store.ArtifactCaptureOwner, "_seal_and_sync", forbidden_seal)
    result = owner.capture((request,))
    assert result.errors == ("artifact_cleanup_pending",)
    assert seal_calls == 0


@pytest.mark.parametrize("entrypoint", ("close", "retry"))
def test_public_cleanup_entrypoints_preserve_host_primary(
    monkeypatch, tmp_path: Path, entrypoint: str
) -> None:
    """Preserve removal primary and recovery authority through close and retry."""
    import topsailai.hooks.artifact_cleanup as cleanup
    from topsailai.hooks import get_artifact_recovery_owner

    owner, request, _ = _script_fixture(tmp_path)
    captured = owner.capture((request,))
    assert captured.artifact is not None
    debt_id = owner._issued[id(captured.artifact)].debt_id
    if entrypoint == "retry":
        monkeypatch.setattr(cleanup.os, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("arm debt")))
        assert owner.dispose(captured.artifact).cleanup_pending
        monkeypatch.undo()
    primary = KeyboardInterrupt(f"{entrypoint} removal primary")
    real_close = cleanup.os.close
    unlink_started = False
    close_failed = False

    def interrupted_unlink(*args, **kwargs):
        nonlocal unlink_started
        unlink_started = True
        raise primary

    def interrupted_close(descriptor: int) -> None:
        nonlocal close_failed
        if unlink_started and not close_failed:
            close_failed = True
            real_close(descriptor)
            raise SystemExit("secondary close")
        real_close(descriptor)

    monkeypatch.setattr(cleanup.os, "unlink", interrupted_unlink)
    monkeypatch.setattr(cleanup.os, "close", interrupted_close)
    with pytest.raises(KeyboardInterrupt) as raised:
        owner.close() if entrypoint == "close" else owner.retry_cleanup(debt_id)
    assert raised.value is primary
    assert get_artifact_recovery_owner(primary) is owner
    assert close_failed and len(owner.cleanup_debts()) == 1
def test_effective_execute_env_and_shebang_boundary(monkeypatch, tmp_path: Path) -> None:
    """Reject ineffective execute authority, env dispatch, and truncated shebangs."""
    import stat
    import topsailai.hooks.artifact_validation as validation
    from types import SimpleNamespace

    effective_uid = 1001
    status = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o410,
        st_uid=effective_uid,
        st_gid=2002,
    )
    with pytest.raises(validation.ArtifactValidationError, match="trust_rejected"):
        validation._validate_interpreter_status(status, effective_uid)

    source = tmp_path / "script"
    policy = ExecutablePlatformPolicy("posix", ("/usr/bin/env",))
    request = ArtifactCaptureRequest(source, "script", "script", policy)
    owner = type("Owner", (), {})()
    for payload, token in (
        (b"#!/usr/bin/env\n", "trust_rejected"),
        (b"#!" + b"x" * 4094, "unsupported_artifact_closure"),
    ):
        source.write_bytes(payload)
        descriptor = os.open(source, os.O_RDONLY)
        try:
            with pytest.raises(validation.ArtifactValidationError, match=token):
                validation._script_runtime(
                    descriptor, request, os.geteuid(), lambda: None, False, owner
                )
        finally:
            os.close(descriptor)


@pytest.mark.parametrize("primary_phase", ("read", "write", "fsync"))
@pytest.mark.parametrize(
    "close_error", (SystemExit("close host"), OSError("close ordinary")),
    ids=("host-close", "ordinary-close"),
)
def test_copy_primary_matrix_blocks_later_admission_io(
    monkeypatch, tmp_path: Path, primary_phase: str, close_error: BaseException
) -> None:
    """Allow only opens made inside the exact owned cleanup boundary."""
    import topsailai.hooks.artifact_store as store
    from topsailai.hooks import get_artifact_recovery_owner

    owner, request, _ = _script_fixture(tmp_path)
    primary = KeyboardInterrupt(f"{primary_phase} primary")
    target_descriptor: int | None = None
    primary_started = cleanup_active = False
    close_attempts = 0
    forbidden: list[str] = []
    cleanup_opens: list[tuple[object, int, int | None]] = []
    cleanup_slot = None
    real_open, real_close = store.os.open, store.os.close
    real_read, real_write = store.os.read, store.os.write
    real_fsync, real_chmod = store.os.fsync, store.os.chmod
    real_cleanup = store.ArtifactCaptureOwner._cleanup_slot
    cleanup_flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )

    def descriptor_path(descriptor: int) -> str:
        return os.readlink(f"/proc/self/fd/{descriptor}")

    def observed_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal target_descriptor
        if primary_started:
            if not cleanup_active:
                forbidden.append("open")
            else:
                assert cleanup_slot is not None
                parent = None if dir_fd is None else Path(descriptor_path(dir_fd))
                entry_names = {
                    value.split("/", 1)[0] for value, kind, _, _ in cleanup_slot.children
                    if kind == "directory"
                }
                allowed = (
                    Path(path) == owner._artifact_root and dir_fd is None
                ) or (
                    path == cleanup_slot.directory.name
                    and parent == owner._artifact_root
                ) or (
                    path in entry_names and parent == cleanup_slot.directory
                )
                assert allowed and flags == cleanup_flags
                cleanup_opens.append((path, flags, dir_fd))
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path).name == request.source_path.name and flags & os.O_WRONLY:
            target_descriptor = descriptor
        return descriptor

    def observed_read(descriptor: int, size: int) -> bytes:
        nonlocal primary_started
        if primary_started:
            forbidden.append("read")
        if (primary_phase == "read" and target_descriptor is not None
                and not primary_started
                and descriptor_path(descriptor) == str(request.source_path)):
            primary_started = True
            raise primary
        return real_read(descriptor, size)

    def observed_write(descriptor: int, value) -> int:
        nonlocal primary_started
        if primary_started:
            forbidden.append("write")
        if primary_phase == "write" and descriptor == target_descriptor:
            primary_started = True
            raise primary
        return real_write(descriptor, value)

    def observed_fsync(descriptor: int) -> None:
        nonlocal primary_started
        if primary_started:
            forbidden.append("fsync")
        if primary_phase == "fsync" and descriptor == target_descriptor:
            primary_started = True
            raise primary
        real_fsync(descriptor)

    def observed_chmod(*args, **kwargs) -> None:
        if primary_started:
            forbidden.append("chmod")
        real_chmod(*args, **kwargs)

    def observed_close(descriptor: int) -> None:
        nonlocal close_attempts
        if descriptor == target_descriptor:
            close_attempts += 1
            real_close(descriptor)
            raise close_error
        real_close(descriptor)

    def owned_cleanup(self, slot):
        nonlocal cleanup_active, cleanup_slot
        cleanup_slot = slot
        cleanup_active = True
        try:
            return real_cleanup(self, slot)
        finally:
            cleanup_active = False

    patches = (
        (store.os, "open", observed_open), (store.os, "close", observed_close),
        (store.os, "read", observed_read), (store.os, "write", observed_write),
        (store.os, "fsync", observed_fsync), (store.os, "chmod", observed_chmod),
        (store.ArtifactCaptureOwner, "_cleanup_slot", owned_cleanup),
        (store.ArtifactCaptureOwner, "_issue", lambda *a, **k: pytest.fail("issue")),
        (store, "validate_sealed_artifact", lambda *a, **k: pytest.fail("seal")),
    )
    for target, name, value in patches:
        monkeypatch.setattr(target, name, value)
    with pytest.raises(KeyboardInterrupt) as raised:
        owner.capture((request,))
    assert raised.value is primary and get_artifact_recovery_owner(primary) is owner
    assert close_attempts == 1 and forbidden == [] and cleanup_opens
    assert all(flags == cleanup_flags for _, flags, _ in cleanup_opens)
    debts = owner.cleanup_debts()
    assert len(debts) == 1 and cleanup_slot is owner._slots[debts[0].debt_id]
    records = tuple(cleanup_slot.ledger._records.values())
    assert len(records) == 1 and records[0].uncertain_close
    assert not records[0].uncertain_open
    wrong_parent = real_open(request.source_path, os.O_RDONLY)
    owned_parent = real_open(owner._artifact_root, cleanup_flags)
    cleanup_active = True
    try:
        bad_calls = (
            (cleanup_slot.directory.name, cleanup_flags, wrong_parent),
            (f"{cleanup_slot.directory.name}-sibling", cleanup_flags, owned_parent),
            (owner._artifact_root / cleanup_slot.directory.name, cleanup_flags, None),
            (owner._artifact_root, cleanup_flags | os.O_CREAT, None),
        )
        for path, flags, parent in bad_calls:
            with pytest.raises(AssertionError):
                observed_open(path, flags, dir_fd=parent)
    finally:
        cleanup_active = False
        real_close(owned_parent)
        real_close(wrong_parent)
    assert not owner.retry_cleanup(debts[0].debt_id) and close_attempts == 1
    probe = observed_open(request.source_path, os.O_RDONLY)
    try:
        observed_fsync(probe)
    finally:
        real_close(probe)
    assert forbidden[-2:] == ["open", "fsync"]
