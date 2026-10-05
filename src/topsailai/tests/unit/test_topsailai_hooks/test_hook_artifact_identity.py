"""Focused U07 canonical artifact identity tests."""

from __future__ import annotations

import hashlib
import platform
import struct

from topsailai.hooks.artifact_identity import (
    artifact_identity,
    frame_bytes,
    frame_text,
    frame_u64,
    native_runtime_fingerprint,
)


def _b(value: bytes) -> bytes:
    """Independently length-frame bytes for fixed contract vectors."""
    return len(value).to_bytes(8, "big") + value


def test_artifact_identity_empty_golden_vector() -> None:
    """Bind the empty identity to its domain and explicit zero cardinality."""
    expected = hashlib.sha256(
        _b(b"topsailai-hook-artifact-v1") + (0).to_bytes(8, "big")
    ).hexdigest()
    assert artifact_identity((), (), False) == expected


def test_identity_framing_uses_lengths_and_network_u64() -> None:
    """Distinguish adjacent fields through explicit lengths and cardinality words."""
    assert frame_u64(1) == b"\x00" * 7 + b"\x01"
    assert frame_bytes(b"ab") + frame_bytes(b"c") != frame_bytes(b"a") + frame_bytes(b"bc")
    assert frame_text("é") == _b("é".encode("utf-8"))


def test_native_runtime_fingerprint_golden_vector() -> None:
    """Bind native runtime identity to domain, architecture, and pointer width."""
    body = b"".join(
        (
            _b(b"topsailai-hook-runtime-v1"),
            _b(b"native-linux"),
            _b(platform.machine().encode("utf-8")),
            (struct.calcsize("P") * 8).to_bytes(8, "big"),
        )
    )
    assert native_runtime_fingerprint() == hashlib.sha256(body).hexdigest()


def _entry(index: int, *, content: str, deployment: str, logical_name: str):
    """Build immutable identity evidence without using production framing helpers."""
    from pathlib import Path
    from topsailai.hooks import (
        ArtifactFileIdentity,
        ArtifactInventoryEntry,
        ArtifactValidationEvidence,
    )

    source_root = Path("/trusted/source")
    source_path = source_root / f"{logical_name}.py"
    evidence = ArtifactValidationEvidence(
        source_root,
        source_path,
        ArtifactFileIdentity(7, 11 + index, 3, 13, 17, 0o400, 1000, 1000, 1),
        None,
        "2" * 64,
        deployment,
        1000,
        True,
    )
    return ArtifactInventoryEntry(
        index,
        "python_source",
        logical_name,
        f"entry-{index:06d}/{logical_name}.py",
        3,
        content,
        0o400,
        evidence,
    )


def _independent_entry_frame(entry, policy_frame: bytes = b"\x00") -> bytes:
    """Frame one entry without production identity helpers."""
    evidence = entry.validation
    return b"".join((
        _b(b"entry-v1"), entry.index.to_bytes(8, "big"), _b(entry.kind.encode()),
        _b(entry.logical_name.encode()), _b(entry.relative_path.encode()),
        entry.size_bytes.to_bytes(8, "big"), bytes.fromhex(entry.content_sha256),
        entry.mode.to_bytes(8, "big"), _b(str(evidence.source_root).encode()),
        _b(evidence.source_path.relative_to(evidence.source_root).as_posix().encode()),
        bytes.fromhex(evidence.runtime_sha256), bytes.fromhex(evidence.deployment_sha256),
        _b(b"single-file-trusted-runtime-v1"), policy_frame,
    ))


def _independent_identity(entries, policy_frames=None) -> str:
    """Compute the artifact contract independently for golden vectors."""
    frames = policy_frames or (b"\x00",) * len(entries)
    body = _b(b"topsailai-hook-artifact-v1") + len(entries).to_bytes(8, "big")
    body += b"".join(_independent_entry_frame(entry, policy) for entry, policy in zip(
        entries, frames, strict=True
    ))
    return hashlib.sha256(body).hexdigest()


