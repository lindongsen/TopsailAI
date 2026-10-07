"""Bounded owner for immutable framework hook artifacts."""

from __future__ import annotations

import os
import secrets
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

from topsailai.hooks.artifact_cleanup import (
    ArtifactRemovalProgress,
    DescriptorLedger,
    _finalization_descriptor,
    preserve_cleanup_primary,
    remove_owned_artifact,
    validate_sealed_artifact,
)
from topsailai.hooks.artifact_contracts import (
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureResult,
    ArtifactCaptureTrust,
    ArtifactCleanupDebt,
    ArtifactDisposeResult,
    ArtifactInventoryEntry,
)
from topsailai.hooks.artifact_identity import artifact_identity
from topsailai.hooks.artifact_structure import (
    valid_root_spelling as _valid_root_spelling,
    validate_capture_call as _validate_call,
    validate_resource_free as _validate_resource_free,
)
from topsailai.hooks.artifact_store_managed import ArtifactCaptureOwnerConstruction
from topsailai.hooks.artifact_validation import (
    ArtifactValidationError,
    ValidatedSource,
    assertion_for_request,
    open_validated_source,
    revalidate_source,
    validate_artifact_root,
    validate_python_runtime,
    validate_request_structure,
    validate_source_roots,
)

_MAX_SLOTS = 16
_MAX_OWNER_ENTRIES = 128
_MAX_OWNER_BYTES = 67_108_864
_CHUNK_SIZE = 65_536
_ISSUER = object()

class _Cancelled(Exception):
    """Signal one latched cooperative cancellation."""

class _TimedOut(Exception):
    """Signal one cooperative absolute deadline expiry."""

@dataclass(slots=True)
class _Slot:
    """Own one bounded live capture or unsettled cleanup obligation."""

    debt_id: str
    reserved_entries: int
    reserved_bytes: int
    directory: Path | None = None
    root_identity: tuple[int, int, int, int] | None = None
    directory_identity: tuple[int, int] | None = None
    children: tuple[tuple[str, str, int, int], ...] = ()
    artifact: CapturedArtifact | None = None
    disposed: bool = False
    cleanup_pending: bool = False
    ledger: DescriptorLedger = field(default_factory=DescriptorLedger)
    removal: ArtifactRemovalProgress = field(default_factory=ArtifactRemovalProgress)
    uncertain_creation: bool = False

class CapturedArtifact:
    """Expose an immutable owner-issued artifact summary and sensitive locator."""

    __slots__ = (
        "_identity", "_entries", "_total_bytes", "_directory", "_disposed", "_issuer"
    )

    def __init__(self, issuer: object, identity: str, entries: tuple[ArtifactInventoryEntry, ...],
                 total_bytes: int, directory: Path | None) -> None:
        """Construct only for the owning implementation."""
        if issuer is not _ISSUER:
            raise TypeError("CapturedArtifact has no public constructor")
        self._identity = identity
        self._entries = entries
        self._total_bytes = total_bytes
        self._directory = directory
        self._disposed = False
        self._issuer: ArtifactCaptureOwner | None = None

    @property
    def identity(self) -> str:
        """Return the stable framed artifact identity."""
        return self._identity

    @property
    def entries(self) -> tuple[ArtifactInventoryEntry, ...]:
        """Return the immutable ordered inventory."""
        return self._entries

    @property
    def total_bytes(self) -> int:
        """Return the complete captured payload byte count."""
        return self._total_bytes

    @property
    def directory(self) -> Path:
        """Return the sensitive host locator for a nonempty live artifact."""
        if self._directory is None:
            raise RuntimeError("empty artifact has no directory")
        return self._directory

    @property
    def disposed(self) -> bool:
        """Return whether the owner logically disposed this artifact."""
        return self._disposed

    def __reduce__(self):
        """Reject serialization of owner-issued authority."""
        raise TypeError("CapturedArtifact is not serializable")

