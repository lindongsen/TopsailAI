"""Focused U07 validation and cleanup coverage closure tests."""

from __future__ import annotations

import builtins
import errno
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks import ArtifactCaptureOwner, ArtifactCaptureTrust
from topsailai.hooks.artifact_cleanup import (
    DescriptorLedger,
    remove_owned_artifact,
    validate_sealed_artifact,
)
from topsailai.hooks.artifact_contracts import (
    ArtifactCaptureRequest,
    ArtifactClosureAssertion,
    ArtifactInventoryEntry,
    ArtifactValidationEvidence,
    ExecutablePlatformPolicy,
)
from topsailai.hooks.artifact_validation import (
    ArtifactValidationError,
    ValidatedSource,
    file_identity,
    revalidate_source,
)


class _LedgerOwner:
    """Expose one real descriptor ledger through the validation protocol."""

    def __init__(self) -> None:
        """Create an empty owner."""
        self.ledger = DescriptorLedger()

    def open_descriptor(self, path, flags, mode=0o777, *, dir_fd=None):
        """Open one descriptor through the ledger."""
        return self.ledger.open(path, flags, mode, dir_fd=dir_fd)

    def close_descriptor(self, descriptor: int) -> None:
        """Close one exact descriptor through the ledger."""
        self.ledger.close(descriptor)


def _sealed_fixture(tmp_path: Path):
    """Create one sealed artifact tree and its expected records."""
    directory = tmp_path / "capture"
    entry_directory = directory / "0000-script-tool"
    directory.mkdir(mode=0o700)
    entry_directory.mkdir(mode=0o700)
    target = entry_directory / "tool"
    target.write_bytes(b"payload")
    target.chmod(0o500)
    entry_directory.chmod(0o500)
    directory.chmod(0o500)
    directory_status = directory.stat()
    entry_status = entry_directory.stat()
    target_status = target.stat()
    evidence = ArtifactValidationEvidence(
        tmp_path,
        target,
        file_identity(target_status),
        None,
        "1" * 64,
        "2" * 64,
        os.getuid(),
        True,
    )
    entry = ArtifactInventoryEntry(
        0,
        "script",
        "tool",
        "0000-script-tool/tool",
        target_status.st_size,
        "3" * 64,
        0o500,
        evidence,
    )
    children = (
        ("0000-script-tool", "directory", entry_status.st_dev, entry_status.st_ino),
        (entry.relative_path, "file", target_status.st_dev, target_status.st_ino),
    )
    return directory, target, entry, children, (directory_status.st_dev, directory_status.st_ino)


@pytest.mark.parametrize(
    "mutation",
    ("capture-mode", "entry-mode", "file-mode", "entry-extra", "expected", "capture-extra"),
)
def test_finalization_rejects_each_metadata_and_inventory_layer(
    tmp_path: Path, mutation: str
) -> None:
    """Reject every independently altered sealed metadata or inventory layer."""
    directory, target, entry, children, identity = _sealed_fixture(tmp_path)
    if mutation == "capture-mode":
        directory.chmod(0o700)
    elif mutation == "entry-mode":
        target.parent.chmod(0o700)
    elif mutation == "file-mode":
        target.chmod(0o400)
    elif mutation == "entry-extra":
        (target.parent / "extra").write_bytes(b"x")
    elif mutation == "expected":
        children = children[:-1]
    else:
        (directory / "extra").mkdir()
    ledger = DescriptorLedger()
    with pytest.raises(ArtifactValidationError, match="artifact_storage_unavailable"):
        validate_sealed_artifact(
            directory, identity, (entry,), children, os.getuid(), ledger, lambda: None
        )
    assert ledger.count == 0