def test_artifact_identity_one_and_two_entry_golden_vectors() -> None:
    """Bind field order, ordering, and a direct collection-count word."""
    first = _entry(0, content="1" * 64, deployment="3" * 64, logical_name="alpha")
    second = _entry(1, content="4" * 64, deployment="5" * 64, logical_name="beta")
    assert artifact_identity((first,), (None,), False) == _independent_identity((first,))
    assert artifact_identity((first, second), (None, None), False) == _independent_identity(
        (first, second)
    )
    assert artifact_identity((first, second), (None, None), False) != artifact_identity(
        (second, first), (None, None), False
    )
    missing_count = hashlib.sha256(
        _b(b"topsailai-hook-artifact-v1") + _independent_entry_frame(first)
    ).hexdigest()
    assert artifact_identity((first,), (None,), False) != missing_count


def test_script_policy_and_collection_boundary_golden_vectors() -> None:
    """Bind valid absent, empty, sorted, and counted policy collections."""
    from dataclasses import replace
    from topsailai.hooks import ExecutablePlatformPolicy

    module = _entry(0, content="1" * 64, deployment="3" * 64, logical_name="hook")
    assert artifact_identity((module,), (None,), False) == _independent_identity((module,))
    script = replace(
        module,
        kind="script",
        relative_path="entry-000000/hook",
        mode=0o500,
        validation=replace(
            module.validation,
            source_path=module.validation.source_root / "hook",
            identity=replace(module.validation.identity, mode=0o500),
        ),
    )
    empty_policy = ExecutablePlatformPolicy("posix")
    empty_frame = b"\x01" + _b(b"posix") + (0).to_bytes(8, "big") + b"\x01"
    assert artifact_identity((script,), (empty_policy,), True) == _independent_identity(
        (script,), (empty_frame,)
    )
    declaration = ("/usr/bin/zsh", "/bin/sh")
    canonical = tuple(sorted(declaration))
    policy_frame = b"\x01" + _b(b"posix") + (2).to_bytes(8, "big")
    policy_frame += b"".join(_b(value.encode()) for value in canonical) + b"\x00"
    policy = ExecutablePlatformPolicy("posix", declaration)
    expected = _independent_identity((script,), (policy_frame,))
    assert artifact_identity((script,), (policy,), False) == expected
    missing_interpreter_count = b"\x01" + _b(b"posix")
    missing_interpreter_count += b"".join(_b(value.encode()) for value in canonical) + b"\x00"
    assert expected != _independent_identity((script,), (missing_interpreter_count,))
    reordered = ExecutablePlatformPolicy("posix", tuple(reversed(declaration)))
    assert artifact_identity((script,), (reordered,), False) == expected



def test_identity_separates_content_provenance_runtime_deployment_and_policy() -> None:
    """Keep content, source evidence, runtime, deployment, and policy identities distinct."""
    from dataclasses import replace
    from topsailai.hooks import ExecutablePlatformPolicy

    first = _entry(0, content="1" * 64, deployment="3" * 64, logical_name="alpha")
    baseline = artifact_identity((first,), (None,), False)
    changed_content = replace(first, content_sha256="6" * 64)
    changed_runtime = replace(
        first, validation=replace(first.validation, runtime_sha256="7" * 64)
    )
    changed_deployment = replace(
        first, validation=replace(first.validation, deployment_sha256="8" * 64)
    )
    changed_provenance = replace(
        first,
        validation=replace(
            first.validation,
            source_path=first.validation.source_root / "renamed.py",
            identity=replace(first.validation.identity, inode=999),
        ),
    )
    assert baseline != artifact_identity((changed_content,), (None,), False)
    assert baseline != artifact_identity((changed_runtime,), (None,), False)
    assert baseline != artifact_identity((changed_deployment,), (None,), False)
    assert baseline != artifact_identity((changed_provenance,), (None,), False)
    changed_evidence_only = replace(
        first, validation=replace(first.validation, identity=replace(first.validation.identity, inode=999))
    )
    assert baseline == artifact_identity((changed_evidence_only,), (None,), False)
    script_policy = ExecutablePlatformPolicy("posix", ("/bin/z", "/bin/a"))
    assert baseline != artifact_identity((first,), (script_policy,), False)
    assert artifact_identity((first,), (script_policy,), False) != artifact_identity(
        (first,), (script_policy,), True
    )
