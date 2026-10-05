"""Boundary assertions for U07 artifact capacity tests."""

from __future__ import annotations

import hashlib
import os
import platform
import struct
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


def _native_bytes(payload: bytes) -> bytes:
    """Return minimal native bytes carrying one bounded payload."""
    machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
    return (
        b"\x7fELF" + bytes([2 if struct.calcsize("P") == 8 else 1])
        + b"\x00" * 13 + machine.to_bytes(2, "little") + payload
    )


def _fixture(tmp_path: Path, sizes: tuple[int, ...]):
    """Create one exact multi-entry owner for boundary assertions."""
    source_root, artifact_root = tmp_path / "source", tmp_path / "artifacts"
    source_root.mkdir(parents=True, mode=0o700)
    artifact_root.mkdir(mode=0o700)
    policy = ExecutablePlatformPolicy("posix")
    requests, assertions, contents = [], [], []
    for index, size in enumerate(sizes):
        content = _native_bytes(bytes([65 + index]) * size)
        source = source_root / f"native-{index}"
        source.write_bytes(content)
        source.chmod(0o500)
        requests.append(ArtifactCaptureRequest(source, "script", source.name, policy))
        assertions.append(ArtifactClosureAssertion(
            source, "script", source.name, hashlib.sha256(content).hexdigest(),
            native_runtime_fingerprint(), f"{index + 1:x}" * 64,
        ))
        contents.append(content)
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifact_root),
        trust=ArtifactCaptureTrust((source_root,), (), True, tuple(assertions)),
    )
    return owner, tuple(requests), tuple(contents)


def _dispose(owner, result) -> None:
    """Dispose an accepted boundary artifact."""
    assert result.accepted and result.artifact is not None
    assert owner.dispose(result.artifact).accepted


def assert_byte_and_owner_capacity_boundaries(monkeypatch, tmp_path: Path) -> None:
    """Prove independent adjacent request, byte, and owner limits."""
    owner, requests, contents = _fixture(tmp_path / "limits", (3, 5, 7))
    largest = max(map(len, contents[:2]))
    total = sum(map(len, contents[:2]))
    for count, accepted in ((1, True), (2, True), (3, False)):
        result = owner.capture(
            requests[:count],
            policy=ArtifactCapturePolicy(
                max_entries=2, max_file_bytes=max(map(len, contents)),
                max_total_bytes=sum(map(len, contents)),
            ),
        )
        assert result.accepted is accepted
        if accepted:
            _dispose(owner, result)
        else:
            assert result.errors == ("artifact_inventory_limit",)
    for limit, accepted in ((largest - 1, False), (largest, True), (largest + 1, True)):
        result = owner.capture(
            requests[:2],
            policy=ArtifactCapturePolicy(
                max_entries=2, max_file_bytes=limit, max_total_bytes=total + 1,
            ),
        )
        assert result.accepted is accepted
        if accepted:
            _dispose(owner, result)
        else:
            assert result.errors == ("artifact_byte_limit",)
    for limit, accepted in ((total - 1, False), (total, True), (total + 1, True)):
        result = owner.capture(
            requests[:2],
            policy=ArtifactCapturePolicy(
                max_entries=2, max_file_bytes=largest + 1, max_total_bytes=limit,
            ),
        )
        assert result.accepted is accepted
        if accepted:
            _dispose(owner, result)
        else:
            assert result.errors == ("artifact_byte_limit",)
    owner.close()

    import topsailai.hooks.artifact_store as store

    monkeypatch.setattr(store, "_MAX_OWNER_ENTRIES", 1)
    monkeypatch.setattr(store, "_MAX_OWNER_BYTES", 1_000)
    owner, requests, _ = _fixture(tmp_path / "owner-entry", (1,))
    live = owner.capture(
        requests, policy=ArtifactCapturePolicy(
            max_entries=1, max_file_bytes=60, max_total_bytes=60,
        ),
    )
    assert live.accepted and live.artifact is not None
    opened = 0
    real_open = os.open

    def observed_open(*args, **kwargs):
        nonlocal opened
        opened += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(store.os, "open", observed_open)
    policy = ArtifactCapturePolicy(
        max_entries=1, max_file_bytes=50, max_total_bytes=50,
    )
    rejected = owner.capture(requests, policy=policy)
    assert rejected.errors == ("artifact_capacity_exceeded",) and opened == 0
    assert owner.dispose(live.artifact).accepted
    recovered = owner.capture(requests, policy=policy)
    assert recovered.accepted and opened > 0
    _dispose(owner, recovered)
    owner.close()

    import topsailai.hooks.artifact_cleanup as cleanup

    owner, requests, _ = _fixture(tmp_path / "owner-debt", (1,))
    live = owner.capture(requests, policy=policy)
    assert live.accepted and live.artifact is not None
    real_unlink = cleanup.os.unlink
    monkeypatch.setattr(
        cleanup.os, "unlink",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("retain debt")),
    )
    pending = owner.dispose(live.artifact)
    assert pending.cleanup_pending and len(owner.cleanup_debts()) == 1
    opened = 0
    rejected = owner.capture(requests, policy=policy)
    assert rejected.errors == ("artifact_capacity_exceeded",) and opened == 0
    monkeypatch.setattr(cleanup.os, "unlink", real_unlink)
    assert owner.retry_cleanup(owner.cleanup_debts()[0].debt_id)
    recovered = owner.capture(requests, policy=policy)
    assert recovered.accepted and opened > 0
    _dispose(owner, recovered)
    owner.close()

    monkeypatch.setattr(store, "_MAX_OWNER_ENTRIES", 2)
    owner, requests, _ = _fixture(tmp_path / "owner-byte", (1,))
    live = owner.capture(requests, policy=policy)
    assert live.accepted and live.artifact is not None
    monkeypatch.setattr(
        store, "_MAX_OWNER_BYTES", live.artifact.total_bytes + policy.max_total_bytes - 1,
    )
    opened = 0
    rejected = owner.capture(requests, policy=policy)
    assert rejected.errors == ("artifact_capacity_exceeded",) and opened == 0
    assert owner.dispose(live.artifact).accepted
    recovered = owner.capture(requests, policy=policy)
    assert recovered.accepted and opened > 0
    _dispose(owner, recovered)
    owner.close()