def test_finalization_translates_metadata_observation_failure(monkeypatch, tmp_path: Path) -> None:
    """Translate fail-closed metadata observation into the storage token."""
    directory, _, entry, children, identity = _sealed_fixture(tmp_path)

    def denied(*args, **kwargs):
        raise OSError(errno.EPERM, "secret metadata failure")

    monkeypatch.setattr(os, "getxattr", denied)
    ledger = DescriptorLedger()
    with pytest.raises(ArtifactValidationError, match="artifact_storage_unavailable"):
        validate_sealed_artifact(
            directory, identity, (entry,), children, os.getuid(), ledger, lambda: None
        )
    assert ledger.count == 0


@pytest.mark.parametrize("mismatch", ("root", "capture"))
def test_cleanup_refuses_root_and_capture_identity_replacement(
    tmp_path: Path, mismatch: str
) -> None:
    """Refuse deletion when either pinned directory identity no longer matches."""
    directory, _, _, children, identity = _sealed_fixture(tmp_path)
    root_status = tmp_path.stat()
    root_identity = (
        root_status.st_dev,
        root_status.st_ino,
        root_status.st_uid,
        root_status.st_mode & 0o7777,
    )
    if mismatch == "root":
        root_identity = (0, 0, 0, 0)
    else:
        identity = (0, 0)
    ledger = DescriptorLedger()
    assert not remove_owned_artifact(
        tmp_path, directory, root_identity, identity, children, "debt", ledger
    )
    assert directory.exists() and ledger.count == 0


def test_cleanup_refuses_child_replacement_after_matching_inventory(
    monkeypatch, tmp_path: Path
) -> None:
    """Refuse a child whose identity changes after the inventory observation."""
    import topsailai.hooks.artifact_cleanup as cleanup

    directory, target, _, children, identity = _sealed_fixture(tmp_path)
    root_status = tmp_path.stat()
    root_identity = (
        root_status.st_dev,
        root_status.st_ino,
        root_status.st_uid,
        root_status.st_mode & 0o7777,
    )
    monkeypatch.setattr(cleanup, "_inventory_fd", lambda *args: children)
    real_stat = cleanup.os.stat

    def changed_stat(path, *args, **kwargs):
        status = real_stat(path, *args, **kwargs)
        if path == target.name and kwargs.get("dir_fd") is not None:
            return SimpleNamespace(st_mode=status.st_mode, st_dev=status.st_dev, st_ino=0)
        return status

    monkeypatch.setattr(cleanup.os, "stat", changed_stat)
    ledger = DescriptorLedger()
    assert not remove_owned_artifact(
        tmp_path, directory, root_identity, identity, children, "debt", ledger
    )
    assert target.exists() and ledger.count == 0


def test_cleanup_removal_and_logging_failures_are_fail_safe(monkeypatch, tmp_path: Path) -> None:
    """Retain debt on removal failure but ignore logging failure after deletion."""
    import topsailai.hooks.artifact_cleanup as cleanup

    directory, target, _, children, identity = _sealed_fixture(tmp_path)
    root_status = tmp_path.stat()
    root_identity = (
        root_status.st_dev,
        root_status.st_ino,
        root_status.st_uid,
        root_status.st_mode & 0o7777,
    )
    real_unlink = cleanup.os.unlink
    monkeypatch.setattr(cleanup.os, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fail")))
    assert not remove_owned_artifact(
        tmp_path, directory, root_identity, identity, children, "debt", DescriptorLedger()
    )
    assert target.exists()
    monkeypatch.setattr(cleanup.os, "unlink", real_unlink)
    monkeypatch.setattr(
        builtins, "print", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("log"))
    )
    assert remove_owned_artifact(
        tmp_path, directory, root_identity, identity, children, "debt", DescriptorLedger()
    )
    assert not directory.exists()


