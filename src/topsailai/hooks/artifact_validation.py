"""Linux-qualified trust validation for immutable hook artifact capture."""

from __future__ import annotations

import hashlib
import importlib.machinery
import os
import platform
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from topsailai.hooks.artifact_cleanup import (
    _checked_io,
    close_descriptor_chain as _close_descriptors,
    finalize_descriptor_chain as _finalize_descriptors,
    open_directory_chain as _open_directory_chain,
    require_fd_metadata_absent as _require_fd_metadata_absent,
)

from topsailai.hooks.artifact_contracts import (
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ArtifactFileIdentity,
    ArtifactInterpreterEvidence,
    ArtifactPythonRuntimeAuthority,
    ArtifactValidationEvidence,
)
from topsailai.hooks.artifact_identity import (
    native_runtime_fingerprint,
    python_runtime_fingerprint,
    shebang_runtime_fingerprint,
)
from topsailai.hooks.artifact_structure import (
    validate_capture_trust_structure,
    validate_request_structure,
)

_CHUNK_SIZE = 65_536
_INTERPRETER_LIMIT = 67_108_864
class ArtifactValidationError(Exception):
    """Carry one stable non-sensitive validation token."""

    def __init__(self, token: str) -> None:
        """Store one public rejection token."""
        self.token = token
        super().__init__(token)
class DescriptorOwner(Protocol):
    """Reserve, acquire, and release slot-owned descriptors."""

    def open_descriptor(
        self, path: str | Path, flags: int, mode: int = 0o777, *,
        dir_fd: int | None = None,
    ) -> int: ...

    def close_descriptor(self, descriptor: int) -> None: ...

@dataclass(frozen=True, slots=True)
class ValidatedSource:
    """Hold one pinned source descriptor and its admission evidence."""

    descriptor: int
    ancestry_descriptors: tuple[int, ...]
    ancestry_identities: tuple[tuple[int, int, int, int, int], ...]
    descriptor_owner: DescriptorOwner
    request: ArtifactCaptureRequest
    assertion: ArtifactClosureAssertion
    identity: ArtifactFileIdentity
    evidence: ArtifactValidationEvidence
    basename: str
    final_mode: int
def assertion_for_request(trust: ArtifactCaptureTrust, request: ArtifactCaptureRequest) -> ArtifactClosureAssertion:
    """Return the sole matching host assertion or reject closure."""
    matches = tuple(
        assertion
        for assertion in trust.closure_assertions
        if (assertion.source_path, assertion.kind, assertion.logical_name)
        == (request.source_path, request.kind, request.logical_name)
    )
    if len(matches) != 1:
        raise ArtifactValidationError("unsupported_artifact_closure")
    return matches[0]
def validate_artifact_root(
    artifact_root: Path,
    source_roots: tuple[Path, ...],
    expected_uid: int,
    checkpoint: Callable[[], None],
    descriptor_owner: DescriptorOwner,
) -> tuple[int, int, int, int]:
    """Validate a private root through one pinned no-follow descriptor chain."""
    descriptors: tuple[int, ...] = ()
    scope_primary: BaseException | None = None
    try:
        checkpoint()
        descriptors = _open_directory_chain(artifact_root, descriptor_owner, checkpoint)
        checkpoint()
        root_status = os.fstat(descriptors[-1])
        checkpoint()
        if root_status.st_uid != expected_uid or stat.S_IMODE(root_status.st_mode) != 0o700:
            raise ArtifactValidationError("artifact_storage_unavailable")
        _require_fd_metadata_absent(descriptors[-1], directory=True, checkpoint=checkpoint)
        checkpoint()
        for source_root in source_roots:
            if (
                artifact_root == source_root
                or artifact_root.is_relative_to(source_root)
                or source_root.is_relative_to(artifact_root)
            ):
                raise ArtifactValidationError("artifact_storage_unavailable")
    except BaseException as exc:
        scope_primary = exc
        if isinstance(exc, ArtifactValidationError):
            raise
        if isinstance(exc, (OSError, RuntimeError, ValueError)):
            raise ArtifactValidationError("artifact_storage_unavailable") from exc
        raise
    finally:
        _finalize_descriptors(descriptors, descriptor_owner, checkpoint, scope_primary)
    return (
        root_status.st_dev,
        root_status.st_ino,
        root_status.st_uid,
        stat.S_IMODE(root_status.st_mode),
    )