class ArtifactCaptureOwner(ArtifactCaptureOwnerConstruction):
    """Capture, retain, and explicitly clean a bounded immutable artifact set."""

    def __init__(self, *, artifact_root: str, trust: ArtifactCaptureTrust) -> None:
        """Validate only detached structure without filesystem access."""
        super().__init__(artifact_root=artifact_root, trust=trust)

    def __enter__(self) -> ArtifactCaptureOwner:
        """Return this explicit lifecycle owner."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Close owned artifacts without suppressing a body exception."""
        try:
            self.close()
        except BaseException as cleanup_error:
            if exc is None:
                _attach_recovery_owner(cleanup_error, self)
                raise
            _attach_recovery_owner(exc, self)
            try:
                exc.add_note(
                    f"artifact cleanup interrupted: {type(cleanup_error).__name__}"
                )
            except BaseException:
                pass
        return False

    def capture(
        self,
        requests: tuple[ArtifactCaptureRequest, ...],
        *,
        policy: ArtifactCapturePolicy = ArtifactCapturePolicy(),
        cancellation: threading.Event | None = None,
        deadline: float | None = None,
    ) -> ArtifactCaptureResult:
        """Atomically capture an exact ordered request inventory."""
        start = time.monotonic()
        token = _validate_call(requests, policy, cancellation, deadline)
        if token is not None:
            return _rejected(token)
        assert type(requests) is tuple and type(policy) is ArtifactCapturePolicy
        absolute_deadline = start + policy.timeout_ms / 1000
        if deadline is not None:
            absolute_deadline = min(absolute_deadline, deadline)
        latched_cancel = False

        def checkpoint() -> None:
            nonlocal latched_cancel
            latched_cancel = latched_cancel or bool(cancellation and cancellation.is_set())
            if latched_cancel:
                raise _Cancelled
            if time.monotonic() >= absolute_deadline:
                raise _TimedOut

        try:
            with self._lock:
                if self._closed:
                    return _rejected("artifact_owner_closed")
                if not sys.platform.startswith("linux"):
                    return _rejected("unsupported_platform")
                checkpoint()
                token = _validate_resource_free(requests, policy, self._trust)
                if token is not None:
                    return _rejected(token)
                reserved_bytes = 0 if not requests else policy.max_total_bytes
                if not self._has_capacity(len(requests), reserved_bytes):
                    return _rejected("artifact_capacity_exceeded")
                slot = _Slot(
                    debt_id=f"artifact-{secrets.token_hex(16)}",
                    reserved_entries=len(requests),
                    reserved_bytes=reserved_bytes,
                )
                recovery = self._managed_recovery
                if recovery is not None:
                    recovery._bind_capture_slot(slot)
                return self._capture_reserved(slot, requests, policy, checkpoint)
        except _Cancelled:
            return _rejected("artifact_capture_cancelled")
        except _TimedOut:
            return _rejected("artifact_capture_timeout")

    def dispose(self, artifact: CapturedArtifact) -> ArtifactDisposeResult:
        """Logically dispose one exact owner-issued artifact and attempt cleanup."""
        with self._lock:
            if not isinstance(artifact, CapturedArtifact) or artifact._issuer is not self:
                return ArtifactDisposeResult(False, errors=("invalid_artifact",))
            slot = self._issued.get(id(artifact))
            if slot is None:
                if artifact._disposed:
                    return ArtifactDisposeResult(True, already_disposed=True)
                return ArtifactDisposeResult(False, errors=("invalid_artifact",))
            already = artifact._disposed
            artifact._disposed = True
            slot.disposed = True
            try:
                settled = self._cleanup_slot(slot)
            except BaseException as primary:
                _attach_recovery_owner(primary, self)
                raise
            return ArtifactDisposeResult(
                True,
                already,
                not settled,
                () if settled else ("artifact_cleanup_pending",),
            )

    def close(self) -> ArtifactDisposeResult:
        """Close the owner and attempt every slot after ordinary failures."""
        with self._lock:
            already = self._closed
            self._closed = True
            slots = tuple(self._slots.values())
            for slot in slots:
                if slot.artifact is not None:
                    slot.artifact._disposed = True
                    slot.disposed = True
            pending = False
            for slot in slots:
                try:
                    settled = self._cleanup_slot(slot)
                except Exception:
                    slot.cleanup_pending = True
                    settled = False
                except BaseException as primary:
                    _attach_recovery_owner(primary, self)
                    raise
                if not settled:
                    pending = True
            return ArtifactDisposeResult(
                True, already, pending, ("artifact_cleanup_pending",) if pending else ()
            )

    def cleanup_debts(self) -> tuple[ArtifactCleanupDebt, ...]:
        """Return stable opaque cleanup debts without sensitive locators."""
        with self._lock:
            return tuple(
                ArtifactCleanupDebt(slot.debt_id, "artifact_cleanup_pending")
                for slot in sorted(self._slots.values(), key=lambda item: item.debt_id)
                if slot.cleanup_pending
            )

    def retry_cleanup(self, debt_id: str) -> bool:
        """Attempt one bounded cleanup pass for an exact outstanding debt."""
        with self._lock:
            slot = self._slots.get(debt_id)
            if slot is None or not slot.cleanup_pending:
                return False
            try:
                return self._cleanup_slot(slot)
            except BaseException as primary:
                _attach_recovery_owner(primary, self)
                raise

    def _capture_reserved(
        self,
        slot: _Slot,
        requests: tuple[ArtifactCaptureRequest, ...],
        policy: ArtifactCapturePolicy,
        checkpoint,
    ) -> ArtifactCaptureResult:
        """Publish and execute one capture under one recovery scope."""
        sources: list[ValidatedSource] = []
        primary = "artifact_internal_error"
        try:
            self._slots[slot.debt_id] = slot
            checkpoint()
            uid = os.geteuid()
            if self._bound_uid is None:
                self._bound_uid = uid
            elif self._bound_uid != uid:
                raise ArtifactValidationError("trust_rejected")
            roots = validate_source_roots(
                self._trust.source_roots, uid, checkpoint, slot.ledger
            )
            root_identity = validate_artifact_root(
                self._artifact_root, roots, uid, checkpoint, slot.ledger
            )
            checkpoint()
            if self._root_identity is None:
                self._root_identity = root_identity
            elif self._root_identity != root_identity:
                raise ArtifactValidationError("artifact_storage_unavailable")
            slot.root_identity = root_identity
            python_evidence = None
            python_fingerprint = None
            if any(item.kind != "script" for item in requests):
                authority = self._trust.python_runtime
                if authority is None:
                    raise ArtifactValidationError("unsupported_platform")
                python_evidence, python_fingerprint = validate_python_runtime(
                    authority, uid, checkpoint, slot.ledger
                )
                if self._python_fingerprint not in (None, python_fingerprint):
                    raise ArtifactValidationError("trust_rejected")
            if not requests:
                if slot.ledger.close_all() or slot.ledger.has_outstanding():
                    return _rejected("artifact_cleanup_pending", self)
                checkpoint()
                artifact = self._issue(slot, (), (), 0, None)
                return ArtifactCaptureResult(True, artifact)
            self._create_capture_directory(slot, checkpoint)
            assert slot.directory is not None and slot.directory_identity is not None
            entries: list[ArtifactInventoryEntry] = []
            children: list[tuple[str, str, int, int]] = []
            total = 0
            for index, request in enumerate(requests):
                checkpoint()
                source = open_validated_source(
                    request,
                    assertion_for_request(self._trust, request),
                    roots,
                    uid,
                    checkpoint,
                    python_evidence,
                    python_fingerprint,
                    self._trust.allow_native_scripts,
                    slot.ledger,
                )
                sources.append(source)
                entry, created, copied = self._copy_source(
                    slot, slot.directory, index, source, policy, total, checkpoint
                )
                total += copied
                entries.append(entry)
                children.extend(created)
                slot.children = tuple(children)
            for source in sources:
                checkpoint()
                revalidate_source(source, checkpoint)
                checkpoint()
            if not self._close_sources(slot, sources, checkpoint):
                raise ArtifactValidationError("artifact_cleanup_pending")
            sources.clear()
            self._seal_and_sync(slot, slot.directory, children, entries, checkpoint)
            slot.reserved_bytes = total
            if python_fingerprint is not None:
                self._python_fingerprint = python_fingerprint
            checkpoint()
            if slot.ledger.has_outstanding():
                raise ArtifactValidationError("artifact_cleanup_pending")
            artifact = self._issue(
                slot, tuple(entries), tuple(item.script_policy for item in requests),
                total, slot.directory,
            )
            return ArtifactCaptureResult(True, artifact)
        except ArtifactValidationError as exc:
            primary = exc.token
        except _Cancelled:
            primary = "artifact_capture_cancelled"
        except _TimedOut:
            primary = "artifact_capture_timeout"
        except (OSError, RuntimeError, ValueError):
            primary = "artifact_storage_unavailable"
        except Exception:
            primary = "artifact_internal_error"
        except BaseException as exc:
            cleanup_errors: list[BaseException] = []
            try:
                self._close_sources(slot, sources)
            except BaseException as cleanup_error:
                slot.cleanup_pending = True
                cleanup_errors.append(cleanup_error)
            try:
                settled = self._cleanup_slot(slot)
            except BaseException as cleanup_error:
                slot.cleanup_pending = True
                settled = False
                cleanup_errors.append(cleanup_error)
            if not settled:
                _attach_recovery_owner(exc, self)
            for cleanup_error in cleanup_errors:
                try:
                    exc.add_note(
                        f"artifact cleanup interrupted: {type(cleanup_error).__name__}"
                    )
                except BaseException:
                    pass
            raise
        slot.cleanup_pending = True
        try:
            if primary not in ("artifact_capture_cancelled", "artifact_capture_timeout"):
                try:
                    checkpoint()
                except _Cancelled:
                    primary = "artifact_capture_cancelled"
                except _TimedOut:
                    primary = "artifact_capture_timeout"
            self._close_sources(slot, sources)
            if not self._cleanup_slot(slot):
                return _rejected("artifact_cleanup_pending", self)
        except BaseException as cleanup_primary:
            slot.cleanup_pending = True
            preserve_cleanup_primary(
                cleanup_primary, lambda: self._cleanup_slot(slot)
            )
            if slot.cleanup_pending or slot.ledger.has_outstanding():
                _attach_recovery_owner(cleanup_primary, self)
            raise
        return _rejected(primary)

    def _copy_source(
        self, slot: _Slot, directory: Path, index: int, source: ValidatedSource,
        policy: ArtifactCapturePolicy, prior_total: int, checkpoint,
    ) -> tuple[ArtifactInventoryEntry, tuple[tuple[str, str, int, int], ...], int]:
        """Copy one pinned source with bounded reads and complete writes."""
        entry_name = f"entry-{index:06d}"
        entry_directory = directory / entry_name
        checkpoint()
        entry_directory.mkdir(mode=0o700)
        checkpoint()
        entry_status = entry_directory.lstat()
        checkpoint()
        slot.children += ((entry_name, "directory", entry_status.st_dev, entry_status.st_ino),)
        target = entry_directory / source.basename
        checkpoint()
        descriptor = slot.ledger.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        checkpoint()
        target_status = os.fstat(descriptor)
        checkpoint()
        relative = f"{entry_name}/{source.basename}"
        slot.children += ((relative, "file", target_status.st_dev, target_status.st_ino),)
        import hashlib
        digest = hashlib.sha256()
        total = 0
        content_digest = ""
        with _finalization_descriptor(slot.ledger, descriptor, checkpoint):
            checkpoint()
            os.lseek(source.descriptor, 0, os.SEEK_SET)
            checkpoint()
            while True:
                checkpoint()
                remaining = min(
                    policy.max_file_bytes - total,
                    policy.max_total_bytes - prior_total - total,
                )
                try:
                    chunk = os.read(source.descriptor, min(_CHUNK_SIZE, remaining + 1))
                except OSError as exc:
                    checkpoint()
                    raise ArtifactValidationError("trust_rejected") from exc
                checkpoint()
                if not chunk:
                    break
                total += len(chunk)
                if total > policy.max_file_bytes or prior_total + total > policy.max_total_bytes:
                    raise ArtifactValidationError("artifact_byte_limit")
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    checkpoint()
                    written = os.write(descriptor, view)
                    checkpoint()
                    if written <= 0:
                        raise OSError("zero write")
                    view = view[written:]
            if total != source.identity.size:
                raise ArtifactValidationError("artifact_source_changed")
            content_digest = digest.hexdigest()
            if content_digest != source.assertion.content_sha256:
                raise ArtifactValidationError("unsupported_artifact_closure")
            checkpoint()
            os.fsync(descriptor)
            checkpoint()
        os.chmod(target, source.final_mode)
        checkpoint()
        target_status = target.lstat()
        checkpoint()
        inventory = ArtifactInventoryEntry(
            index, source.request.kind, source.request.logical_name, relative,
            total, content_digest, source.final_mode, source.evidence,
        )
        children = (
            (entry_name, "directory", entry_status.st_dev, entry_status.st_ino),
            (relative, "file", target_status.st_dev, target_status.st_ino),
        )
        return inventory, children, total

    def _seal_and_sync(
        self, slot: _Slot, directory: Path,
        children: list[tuple[str, str, int, int]],
        entries: list[ArtifactInventoryEntry], checkpoint,
    ) -> None:
        """Read back bytes, seal modes, and durably sync the exact inventory."""
        import hashlib
        for entry in entries:
            checkpoint()
            path = directory / entry.relative_path
            descriptor = slot.ledger.open(
                path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            with _finalization_descriptor(slot.ledger, descriptor, checkpoint):
                digest = hashlib.sha256()
                size = 0
                while True:
                    checkpoint()
                    remaining = entry.size_bytes - size
                    chunk = os.read(descriptor, min(_CHUNK_SIZE, remaining + 1))
                    checkpoint()
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > entry.size_bytes:
                        raise ArtifactValidationError("artifact_storage_unavailable")
                    digest.update(chunk)
                if size != entry.size_bytes or digest.hexdigest() != entry.content_sha256:
                    raise ArtifactValidationError("artifact_storage_unavailable")
                checkpoint()
                os.fsync(descriptor)
                checkpoint()
            checkpoint()
            path.parent.chmod(0o500)
            checkpoint()
            _fsync_directory(path.parent, slot.ledger, checkpoint)
        checkpoint()
        directory.chmod(0o500)
        checkpoint()
        _fsync_directory(directory, slot.ledger, checkpoint)
        _fsync_directory(self._artifact_root, slot.ledger, checkpoint)
        if slot.directory_identity is None:
            raise ArtifactValidationError("artifact_storage_unavailable")
        validate_sealed_artifact(
            directory,
            slot.directory_identity,
            tuple(entries),
            tuple(children),
            os.geteuid(),
            slot.ledger,
            checkpoint,
        )

    def _issue(
        self,
        slot: _Slot,
        entries: tuple[ArtifactInventoryEntry, ...],
        policies: tuple[object, ...],
        total: int,
        directory: Path | None,
    ) -> CapturedArtifact:
        """Publish one object only after every descriptor and liveness check."""
        identity = artifact_identity(entries, policies, self._trust.allow_native_scripts)
        artifact = CapturedArtifact(_ISSUER, identity, entries, total, directory)
        artifact._issuer = self
        slot.artifact = artifact
        self._issued[id(artifact)] = slot
        return artifact

    def _create_capture_directory(self, slot: _Slot, checkpoint) -> None:
        """Arm responsibility before creation and publish identity before returning."""
        for _ in range(128):
            candidate = self._artifact_root / f"capture-{secrets.token_hex(16)}"
            slot.directory = candidate
            slot.uncertain_creation = True
            try:
                checkpoint()
                candidate.mkdir(mode=0o700)
                checkpoint()
            except FileExistsError:
                slot.directory = None
                slot.uncertain_creation = False
                continue
            except BaseException:
                raise
            status = candidate.lstat()
            checkpoint()
            slot.directory_identity = (status.st_dev, status.st_ino)
            slot.uncertain_creation = False
            return
        raise ArtifactValidationError("artifact_storage_unavailable")

    def _close_sources(self, slot: _Slot, sources: list[ValidatedSource], checkpoint=None) -> bool:
        """Close source descriptors and report whether every close was confirmed."""
        settled = True
        for source in sources:
            for descriptor in (source.descriptor, *reversed(source.ancestry_descriptors)):
                try:
                    slot.ledger.close(descriptor)
                    if checkpoint is not None:
                        checkpoint()
                except (OSError, RuntimeError):
                    slot.cleanup_pending = True
                    settled = False
                except BaseException:
                    slot.cleanup_pending = True
                    raise
        return settled and not slot.ledger.has_outstanding()

    def _cleanup_slot(self, slot: _Slot) -> bool:
        """Settle an exact slot or retain one bounded opaque debt."""
        slot.cleanup_pending = True
        slot.ledger.close_all()
        if slot.directory is not None and not slot.uncertain_creation:
            settled = remove_owned_artifact(
                self._artifact_root,
                slot.directory,
                slot.root_identity,
                slot.directory_identity,
                slot.children,
                slot.debt_id,
                slot.ledger,
                slot.removal,
            )
        else:
            settled = slot.directory is None and not slot.uncertain_creation
        settled = settled and not slot.ledger.has_outstanding()
        slot.cleanup_pending = not settled
        if settled:
            self._slots.pop(slot.debt_id, None)
            if slot.artifact is not None:
                self._issued.pop(id(slot.artifact), None)
        return settled

    def _has_capacity(self, entries: int, payload: int) -> bool:
        """Check owner-wide live-and-debt reservations without filesystem I/O."""
        return (
            len(self._slots) < _MAX_SLOTS
            and sum(slot.reserved_entries for slot in self._slots.values()) + entries <= _MAX_OWNER_ENTRIES
            and sum(slot.reserved_bytes for slot in self._slots.values()) + payload <= _MAX_OWNER_BYTES
        )

def get_artifact_recovery_owner(error: BaseException) -> ArtifactCaptureOwner | None:
    """Return the owner attached to an interrupted standalone call."""
    value = getattr(error, "_topsailai_artifact_recovery_owner", None)
    return value if isinstance(value, ArtifactCaptureOwner) else None


def _attach_recovery_owner(error: BaseException, owner: ArtifactCaptureOwner) -> None:
    """Route bounded recovery without changing exception identity."""
    try:
        recovery = owner._managed_recovery
        if recovery is None:
            setattr(error, "_topsailai_artifact_recovery_owner", owner)
        else:
            setattr(error, "_topsailai_artifact_lease_recovery", recovery)
    except BaseException:
        pass


def _rejected(token: str, owner: ArtifactCaptureOwner | None = None) -> ArtifactCaptureResult:
    """Build one bounded rejection result without leaking a managed owner."""
    recovery_owner = owner if owner is not None and owner._managed_recovery is None else None
    return ArtifactCaptureResult(False, errors=(token,), recovery_owner=recovery_owner)

def _fsync_directory(path: Path, ledger: DescriptorLedger, checkpoint) -> None:
    """Synchronize one directory through a slot-owned descriptor."""
    checkpoint()
    descriptor = ledger.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    with _finalization_descriptor(ledger, descriptor, checkpoint):
        checkpoint()
        os.fsync(descriptor)
        checkpoint()