def _validated_source(tmp_path: Path) -> tuple[ValidatedSource, _LedgerOwner]:
    """Create a real pinned source suitable for direct revalidation."""
    root = tmp_path / "source"
    root.mkdir(mode=0o700)
    source = root / "tool"
    source.write_bytes(b"payload")
    source.chmod(0o500)
    owner = _LedgerOwner()
    from topsailai.hooks.artifact_validation import _open_directory_chain

    ancestry_descriptors = _open_directory_chain(root, owner)
    source_descriptor = owner.open_descriptor(source, os.O_RDONLY)
    status = os.fstat(source_descriptor)
    identity = file_identity(status)
    request = ArtifactCaptureRequest(
        source, "script", "tool", ExecutablePlatformPolicy("posix")
    )
    assertion = ArtifactClosureAssertion(
        source, "script", "tool", "1" * 64, "2" * 64, "3" * 64
    )
    ancestry_identities = tuple(
        (
            directory_status.st_dev,
            directory_status.st_ino,
            directory_status.st_uid,
            directory_status.st_gid,
            directory_status.st_mode & 0o7777,
        )
        for directory_status in map(os.fstat, ancestry_descriptors)
    )
    evidence = ArtifactValidationEvidence(
        root, source, identity, None, "2" * 64, "3" * 64, os.getuid(), True
    )
    validated = ValidatedSource(
        source_descriptor,
        ancestry_descriptors,
        ancestry_identities,
        owner,
        request,
        assertion,
        identity,
        evidence,
        source.name,
        0o500,
    )
    return validated, owner


@pytest.mark.parametrize("failure", ("cardinality", "identity", "status", "rewalk"))
def test_revalidation_translates_ancestry_metadata_and_rewalk_failures(
    monkeypatch, tmp_path: Path, failure: str
) -> None:
    """Observe exact rewalk/status boundaries for every translated failure."""
    import topsailai.hooks.artifact_validation as validation

    source, owner = _validated_source(tmp_path)
    calls = {"rewalk": 0, "status": 0}
    real_rewalk = validation._open_directory_chain
    real_status = validation._validate_source_status

    def observed_rewalk(*args, **kwargs):
        calls["rewalk"] += 1
        if failure == "rewalk":
            raise OSError("rewalk failed")
        return real_rewalk(*args, **kwargs)

    def observed_status(*args, **kwargs):
        calls["status"] += 1
        if failure == "status":
            raise ArtifactValidationError("trust_rejected")
        return real_status(*args, **kwargs)

    monkeypatch.setattr(validation, "_open_directory_chain", observed_rewalk)
    monkeypatch.setattr(validation, "_validate_source_status", observed_status)
    if failure == "cardinality":
        source = SimpleNamespace(**{
            field: getattr(source, field)
            for field in source.__dataclass_fields__
        })
        source.ancestry_identities = ()
    elif failure == "identity":
        source = SimpleNamespace(**{
            field: getattr(source, field)
            for field in source.__dataclass_fields__
        })
        source.ancestry_identities = (
            (0, 0, 0, 0, 0), *source.ancestry_identities[1:]
        )
        assert len(source.ancestry_descriptors) == len(source.ancestry_identities)
    with pytest.raises(ArtifactValidationError, match="artifact_source_changed"):
        revalidate_source(source)
    assert calls == {
        "rewalk": 0 if failure in ("cardinality", "identity") else 1,
        "status": 1 if failure == "status" else 0,
    }
    owner.ledger.close_all()
    assert owner.ledger.count == 0


def test_public_owner_and_handle_rejection_edges(tmp_path: Path) -> None:
    """Cover opaque serialization, closed owner, and foreign handle rejection."""
    import pickle

    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    source_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    trust = ArtifactCaptureTrust((source_root,), ())
    owner = ArtifactCaptureOwner(artifact_root=str(artifact_root), trust=trust)
    result = owner.capture(())
    assert result.artifact is not None
    with pytest.raises(TypeError, match="not serializable"):
        pickle.dumps(result.artifact)
    other = ArtifactCaptureOwner(artifact_root=str(artifact_root), trust=trust)
    assert other.dispose(result.artifact).errors == ("invalid_artifact",)
    assert owner.close().accepted
    assert owner.capture(()).errors == ("artifact_owner_closed",)
    other.close()
    with pytest.raises(ValueError, match="invalid artifact capture owner"):
        ArtifactCaptureOwner(artifact_root="relative", trust=trust)