def validate_source_roots(
    roots: tuple[Path, ...], expected_uid: int, checkpoint: Callable[[], None],
    descriptor_owner: DescriptorOwner,
) -> tuple[Path, ...]:
    """Validate canonical roots through pinned descriptor-relative ancestry."""
    for root in roots:
        descriptors: tuple[int, ...] = ()
        scope_primary: BaseException | None = None
        try:
            checkpoint()
            descriptors = _open_directory_chain(root, descriptor_owner, checkpoint)
            checkpoint()
            if root == Path(root.anchor):
                raise ArtifactValidationError("trust_rejected")
            for index, descriptor in enumerate(descriptors):
                status = os.fstat(descriptor)
                checkpoint()
                _validate_directory_status(
                    status,
                    expected_uid,
                    require_read=index == len(descriptors) - 1,
                )
                _require_fd_metadata_absent(descriptor, directory=True, checkpoint=checkpoint)
                checkpoint()
        except BaseException as exc:
            scope_primary = exc
            if isinstance(exc, ArtifactValidationError):
                raise
            if isinstance(exc, (OSError, RuntimeError, ValueError)):
                raise ArtifactValidationError("trust_rejected") from exc
            raise
        finally:
            _finalize_descriptors(
                descriptors, descriptor_owner, checkpoint, scope_primary
            )
    for index, root in enumerate(roots):
        if any(
            root == other or root.is_relative_to(other) or other.is_relative_to(root)
            for other in roots[index + 1 :]
        ):
            raise ArtifactValidationError("trust_rejected")
    return roots
