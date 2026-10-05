"""Immutable public contracts for framework-owned artifact capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy

if TYPE_CHECKING:
    from topsailai.hooks.artifact_store import ArtifactCaptureOwner, CapturedArtifact


@dataclass(frozen=True, slots=True)
class ArtifactPythonRuntimeAuthority:
    """Attest the exact ordinary CPython executable used by the host."""

    executable: Path = field(repr=False)
    content_sha256: str = field(repr=False)
    bootstrap: str = "cpython-executable-v1"


@dataclass(frozen=True, slots=True)
class ArtifactClosureAssertion:
    """Attest one exact source and its trusted deployment closure."""

    source_path: Path = field(repr=False)
    kind: str
    logical_name: str
    content_sha256: str = field(repr=False)
    runtime_sha256: str = field(repr=False)
    deployment_sha256: str = field(repr=False)
    closure: str = "single-file-trusted-runtime-v1"


@dataclass(frozen=True, slots=True)
class ArtifactCaptureTrust:
    """Hold host-only source, interpreter, and closure authority."""

    source_roots: tuple[Path, ...] = field(repr=False)
    allowed_interpreters: tuple[Path, ...] = field(default=(), repr=False)
    allow_native_scripts: bool = False
    closure_assertions: tuple[ArtifactClosureAssertion, ...] = field(default=(), repr=False)
    python_runtime: ArtifactPythonRuntimeAuthority | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ArtifactCaptureRequest:
    """Request capture of one exact source under host authority."""

    source_path: Path = field(repr=False)
    kind: str
    logical_name: str
    script_policy: ExecutablePlatformPolicy | None = None


@dataclass(frozen=True, slots=True)
class ArtifactCapturePolicy:
    """Bound one complete cooperative capture operation."""

    timeout_ms: int = 10_000
    max_entries: int = 128
    max_file_bytes: int = 16_777_216
    max_total_bytes: int = 67_108_864


@dataclass(frozen=True, slots=True)
class ArtifactFileIdentity:
    """Record stable filesystem facts used only as validation evidence."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    uid: int
    gid: int
    links: int


@dataclass(frozen=True, slots=True)
class ArtifactInterpreterEvidence:
    """Record one validated interpreter without granting launch authority."""

    path: Path = field(repr=False)
    identity: ArtifactFileIdentity
    content_sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ArtifactValidationEvidence:
    """Record immutable source-admission evidence."""

    source_root: Path = field(repr=False)
    source_path: Path = field(repr=False)
    identity: ArtifactFileIdentity
    interpreter: ArtifactInterpreterEvidence | None
    runtime_sha256: str = field(repr=False)
    deployment_sha256: str = field(repr=False)
    checked_uid: int
    acl_capability_absent: bool


@dataclass(frozen=True, slots=True)
class ArtifactInventoryEntry:
    """Describe one sealed file in request order."""

    index: int
    kind: str
    logical_name: str
    relative_path: str
    size_bytes: int
    content_sha256: str
    mode: int
    validation: ArtifactValidationEvidence


@dataclass(frozen=True, slots=True)
class ArtifactCaptureResult:
    """Return an atomically accepted artifact or one stable rejection."""

    accepted: bool
    artifact: CapturedArtifact | None = None
    errors: tuple[str, ...] = ()
    recovery_owner: ArtifactCaptureOwner | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ArtifactDisposeResult:
    """Report logical disposal and physical cleanup state."""

    accepted: bool
    already_disposed: bool = False
    cleanup_pending: bool = False
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactCleanupDebt:
    """Expose one opaque bounded cleanup obligation."""

    debt_id: str
    category: str
