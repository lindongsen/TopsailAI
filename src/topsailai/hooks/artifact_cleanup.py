"""Descriptor obligations and exact cleanup for immutable hook artifacts."""

from __future__ import annotations

import errno
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, TypeVar

_T = TypeVar("_T")
_MAX_DESCRIPTOR_OBLIGATIONS = 4096


def _checked_io(checkpoint: Callable[[], None], operation: Callable[[], _T]) -> _T:
    """Check liveness around I/O without replacing a host interruption."""
    checkpoint()
    try:
        result = operation()
    except Exception:
        checkpoint()
        raise
    checkpoint()
    return result

def preserve_cleanup_primary(primary: BaseException, cleanup: Callable[[], object]) -> None:
    """Attempt mandatory cleanup without replacing a host primary."""
    try:
        cleanup()
    except BaseException as cleanup_error:
        try:
            primary.add_note(f"artifact cleanup interrupted: {type(cleanup_error).__name__}")
        except BaseException:
            pass

@contextmanager
def _finalization_descriptor(
    ledger: DescriptorLedger,
    descriptor: int,
    checkpoint: Callable[[], None],
) -> Iterator[None]:
    """Close finalization I/O without replacing a host interruption."""
    try:
        yield
    except Exception:
        ledger.close(descriptor)
        checkpoint()
        raise
    except BaseException as primary:
        try:
            ledger.close(descriptor)
        except BaseException as cleanup_error:
            try:
                primary.add_note(
                    f"artifact cleanup interrupted: {type(cleanup_error).__name__}"
                )
            except BaseException:
                pass
        raise
    ledger.close(descriptor)
    checkpoint()


@dataclass(slots=True)
class _DescriptorObligation:
    """Track authority for one descriptor acquisition before it starts."""

    obligation_id: int
    descriptor: int | None = None
    uncertain_open: bool = False
    uncertain_close: bool = False


