"""Offline deployment manifest generation only; never called by Runtime. Author: DawsonLin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from topsailai.hooks.artifact_contracts import ArtifactClosureAssertion, ArtifactPythonRuntimeAuthority
from topsailai.hooks.artifact_identity import python_runtime_fingerprint
from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy
from topsailai.hooks.module_discovery import enumerate_module_candidates_owned

_MAX_FILE_BYTES = 16_777_216
_MAX_MANIFEST_BYTES = 1_048_576


def _read_stable(path: Path) -> tuple[bytes, os.stat_result]:
    """Read bounded regular bytes with exact descriptor and named-path identity checks."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_FILE_BYTES:
        raise ValueError("invalid deployment source")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        content = stream.read(_MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    named = path.lstat()
    identities = {(item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
        item.st_ctime_ns, item.st_mode, item.st_uid, item.st_gid, item.st_nlink)
        for item in (before, opened, after, named)}
    if len(identities) != 1 or len(content) > _MAX_FILE_BYTES:
        raise ValueError("deployment source changed during generation")
    return content, after


def generate_module_trust_manifest(
    *, module_folders: tuple[Path, ...], source_roots: tuple[Path, ...],
    reviewed_deployment_sha256: str, python_runtime: ArtifactPythonRuntimeAuthority,
) -> tuple[bytes, str]:
    """Generate existing v1 authority offline from deployer-reviewed closure inputs.

    Run on the frozen deployment tree under the target CPython runtime. The digest
    supplied by the deployer attests review; this function does not review imports
    or prove dependency closure. Directory configuration contains no member list.
    Scripts are not generated or authorized by this Module-only entry point.
    """
    if type(reviewed_deployment_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", reviewed_deployment_sha256):
        raise ValueError("reviewed deployment digest required")
    if type(python_runtime) is not ArtifactPythonRuntimeAuthority:
        raise ValueError("explicit Python Runtime authority required")
    trust = ConfiguredTrustPolicy(source_roots, python_runtime=python_runtime)
    if type(module_folders) is not tuple or not module_folders or len(module_folders) > 1024:
        raise ValueError("invalid configured Module directories")
    if any(not isinstance(folder, Path) or not folder.is_absolute() for folder in module_folders):
        raise ValueError("absolute configured Module directories required")
    if len(set(module_folders)) != len(module_folders):
        raise ValueError("duplicate configured Module directory")
    if any(root.resolve(strict=True) != root or not root.is_dir() for root in source_roots):
        raise ValueError("canonical deployment source roots required")
    executable = python_runtime.executable
    if executable != Path(sys.executable).resolve(strict=True):
        raise ValueError("generator must run under the authorized target Python runtime")
    runtime_bytes, runtime_stat = _read_stable(executable)
    if hashlib.sha256(runtime_bytes).hexdigest() != python_runtime.content_sha256:
        raise ValueError("Python Runtime authority digest mismatch")
    fingerprint = python_runtime_fingerprint(executable, python_runtime.content_sha256,
        device=runtime_stat.st_dev, inode=runtime_stat.st_ino)
    assertions = {}
    for folder in module_folders:
        if folder.is_symlink() or folder.resolve(strict=True) != folder:
            raise ValueError("noncanonical configured Module directory")
        if not any(folder.is_relative_to(root) for root in trust.source_roots):
            raise ValueError("configured Module directory outside source roots")
        inventory = enumerate_module_candidates_owned(folder)
        if not inventory.accepted:
            raise ValueError("configured Module discovery rejected")
        for candidate in inventory.candidates:
            content, _ = _read_stable(candidate.source_path)
            assertions[str(candidate.source_path)] = {
                "source_path": str(candidate.source_path), "kind": candidate.kind,
                "logical_name": candidate.logical_name,
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "runtime_sha256": fingerprint,
                "deployment_sha256": reviewed_deployment_sha256,
                "closure": "single-file-trusted-runtime-v1",
            }
            if len(assertions) > 4096:
                raise ValueError("deployment assertion limit exceeded")
    ConfiguredTrustPolicy(source_roots, python_runtime=python_runtime, closure_assertions=tuple(
        ArtifactClosureAssertion(source_path=Path(item["source_path"]), **{
            key: value for key, value in item.items() if key != "source_path"})
        for item in assertions.values()))
    document = {
        "schema_version": 1, "source_roots": [str(root) for root in trust.source_roots],
        "allowed_interpreters": [], "allow_native_scripts": False,
        "closure_assertions": [assertions[key] for key in sorted(assertions)],
        "python_runtime": {"executable": str(executable),
            "content_sha256": python_runtime.content_sha256, "bootstrap": python_runtime.bootstrap},
    }
    manifest = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(manifest) > _MAX_MANIFEST_BYTES:
        raise ValueError("deployment manifest size limit exceeded")
    return manifest, hashlib.sha256(manifest).hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Write a new offline manifest and print its pin; never overwrite deployed authority."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-folder", action="append", required=True, type=Path)
    parser.add_argument("--source-root", action="append", required=True, type=Path)
    parser.add_argument("--reviewed-deployment-sha256", required=True)
    parser.add_argument("--python-executable", required=True, type=Path)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if not args.output.is_absolute():
            raise ValueError("absolute manifest output required")
        manifest, digest = generate_module_trust_manifest(
            module_folders=tuple(args.module_folder), source_roots=tuple(args.source_root),
            reviewed_deployment_sha256=args.reviewed_deployment_sha256,
            python_runtime=ArtifactPythonRuntimeAuthority(args.python_executable, args.python_sha256))
        with args.output.open("xb") as stream:
            stream.write(manifest)
        print(digest)
        return 0
    except (OSError, ValueError) as error:
        print(f"deployment authorization failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