def open_validated_source(
    request: ArtifactCaptureRequest,
    assertion: ArtifactClosureAssertion,
    roots: tuple[Path, ...],
    expected_uid: int,
    checkpoint: Callable[[], None],
    python_evidence: ArtifactInterpreterEvidence | None,
    python_fingerprint: str | None,
    allow_native_scripts: bool,
    descriptor_owner: DescriptorOwner,
) -> ValidatedSource:
    """Open a source and retain its pinned descriptor-relative ancestry."""
    checkpoint()
    selected = tuple(root for root in roots if request.source_path.is_relative_to(root))
    if len(selected) != 1:
        raise ArtifactValidationError("trust_rejected")
    root = selected[0]
    descriptors: tuple[int, ...] = ()
    source_descriptor: int | None = None
    try:
        descriptors = _open_directory_chain(root, descriptor_owner, checkpoint)
        parent_fd = descriptors[-1]
        relative_parts = request.source_path.relative_to(root).parts
        for part in relative_parts[:-1]:
            checkpoint()
            descriptor = descriptor_owner.open_descriptor(
                part,
                _directory_open_flags(),
                dir_fd=parent_fd,
            )
            descriptors += (descriptor,)
            checkpoint()
            parent_fd = descriptor
            _validate_directory_status(os.fstat(descriptor), expected_uid)
            checkpoint()
            _require_fd_metadata_absent(descriptor, directory=True, checkpoint=checkpoint)
            checkpoint()
        checkpoint()
        source_descriptor = descriptor_owner.open_descriptor(
            relative_parts[-1],
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        checkpoint()
        status = os.fstat(source_descriptor)
        checkpoint()
        identity = file_identity(status)
        _validate_source_status(request, status, expected_uid)
        _require_fd_metadata_absent(source_descriptor, directory=False, checkpoint=checkpoint)
        basename, final_mode, runtime_digest, interpreter = _source_contract(
            source_descriptor,
            request,
            assertion,
            expected_uid,
            checkpoint,
            python_evidence,
            python_fingerprint,
            allow_native_scripts,
            descriptor_owner,
        )
        evidence = ArtifactValidationEvidence(
            root,
            request.source_path,
            identity,
            interpreter,
            runtime_digest,
            assertion.deployment_sha256,
            expected_uid,
            True,
        )
        ancestry_identities = _validated_ancestry(descriptors, expected_uid, checkpoint)
        return ValidatedSource(
            source_descriptor,
            descriptors,
            ancestry_identities,
            descriptor_owner,
            request,
            assertion,
            identity,
            evidence,
            request.source_path.name,
            final_mode,
        )
    except ArtifactValidationError as exc:
        _close_descriptors(
            descriptors + ((source_descriptor,) if source_descriptor is not None else ()),
            descriptor_owner, exc,
        )
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        _close_descriptors(
            descriptors + ((source_descriptor,) if source_descriptor is not None else ()),
            descriptor_owner, exc,
        )
        raise ArtifactValidationError("trust_rejected") from exc
    except BaseException as exc:
        scope_primary = exc
        _close_descriptors(
            descriptors + ((source_descriptor,) if source_descriptor is not None else ()),
            descriptor_owner, scope_primary,
        )
        raise
def validate_python_runtime(
    authority: ArtifactPythonRuntimeAuthority,
    expected_uid: int,
    checkpoint: Callable[[], None],
    descriptor_owner: DescriptorOwner,
) -> tuple[ArtifactInterpreterEvidence, str]:
    """Validate the host-attested ordinary CPython executable."""
    if sys.implementation.name != "cpython" or getattr(sys, "frozen", False):
        raise ArtifactValidationError("unsupported_platform")
    executable = Path(sys.executable)
    if not executable.is_absolute():
        raise ArtifactValidationError("unsupported_platform")
    descriptors: tuple[int, ...] = ()
    descriptor: int | None = None
    scope_primary: BaseException | None = None
    try:
        observed = Path(_checked_io(checkpoint, lambda: os.readlink("/proc/self/exe")))
        if str(observed).endswith(" (deleted)"):
            raise ArtifactValidationError("unsupported_platform")
        resolved = _checked_io(checkpoint, lambda: executable.resolve(strict=True))
        if resolved != authority.executable or observed != authority.executable:
            raise ArtifactValidationError("unsupported_platform")
        descriptors, ancestry_identities, descriptor = _open_absolute_file(
            authority.executable, expected_uid, checkpoint, descriptor_owner
        )
        checkpoint()
        status = os.fstat(descriptor)
        checkpoint()
        _validate_interpreter_status(status, expected_uid)
        _require_fd_metadata_absent(descriptor, directory=False, checkpoint=checkpoint)
        digest, size = hash_descriptor(descriptor, _INTERPRETER_LIMIT, checkpoint)
        if size != status.st_size or digest != authority.content_sha256:
            raise ArtifactValidationError("trust_rejected")
        _revalidate_interpreter(
            authority.executable, descriptor, file_identity(status), digest, descriptors,
            ancestry_identities, expected_uid, checkpoint, descriptor_owner,
        )
        checkpoint()
        current = os.stat("/proc/self/exe")
        checkpoint()
        if (current.st_dev, current.st_ino) != (status.st_dev, status.st_ino):
            raise ArtifactValidationError("artifact_source_changed")
        evidence = ArtifactInterpreterEvidence(
            authority.executable, file_identity(status), digest
        )
        fingerprint = python_runtime_fingerprint(
            authority.executable, digest, device=status.st_dev, inode=status.st_ino
        )
        return evidence, fingerprint
    except BaseException as exc:
        scope_primary = exc
        if isinstance(exc, ArtifactValidationError):
            raise
        if isinstance(exc, (OSError, RuntimeError, ValueError)):
            raise ArtifactValidationError("unsupported_platform") from exc
        raise
    finally:
        owned = descriptors + ((descriptor,) if descriptor is not None else ())
        _finalize_descriptors(owned, descriptor_owner, checkpoint, scope_primary)
def hash_descriptor(descriptor: int, limit: int, checkpoint: Callable[[], None]) -> tuple[str, int]:
    """Hash from offset zero with limit-plus-one observation."""
    checkpoint()
    os.lseek(descriptor, 0, os.SEEK_SET)
    checkpoint()
    digest = hashlib.sha256()
    total = 0
    while True:
        checkpoint()
        chunk = os.read(descriptor, min(_CHUNK_SIZE, limit - total + 1))
        checkpoint()
        if not chunk:
            return digest.hexdigest(), total
        total += len(chunk)
        if total > limit:
            raise ArtifactValidationError("artifact_byte_limit")
        digest.update(chunk)
def revalidate_source(source: ValidatedSource, checkpoint: Callable[[], None] = lambda: None) -> None:
    """Reject changed source or named ancestry through a second pinned traversal."""
    rewalk: tuple[int, ...] = ()
    scope_primary: BaseException | None = None
    try:
        if len(source.ancestry_descriptors) != len(source.ancestry_identities):
            raise ArtifactValidationError("artifact_source_changed")
        for descriptor, expected in zip(
            source.ancestry_descriptors, source.ancestry_identities, strict=True
        ):
            status = _checked_io(checkpoint, lambda descriptor=descriptor: os.fstat(descriptor))
            if _directory_identity(status) != expected:
                raise ArtifactValidationError("artifact_source_changed")
            _require_fd_metadata_absent(descriptor, directory=True, checkpoint=checkpoint)
        rewalk = _open_directory_chain(
            source.request.source_path.parent, source.descriptor_owner, checkpoint
        )
        rewalk_identities = _validated_ancestry(rewalk, source.evidence.checked_uid, checkpoint)
        if rewalk_identities != source.ancestry_identities:
            raise ArtifactValidationError("artifact_source_changed")
        current_status = _checked_io(checkpoint, lambda: os.fstat(source.descriptor))
        current = file_identity(current_status)
        named_status = _checked_io(
            checkpoint,
            lambda: os.stat(
                source.request.source_path.name,
                dir_fd=rewalk[-1],
                follow_symlinks=False,
            ),
        )
        named = file_identity(named_status)
        if current != source.identity or named != source.identity:
            raise ArtifactValidationError("artifact_source_changed")
        try:
            _validate_source_status(source.request, current_status, source.evidence.checked_uid)
            _require_fd_metadata_absent(source.descriptor, directory=False, checkpoint=checkpoint)
        except ArtifactValidationError as exc:
            raise ArtifactValidationError("artifact_source_changed") from exc
    except BaseException as exc:
        scope_primary = exc
        if isinstance(exc, ArtifactValidationError):
            raise
        if isinstance(exc, (OSError, RuntimeError, ValueError)):
            raise ArtifactValidationError("artifact_source_changed") from exc
        raise
    finally:
        _close_descriptors(rewalk, source.descriptor_owner, scope_primary)
def file_identity(status: os.stat_result) -> ArtifactFileIdentity:
    return ArtifactFileIdentity(
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
        stat.S_IMODE(status.st_mode),
        status.st_uid,
        status.st_gid,
        status.st_nlink,
    )
def _source_contract(
    descriptor: int,
    request: ArtifactCaptureRequest,
    assertion: ArtifactClosureAssertion,
    expected_uid: int,
    checkpoint: Callable[[], None],
    python_evidence: ArtifactInterpreterEvidence | None,
    python_fingerprint: str | None,
    allow_native_scripts: bool,
    descriptor_owner: DescriptorOwner,
) -> tuple[str, int, str, ArtifactInterpreterEvidence | None]:
    """Validate kind-specific naming, runtime, and executable format."""
    name = request.source_path.name
    if request.kind == "python_source":
        if name != f"{request.logical_name}.py" or python_fingerprint is None:
            raise ArtifactValidationError("unsupported_artifact_closure")
        runtime = python_fingerprint
        interpreter = python_evidence
    elif request.kind == "python_extension":
        suffix = next(
            (item for item in sorted(importlib.machinery.EXTENSION_SUFFIXES, key=len, reverse=True)
             if name == request.logical_name + item),
            None,
        )
        if suffix is None or python_fingerprint is None or not _compatible_elf(descriptor, checkpoint):
            raise ArtifactValidationError("unsupported_artifact_closure")
        runtime = python_fingerprint
        interpreter = python_evidence
    else:
        runtime, interpreter = _script_runtime(
            descriptor,
            request,
            expected_uid,
            checkpoint,
            allow_native_scripts,
            descriptor_owner,
        )
    if runtime != assertion.runtime_sha256:
        raise ArtifactValidationError("unsupported_artifact_closure")
    return name, 0o500 if request.kind == "script" else 0o400, runtime, interpreter
def _script_runtime(
    descriptor: int,
    request: ArtifactCaptureRequest,
    expected_uid: int,
    checkpoint: Callable[[], None],
    allow_native_scripts: bool,
    descriptor_owner: DescriptorOwner,
) -> tuple[str, ArtifactInterpreterEvidence | None]:
    """Validate an exact shebang or supported native Linux executable."""
    policy = request.script_policy
    assert policy is not None
    if policy.platform != "posix" or policy.native_suffixes:
        raise ArtifactValidationError("trust_rejected")
    checkpoint()
    os.lseek(descriptor, 0, os.SEEK_SET)
    checkpoint()
    prefix = os.read(descriptor, 4096)
    checkpoint()
    if prefix.startswith(b"#!"):
        if b"\n" not in prefix:
            raise ArtifactValidationError("unsupported_artifact_closure")
        line = prefix.split(b"\n", 1)[0]
        if b"\r" in line or b"\x00" in line:
            raise ArtifactValidationError("unsupported_artifact_closure")
        try:
            declaration = line[2:].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactValidationError("unsupported_artifact_closure") from exc
        if declaration != declaration.strip() or any(char.isspace() for char in declaration):
            raise ArtifactValidationError("unsupported_artifact_closure")
        path = Path(declaration)
        allowed = tuple(Path(item) for item in policy.allowed_interpreters)
        if str(path) != declaration:
            raise ArtifactValidationError("trust_rejected")
        if path == Path("/usr/bin/env"):
            raise ArtifactValidationError("trust_rejected")
        if not path.is_absolute() or path not in allowed:
            raise ArtifactValidationError("trust_rejected")
        evidence = _validate_script_interpreter(
            path, expected_uid, checkpoint, descriptor_owner
        )
        return shebang_runtime_fingerprint(
            path,
            evidence.content_sha256,
            device=evidence.identity.device,
            inode=evidence.identity.inode,
        ), evidence
    if not allow_native_scripts:
        raise ArtifactValidationError("trust_rejected")
    if not _compatible_elf_bytes(prefix):
        raise ArtifactValidationError("unsupported_artifact_closure")
    return native_runtime_fingerprint(), None
def _validate_script_interpreter(
    path: Path,
    expected_uid: int,
    checkpoint: Callable[[], None],
    descriptor_owner: DescriptorOwner,
) -> ArtifactInterpreterEvidence:
    """Validate and hash one canonical approved script interpreter."""
    descriptors: tuple[int, ...] = ()
    descriptor: int | None = None
    scope_primary: BaseException | None = None
    try:
        descriptors, ancestry_identities, descriptor = _open_absolute_file(
            path, expected_uid, checkpoint, descriptor_owner
        )
        checkpoint()
        status = os.fstat(descriptor)
        checkpoint()
        _validate_interpreter_status(status, expected_uid)
        _require_fd_metadata_absent(descriptor, directory=False, checkpoint=checkpoint)
        digest, size = hash_descriptor(descriptor, _INTERPRETER_LIMIT, checkpoint)
        if size != status.st_size:
            raise ArtifactValidationError("artifact_source_changed")
        initial = file_identity(status)
        _revalidate_interpreter(
            path, descriptor, initial, digest, descriptors, ancestry_identities,
            expected_uid, checkpoint, descriptor_owner,
        )
        return ArtifactInterpreterEvidence(path, initial, digest)
    except BaseException as exc:
        scope_primary = exc
        if isinstance(exc, ArtifactValidationError):
            raise
        if isinstance(exc, (OSError, RuntimeError, ValueError)):
            raise ArtifactValidationError("trust_rejected") from exc
        raise
    finally:
        owned = descriptors + ((descriptor,) if descriptor is not None else ())
        _finalize_descriptors(owned, descriptor_owner, checkpoint, scope_primary)
def _validate_source_status(
    request: ArtifactCaptureRequest, status: os.stat_result, expected_uid: int
) -> None:
    """Validate a source regular file's owner and mode."""
    if not stat.S_ISREG(status.st_mode) or status.st_uid not in (0, expected_uid):
        raise ArtifactValidationError("trust_rejected")
    mode = stat.S_IMODE(status.st_mode)
    if mode & 0o022 or mode & (stat.S_ISUID | stat.S_ISGID):
        raise ArtifactValidationError("trust_rejected")
    if request.kind == "script" and not _has_effective_execute(status, expected_uid):
        raise ArtifactValidationError("trust_rejected")
def _validate_interpreter_status(status: os.stat_result, expected_uid: int) -> None:
    """Validate one executable regular runtime file."""
    if not stat.S_ISREG(status.st_mode) or status.st_uid not in (0, expected_uid):
        raise ArtifactValidationError("trust_rejected")
    mode = stat.S_IMODE(status.st_mode)
    if mode & 0o022 or mode & (stat.S_ISUID | stat.S_ISGID) or not _has_effective_execute(
        status, expected_uid
    ):
        raise ArtifactValidationError("trust_rejected")
def _has_effective_execute(status: os.stat_result, expected_uid: int) -> bool:
    """Return whether the captured effective identity may execute the file."""
    mode = stat.S_IMODE(status.st_mode)
    if expected_uid == 0:
        return bool(mode & 0o111)
    if status.st_uid == expected_uid:
        return bool(mode & stat.S_IXUSR)
    groups = {os.getegid(), *os.getgroups()}
    return bool(mode & (stat.S_IXGRP if status.st_gid in groups else stat.S_IXOTH))
def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
def _open_absolute_file(
    path: Path, expected_uid: int, checkpoint: Callable[[], None],
    descriptor_owner: DescriptorOwner,
) -> tuple[tuple[int, ...], tuple[tuple[int, int, int, int, int], ...], int]:
    """Open a file and preserve its admitted ancestry security baseline."""
    descriptors = _open_directory_chain(path.parent, descriptor_owner, checkpoint)
    try:
        ancestry_identities = _validated_ancestry(descriptors, expected_uid, checkpoint)
        checkpoint()
        file_descriptor = descriptor_owner.open_descriptor(
            path.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptors[-1],
        )
        checkpoint()
    except BaseException as exc:
        scope_primary = exc
        _close_descriptors(descriptors, descriptor_owner, scope_primary)
        raise
    return descriptors, ancestry_identities, file_descriptor
def _validated_ancestry(
    descriptors: tuple[int, ...], expected_uid: int, checkpoint: Callable[[], None]
) -> tuple[tuple[int, int, int, int, int], ...]:
    """Observe safe directory identities and absent security metadata."""
    identities = []
    for descriptor in descriptors:
        checkpoint()
        status = os.fstat(descriptor)
        checkpoint()
        _validate_directory_status(status, expected_uid)
        _require_fd_metadata_absent(descriptor, directory=True, checkpoint=checkpoint)
        checkpoint()
        identities.append(_directory_identity(status))
    return tuple(identities)
def _revalidate_interpreter(
    path: Path, descriptor: int, initial: ArtifactFileIdentity, initial_digest: str,
    ancestry: tuple[int, ...],
    initial_ancestry: tuple[tuple[int, int, int, int, int], ...],
    expected_uid: int, checkpoint: Callable[[], None], descriptor_owner: DescriptorOwner,
) -> None:
    """Revalidate interpreter content, identity, metadata, and ancestry."""
    rewalk: tuple[int, ...] = ()
    scope_primary: BaseException | None = None
    try:
        try:
            pinned_ancestry = _validated_ancestry(ancestry, expected_uid, checkpoint)
        except ArtifactValidationError as exc:
            raise ArtifactValidationError("artifact_source_changed") from exc
        checkpoint()
        current_status = os.fstat(descriptor)
        checkpoint()
        try:
            _validate_interpreter_status(current_status, expected_uid)
            _require_fd_metadata_absent(descriptor, directory=False, checkpoint=checkpoint)
        except ArtifactValidationError as exc:
            raise ArtifactValidationError("artifact_source_changed") from exc
        checkpoint()
        current_digest, current_size = hash_descriptor(
            descriptor, _INTERPRETER_LIMIT, checkpoint
        )
        if (
            file_identity(current_status) != initial
            or current_size != initial.size
            or current_digest != initial_digest
        ):
            raise ArtifactValidationError("artifact_source_changed")
        rewalk = _open_directory_chain(path.parent, descriptor_owner, checkpoint)
        try:
            named_ancestry = _validated_ancestry(rewalk, expected_uid, checkpoint)
        except ArtifactValidationError as exc:
            raise ArtifactValidationError("artifact_source_changed") from exc
        if pinned_ancestry != initial_ancestry or named_ancestry != initial_ancestry:
            raise ArtifactValidationError("artifact_source_changed")
        checkpoint()
        named_status = os.stat(path.name, dir_fd=rewalk[-1], follow_symlinks=False)
        checkpoint()
        if file_identity(named_status) != initial:
            raise ArtifactValidationError("artifact_source_changed")
    except BaseException as exc:
        scope_primary = exc
        if isinstance(exc, ArtifactValidationError):
            raise
        if isinstance(exc, (OSError, RuntimeError, ValueError)):
            raise ArtifactValidationError("artifact_source_changed") from exc
        raise
    finally:
        _close_descriptors(rewalk, descriptor_owner, scope_primary)
def _validate_directory_status(
    status: os.stat_result, expected_uid: int, *, require_read: bool = False
) -> None:
    """Validate one pinned source-ancestry directory."""
    mode = stat.S_IMODE(status.st_mode)
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid not in (0, expected_uid)
        or mode & 0o022
        or mode & (stat.S_ISUID | stat.S_ISGID)
        or not mode & 0o111
        or (require_read and not mode & 0o444)
    ):
        raise ArtifactValidationError("trust_rejected")
def _directory_identity(status: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return stable pinned-directory identity and security facts."""
    return (
        status.st_dev,
        status.st_ino,
        status.st_uid,
        status.st_gid,
        stat.S_IMODE(status.st_mode),
    )
def _compatible_elf(descriptor: int, checkpoint: Callable[[], None]) -> bool:
    """Check the bounded ELF header against this process architecture."""
    checkpoint()
    os.lseek(descriptor, 0, os.SEEK_SET)
    checkpoint()
    header = os.read(descriptor, 64)
    checkpoint()
    return _compatible_elf_bytes(header)
def _compatible_elf_bytes(header: bytes) -> bool:
    """Return whether a bounded ELF header matches class and host machine."""
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return False
    expected_class = 2 if struct.calcsize("P") == 8 else 1
    machine = {"x86_64": 62, "aarch64": 183}.get(platform.machine())
    return header[4] == expected_class and int.from_bytes(header[18:20], "little") == machine