class DescriptorLedger:
    """Bound all descriptors and uncertain acquisitions owned by one capture slot."""

    __slots__ = ("_records", "_by_descriptor", "_next_id")

    def __init__(self) -> None:
        """Create an empty fixed-capacity ledger."""
        self._records: dict[int, _DescriptorObligation] = {}
        self._by_descriptor: dict[int, int] = {}
        self._next_id = 0

    @property
    def count(self) -> int:
        """Return the outstanding obligation count."""
        return len(self._records)

    def reserve_uncertain(self) -> None:
        """Retain one bounded obligation whose acquisition outcome is unknown."""
        self._reserve_record(uncertain=True)

    def _reserve_record(self, *, uncertain: bool = False) -> _DescriptorObligation:
        """Reserve exactly one record and settle interrupted empty publication."""
        if len(self._records) >= _MAX_DESCRIPTOR_OBLIGATIONS:
            from topsailai.hooks.artifact_validation import ArtifactValidationError

            raise ArtifactValidationError("artifact_capacity_exceeded")
        obligation_id = self._next_id
        self._next_id += 1
        record = _DescriptorObligation(obligation_id, uncertain_open=uncertain)
        try:
            self._records[obligation_id] = record
            return record
        except BaseException:
            if not uncertain:
                self._records.pop(obligation_id, None)
            raise

    def open(
        self,
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        """Reserve before open and protect authority through publication."""
        if len(self._records) >= _MAX_DESCRIPTOR_OBLIGATIONS:
            from topsailai.hooks.artifact_validation import ArtifactValidationError

            raise ArtifactValidationError("artifact_capacity_exceeded")
        obligation_id = self._next_id
        self._next_id += 1
        record = _DescriptorObligation(obligation_id)
        reservation_published = False
        acquisition_started = False
        descriptor: int | None = None
        try:
            self._records[obligation_id] = record
            reservation_published = True
            acquisition_started = True
            descriptor = os.open(path, flags, mode, dir_fd=dir_fd)
            record.descriptor = descriptor
            self._by_descriptor[descriptor] = record.obligation_id
        except BaseException as primary:
            if descriptor is None:
                if not acquisition_started:
                    if reservation_published or self._records.get(obligation_id) is record:
                        self._records.pop(obligation_id, None)
                elif isinstance(primary, OSError):
                    self._records.pop(obligation_id, None)
                else:
                    record.uncertain_open = True
            else:
                preserve_cleanup_primary(
                    primary,
                    lambda: self._settle_interrupted_publication(record, descriptor),
                )
            raise
        return descriptor

    def _settle_interrupted_publication(
        self, record: _DescriptorObligation, descriptor: int
    ) -> None:
        """Close the exact acquired descriptor after interrupted publication."""
        record.descriptor = None
        self._by_descriptor.pop(descriptor, None)
        record.uncertain_close = True
        os.close(descriptor)
        self._records.pop(record.obligation_id, None)

    def open_descriptor(
        self,
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        """Implement the validation descriptor-owner boundary."""
        return self.open(path, flags, mode, dir_fd=dir_fd)

    def close(self, descriptor: int) -> None:
        """Close once without reclaiming authority from an ambiguous result."""
        obligation_id = self._by_descriptor.pop(descriptor, None)
        if obligation_id is None:
            raise RuntimeError("descriptor is not owned by this capture slot")
        record = self._records[obligation_id]
        record.descriptor = None
        record.uncertain_close = True
        os.close(descriptor)
        self._records.pop(obligation_id, None)

    def close_descriptor(self, descriptor: int) -> None:
        """Implement the validation descriptor-owner boundary."""
        self.close(descriptor)

    def close_all(self) -> tuple[Exception, ...]:
        """Attempt confirmed descriptors without retrying lost close authority."""
        failures: list[Exception] = []
        for descriptor in tuple(self._by_descriptor):
            try:
                self.close(descriptor)
            except Exception as exc:
                failures.append(exc)
        return tuple(failures)

    def has_outstanding(self) -> bool:
        """Return whether confirmed or uncertain obligations remain."""
        return bool(self._records)


def open_directory_chain(path: Path, descriptor_owner, checkpoint=None) -> tuple[int, ...]:
    """Pin every lexical component with liveness checks around each open."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    check = checkpoint or (lambda: None)
    descriptors: list[int] = []
    try:
        check()
        current = descriptor_owner.open_descriptor(Path(path.anchor), flags)
        descriptors.append(current)
        check()
        for part in path.parts[1:]:
            check()
            current = descriptor_owner.open_descriptor(part, flags, dir_fd=current)
            descriptors.append(current)
            check()
    except BaseException as primary:
        close_descriptor_chain(tuple(descriptors), descriptor_owner, primary)
        raise
    return tuple(descriptors)


def close_descriptor_chain(
    descriptors: tuple[int, ...],
    descriptor_owner,
    primary: BaseException | None = None,
) -> None:
    """Close a chain while preserving an explicitly owned host primary."""
    cleanup_error: BaseException | None = None
    for descriptor in reversed(descriptors):
        try:
            descriptor_owner.close_descriptor(descriptor)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                if cleanup_error is None or isinstance(cleanup_error, Exception):
                    cleanup_error = exc
            elif cleanup_error is None:
                cleanup_error = exc
    if primary is not None and not isinstance(primary, Exception):
        if cleanup_error is not None:
            try:
                primary.add_note(
                    f"artifact cleanup interrupted: {type(cleanup_error).__name__}"
                )
            except BaseException:
                pass
        return
    if cleanup_error is not None:
        raise cleanup_error


def finalize_descriptor_chain(
    descriptors: tuple[int, ...],
    descriptor_owner,
    checkpoint: Callable[[], None],
    primary: BaseException | None = None,
) -> None:
    """Close a chain and arbitrate liveness for this explicit scope."""
    close_descriptor_chain(descriptors, descriptor_owner, primary)
    if primary is None or isinstance(primary, Exception):
        checkpoint()

@dataclass(slots=True)
class ArtifactRemovalProgress:
    """Retain exact confirmed deletion progress across bounded cleanup retries."""

    remaining_children: set[tuple[str, str, int, int]] | None = None
    directory_removed: bool = False


def remove_owned_artifact(
    root: Path,
    directory: Path | None,
    root_identity: tuple[int, int, int, int] | None,
    directory_identity: tuple[int, int] | None,
    expected_children: tuple[tuple[str, str, int, int], ...],
    debt_id: str,
    ledger: DescriptorLedger,
    progress: ArtifactRemovalProgress | None = None,
) -> bool:
    """Remove only exact remaining children and retain confirmed progress."""
    if directory is None:
        return not ledger.has_outstanding()
    if progress is None:
        progress = ArtifactRemovalProgress()
    if progress.directory_removed:
        return not ledger.has_outstanding()
    if progress.remaining_children is None:
        progress.remaining_children = set(expected_children)
    root_fd: int | None = None
    capture_fd: int | None = None
    scope_primary: BaseException | None = None
    try:
        root_fd = ledger.open(
            root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        status = os.fstat(root_fd)
        if root_identity is None or (
            status.st_dev,
            status.st_ino,
            status.st_uid,
            stat.S_IMODE(status.st_mode),
        ) != root_identity:
            return False
        capture_fd = ledger.open(
            directory.name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        capture_status = os.fstat(capture_fd)
        if directory_identity != (capture_status.st_dev, capture_status.st_ino):
            return False
        remaining = progress.remaining_children
        if tuple(sorted(_inventory_fd(capture_fd, ledger))) != tuple(sorted(remaining)):
            return False
        os.fchmod(capture_fd, 0o700)
        entry_records = sorted(
            (item for item in tuple(remaining) if item[1] == "directory"),
            key=lambda item: item[0],
        )
        for entry_record in entry_records:
            entry_name, _, entry_device, entry_inode = entry_record
            entry_fd = ledger.open(
                entry_name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=capture_fd,
            )
            entry_primary: BaseException | None = None
            try:
                entry_status = os.fstat(entry_fd)
                if (entry_status.st_dev, entry_status.st_ino) != (
                    entry_device,
                    entry_inode,
                ):
                    return False
                os.fchmod(entry_fd, 0o700)
                file_records = sorted(
                    (
                        item
                        for item in tuple(remaining)
                        if item[1] == "file"
                        and item[0].startswith(entry_name + "/")
                    ),
                    key=lambda item: item[0],
                )
                for file_record in file_records:
                    relative, _, device, inode = file_record
                    name = relative.split("/", 1)[1]
                    child = os.stat(name, dir_fd=entry_fd, follow_symlinks=False)
                    if not stat.S_ISREG(child.st_mode) or (
                        child.st_dev,
                        child.st_ino,
                    ) != (device, inode):
                        return False
                    os.unlink(name, dir_fd=entry_fd)
                    remaining.remove(file_record)
            except BaseException as exc:
                entry_primary = exc
                raise
            finally:
                close_descriptor_chain((entry_fd,), ledger, entry_primary)
            os.rmdir(entry_name, dir_fd=capture_fd)
            remaining.remove(entry_record)
        ledger.close(capture_fd)
        capture_fd = None
        os.rmdir(directory.name, dir_fd=root_fd)
        progress.directory_removed = True
    except (OSError, RuntimeError, ValueError) as exc:
        scope_primary = exc
        return False
    except BaseException as exc:
        scope_primary = exc
        raise
    finally:
        try:
            close_descriptor_chain(
                tuple(
                    descriptor
                    for descriptor in (capture_fd, root_fd)
                    if descriptor is not None
                ),
                ledger,
                scope_primary,
            )
        except Exception:
            pass
    if ledger.has_outstanding():
        return False
    try:
        print(f"Deleted owned hook artifact: {debt_id}")
    except Exception:
        pass
    return True


def _inventory_fd(
    directory_fd: int, ledger: DescriptorLedger
) -> tuple[tuple[str, str, int, int], ...]:
    """Observe exact two-level inventory through a pinned directory."""
    values: list[tuple[str, str, int, int]] = []
    for name in os.listdir(directory_fd):
        status = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(status.st_mode):
            values.append((name, "directory", status.st_dev, status.st_ino))
            entry_fd = ledger.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            entry_primary: BaseException | None = None
            try:
                for child_name in os.listdir(entry_fd):
                    child = os.stat(child_name, dir_fd=entry_fd, follow_symlinks=False)
                    kind = "file" if stat.S_ISREG(child.st_mode) else "other"
                    values.append(
                        (f"{name}/{child_name}", kind, child.st_dev, child.st_ino)
                    )
            except BaseException as exc:
                entry_primary = exc
                raise
            finally:
                close_descriptor_chain((entry_fd,), ledger, entry_primary)
        else:
            values.append((name, "other", status.st_dev, status.st_ino))
    return tuple(values)


def require_fd_metadata_absent(
    descriptor: int, *, directory: bool, checkpoint=None
) -> None:
    """Reject ACL/capability metadata with checks around every query."""
    names = ("system.posix_acl_access", "security.capability")
    if directory:
        names += ("system.posix_acl_default",)
    check = checkpoint or (lambda: None)
    for name in names:
        check()
        try:
            value = os.getxattr(descriptor, name)
        except OSError as exc:
            check()
            if exc.errno in (errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP):
                continue
            from topsailai.hooks.artifact_validation import ArtifactValidationError

            raise ArtifactValidationError("trust_rejected") from exc
        check()
        if value:
            from topsailai.hooks.artifact_validation import ArtifactValidationError

            raise ArtifactValidationError("trust_rejected")


def validate_sealed_artifact(
    directory: Path,
    directory_identity: tuple[int, int],
    entries,
    expected_children: tuple[tuple[str, str, int, int], ...],
    expected_uid: int,
    ledger: DescriptorLedger,
    checkpoint,
) -> None:
    """Verify exact sealed metadata and inventory through pinned descriptors."""
    from topsailai.hooks.artifact_validation import ArtifactValidationError

    checkpoint()
    capture_fd = ledger.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    with _finalization_descriptor(ledger, capture_fd, checkpoint):
        try:
            checkpoint()
            capture_status = os.fstat(capture_fd)
            checkpoint()
            if (
                not stat.S_ISDIR(capture_status.st_mode)
                or (capture_status.st_dev, capture_status.st_ino) != directory_identity
                or capture_status.st_uid != expected_uid
                or stat.S_IMODE(capture_status.st_mode) != 0o500
            ):
                raise ArtifactValidationError("artifact_storage_unavailable")
            require_fd_metadata_absent(capture_fd, directory=True, checkpoint=checkpoint)
            observed: list[tuple[str, str, int, int]] = []
            for entry in entries:
                checkpoint()
                entry_name, file_name = entry.relative_path.split("/", 1)
                entry_fd = ledger.open(
                    entry_name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=capture_fd,
                )
                with _finalization_descriptor(ledger, entry_fd, checkpoint):
                    checkpoint()
                    entry_status = os.fstat(entry_fd)
                    checkpoint()
                    if (
                        not stat.S_ISDIR(entry_status.st_mode)
                        or entry_status.st_uid != expected_uid
                        or stat.S_IMODE(entry_status.st_mode) != 0o500
                    ):
                        raise ArtifactValidationError("artifact_storage_unavailable")
                    require_fd_metadata_absent(
                        entry_fd, directory=True, checkpoint=checkpoint
                    )
                    observed.append(
                        (entry_name, "directory", entry_status.st_dev, entry_status.st_ino)
                    )
                    file_fd = ledger.open(
                        file_name,
                        os.O_RDONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=entry_fd,
                    )
                    with _finalization_descriptor(ledger, file_fd, checkpoint):
                        checkpoint()
                        file_status = os.fstat(file_fd)
                        checkpoint()
                        if (
                            not stat.S_ISREG(file_status.st_mode)
                            or file_status.st_uid != expected_uid
                            or stat.S_IMODE(file_status.st_mode) != entry.mode
                            or file_status.st_nlink != 1
                        ):
                            raise ArtifactValidationError("artifact_storage_unavailable")
                        require_fd_metadata_absent(
                            file_fd, directory=False, checkpoint=checkpoint
                        )
                        observed.append(
                            (
                                entry.relative_path,
                                "file",
                                file_status.st_dev,
                                file_status.st_ino,
                            )
                        )
                    if tuple(os.listdir(entry_fd)) != (file_name,):
                        raise ArtifactValidationError("artifact_storage_unavailable")
            if tuple(sorted(observed)) != tuple(sorted(expected_children)):
                raise ArtifactValidationError("artifact_storage_unavailable")
            if tuple(sorted(os.listdir(capture_fd))) != tuple(
                sorted(entry.relative_path.split("/", 1)[0] for entry in entries)
            ):
                raise ArtifactValidationError("artifact_storage_unavailable")
        except ArtifactValidationError as exc:
            if exc.token == "artifact_storage_unavailable":
                raise
            raise ArtifactValidationError("artifact_storage_unavailable") from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise ArtifactValidationError("artifact_storage_unavailable") from exc
