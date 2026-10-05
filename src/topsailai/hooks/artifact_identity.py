"""Pure framed identities for immutable hook artifacts and runtimes."""

from __future__ import annotations

import hashlib
import platform
import struct
import sys
import sysconfig
from pathlib import Path

from topsailai.hooks.artifact_contracts import ArtifactInventoryEntry
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy

_U64 = struct.Struct("!Q")


def frame_u64(value: int) -> bytes:
    """Frame one unsigned integer in eight-byte network order."""
    return _U64.pack(value)


def frame_bytes(value: bytes) -> bytes:
    """Frame bytes with an explicit length."""
    return frame_u64(len(value)) + value


def frame_text(value: str) -> bytes:
    """Frame strict UTF-8 text without normalization."""
    return frame_bytes(value.encode("utf-8", errors="strict"))


def digest_hex(value: bytes) -> str:
    """Return one lowercase SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


def python_runtime_fingerprint(
    executable: Path,
    executable_digest: str,
    *,
    device: int,
    inode: int,
) -> str:
    """Frame the validated ordinary CPython runtime facts."""
    info = sys.version_info
    body = b"".join(
        (
            frame_bytes(b"topsailai-hook-runtime-v1"),
            frame_bytes(b"python"),
            frame_text(str(executable)),
            bytes.fromhex(executable_digest),
            frame_u64(device),
            frame_u64(inode),
            frame_text(sys.implementation.name),
            frame_text(sys.implementation.cache_tag or ""),
            frame_text(sysconfig.get_config_var("SOABI") or ""),
            frame_u64(info.major),
            frame_u64(info.minor),
            frame_u64(info.micro),
            frame_text(info.releaselevel),
            frame_u64(info.serial),
            frame_text(sys.platform),
            frame_text(platform.machine()),
            frame_u64(struct.calcsize("P") * 8),
        )
    )
    return digest_hex(body)


def shebang_runtime_fingerprint(
    interpreter: Path,
    content_digest: str,
    *,
    device: int,
    inode: int,
) -> str:
    """Frame one exact admitted shebang interpreter."""
    body = b"".join(
        (
            frame_bytes(b"topsailai-hook-runtime-v1"),
            frame_bytes(b"shebang"),
            frame_text(str(interpreter)),
            bytes.fromhex(content_digest),
            frame_u64(device),
            frame_u64(inode),
        )
    )
    return digest_hex(body)


def native_runtime_fingerprint() -> str:
    """Frame the supported Linux native-script process architecture."""
    body = b"".join(
        (
            frame_bytes(b"topsailai-hook-runtime-v1"),
            frame_bytes(b"native-linux"),
            frame_text(platform.machine()),
            frame_u64(struct.calcsize("P") * 8),
        )
    )
    return digest_hex(body)


def artifact_identity(
    entries: tuple[ArtifactInventoryEntry, ...],
    policies: tuple[ExecutablePlatformPolicy | None, ...],
    host_allow_native_scripts: bool,
) -> str:
    """Hash the exact ordered structural artifact manifest."""
    pieces = [frame_bytes(b"topsailai-hook-artifact-v1"), frame_u64(len(entries))]
    for entry, policy in zip(entries, policies, strict=True):
        evidence = entry.validation
        source_relative = evidence.source_path.relative_to(evidence.source_root).as_posix()
        pieces.extend(
            (
                frame_bytes(b"entry-v1"),
                frame_u64(entry.index),
                frame_text(entry.kind),
                frame_text(entry.logical_name),
                frame_text(entry.relative_path),
                frame_u64(entry.size_bytes),
                bytes.fromhex(entry.content_sha256),
                frame_u64(entry.mode),
                frame_text(str(evidence.source_root)),
                frame_text(source_relative),
                bytes.fromhex(evidence.runtime_sha256),
                bytes.fromhex(evidence.deployment_sha256),
                frame_text("single-file-trusted-runtime-v1"),
                _policy_frame(policy, host_allow_native_scripts),
            )
        )
    return digest_hex(b"".join(pieces))


def _policy_frame(
    policy: ExecutablePlatformPolicy | None,
    host_allow_native_scripts: bool,
) -> bytes:
    """Frame an absent module policy or exact script policy."""
    if policy is None:
        return b"\x00"
    interpreters = tuple(sorted(policy.allowed_interpreters))
    parts = [b"\x01", frame_text("posix"), frame_u64(len(interpreters))]
    parts.extend(frame_text(value) for value in interpreters)
    parts.append(b"\x01" if host_allow_native_scripts else b"\x00")
    return b"".join(parts)
