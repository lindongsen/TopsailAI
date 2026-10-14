"""Offline mixed deployment authority; never invoked by Runtime. Author: DawsonLin."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from topsailai.hooks import artifact_validation as validation
from topsailai.hooks.artifact_cleanup import DescriptorLedger
from topsailai.hooks.artifact_contracts import ArtifactCaptureRequest, ArtifactClosureAssertion, ArtifactPythonRuntimeAuthority
from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint
from topsailai.hooks.configured_contracts import ConfiguredPreparationPolicy, ConfiguredScript, ConfiguredTrustPolicy
from topsailai.hooks.configured_script_sources import discover_prepared_script_entries
from topsailai.hooks.module_discovery import enumerate_module_candidates_owned
from topsailai.hooks.module_discovery_policy import DiscoveryBudget, ModuleDiscoveryPolicy

_MAX_FILE_BYTES = 16_777_216
_MAX_MANIFEST_BYTES = 1_048_576
logger = logging.getLogger(__name__)


class _Budget:
    """Share one deadline and aggregate limits across the complete inventory."""

    def __init__(self, policy, cancellation):
        """Establish the deadline once before any filesystem observation."""
        self.policy = policy
        self.discovery = DiscoveryBudget(policy.timeout_ms, cancellation, time.monotonic)
        self.scanned = self.candidates = self.source_bytes = self.read_bytes = 0

    def checkpoint(self):
        """Reject cancellation or expiry before further business I/O."""
        if self.discovery.rejection() is not None:
            raise ValueError("deployment generation stopped")

    def _add(self, field, count, limit):
        """Apply an aggregate bound without resetting between directories."""
        self.checkpoint()
        value = getattr(self, field) + count
        if value > limit:
            raise ValueError("deployment capacity exceeded")
        setattr(self, field, value)

    def add_scan(self):
        """Account every visited directory entry."""
        self._add("scanned", 1, self.policy.max_scanned_entries)

    def add_candidate(self, count=1):
        """Account selected sources across Module and Script discovery."""
        self._add("candidates", count, self.policy.max_candidates)

    def add_source_bytes(self, count):
        """Bound Script metadata sizes during shared discovery."""
        self._add("source_bytes", count, self.policy.max_artifact_bytes)

    def add_read(self, count):
        """Include source and interpreter reads in the aggregate byte budget."""
        self._add("read_bytes", count, self.policy.max_artifact_bytes)


def _io(budget, call, *args, **kwargs):
    """Check the unchanged deadline on both sides of a fallible observation."""
    budget.checkpoint()
    try:
        result = call(*args, **kwargs)
    except Exception:
        budget.checkpoint()
        raise
    budget.checkpoint()
    return result


@contextmanager
def _ledger():
    """Retain uncertain cleanup authority without replaying physical close."""
    owner = DescriptorLedger()
    try:
        yield owner
    except BaseException as primary:
        try:
            errors = owner.close_all()
            if errors or owner.count:
                primary.add_note("deployment descriptor cleanup pending")
        except BaseException:
            primary.add_note("deployment descriptor cleanup interrupted")
        if owner.count:
            primary.deployment_descriptor_owner = owner
        raise
    else:
        try:
            errors = owner.close_all()
        except BaseException as primary:
            if owner.count:
                primary.deployment_descriptor_owner = owner
                primary.add_note("deployment descriptor cleanup interrupted")
            raise
        if errors or owner.count:
            error = ValueError("deployment descriptor cleanup pending")
            error.deployment_descriptor_owner = owner
            raise error


def _canonical(path, budget):
    """Reject noncanonical paths and symlink ancestry without granting authority."""
    for ancestor in reversed((path, *path.parents)):
        if stat.S_ISLNK(_io(budget, ancestor.lstat).st_mode):
            raise ValueError("noncanonical deployment path")
    if _io(budget, path.resolve, strict=True) != path:
        raise ValueError("noncanonical deployment path")


def _read_source(path, budget, *, executable):
    """Stable-read bounded bytes through pinned safe ancestry and named revalidation."""
    _canonical(path, budget)
    with _ledger() as owner:
        ancestry, identities, descriptor = validation._open_absolute_file(
            path, os.geteuid(), budget.checkpoint, owner)
        before = _io(budget, os.fstat, descriptor)
        request = ArtifactCaptureRequest(path, "script" if executable else "python_source", path.name)
        validation._validate_source_status(request, before, os.geteuid())
        validation._require_fd_metadata_absent(descriptor, directory=False, checkpoint=budget.checkpoint)
        if before.st_size > _MAX_FILE_BYTES:
            raise ValueError("deployment source byte limit exceeded")
        chunks, size = [], 0
        while True:
            chunk = _io(budget, os.read, descriptor, min(65536, _MAX_FILE_BYTES - size + 1))
            if not chunk:
                break
            size += len(chunk)
            budget.add_read(len(chunk))
            if size > _MAX_FILE_BYTES:
                raise ValueError("deployment source byte limit exceeded")
            chunks.append(chunk)
        after = _io(budget, os.fstat, descriptor)
        rewalk, current_ancestry, _ = validation._open_absolute_file(
            path, os.geteuid(), budget.checkpoint, owner)
        named = _io(budget, os.stat, path.name, dir_fd=rewalk[-1], follow_symlinks=False)
        if (validation.file_identity(before) != validation.file_identity(after)
                or validation.file_identity(before) != validation.file_identity(named)
                or identities != current_ancestry or size != before.st_size
                or validation._validated_ancestry(ancestry, os.geteuid(), budget.checkpoint) != identities):
            raise ValueError("deployment source changed during generation")
        validation._validate_source_status(request, after, os.geteuid())
        validation._require_fd_metadata_absent(descriptor, directory=False, checkpoint=budget.checkpoint)
        return b"".join(chunks), after


def _digest(value):
    """Validate an explicit reviewed lowercase SHA-256 digest."""
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _inputs(module_folders, scripts, source_roots, reviewed_digest, python_runtime,
            interpreter_digests, policy, cancellation):
    """Validate all container shapes before dependent operations or filesystem I/O."""
    if not _digest(reviewed_digest) or type(policy) is not ConfiguredPreparationPolicy:
        raise ValueError("invalid deployment review or policy")
    if cancellation is not None and not isinstance(cancellation, threading.Event):
        raise ValueError("invalid deployment cancellation")
    if type(module_folders) is not tuple or len(module_folders) > policy.max_hook_points:
        raise ValueError("invalid Module folders")
    if any(not isinstance(path, Path) or not path.is_absolute() for path in module_folders):
        raise ValueError("absolute Module folders required")
    if len(set(module_folders)) != len(module_folders):
        raise ValueError("duplicate Module folder")
    if type(scripts) is not tuple or len(scripts) > policy.max_hook_points:
        raise ValueError("invalid Script sources")
    if any(type(item) is not ConfiguredScript for item in scripts):
        raise ValueError("invalid Script source")
    if module_folders and type(python_runtime) is not ArtifactPythonRuntimeAuthority:
        raise ValueError("explicit Python authority required")
    if type(interpreter_digests) is not tuple or len(interpreter_digests) > 32:
        raise ValueError("invalid interpreter authority")
    for pair in interpreter_digests:
        if (type(pair) is not tuple or len(pair) != 2 or not isinstance(pair[0], Path)
                or not pair[0].is_absolute() or not _digest(pair[1])):
            raise ValueError("invalid interpreter authority")
    if len({path for path, _ in interpreter_digests}) != len(interpreter_digests):
        raise ValueError("duplicate interpreter authority")
    allowed = set()
    for item in scripts:
        value = item.platform_policy
        paths = tuple(Path(raw) for raw in value.allowed_interpreters)
        if (value.platform != "posix" or value.native_suffixes or len(set(paths)) != len(paths)
                or any(str(path) != raw or not path.is_absolute()
                       for path, raw in zip(paths, value.allowed_interpreters, strict=True))):
            raise ValueError("unsupported Script policy")
        allowed.update(paths)
    if allowed != {path for path, _ in interpreter_digests}:
        raise ValueError("interpreter authority must match selected policies")
    return ConfiguredTrustPolicy(source_roots, tuple(sorted(allowed)), python_runtime=python_runtime)


def _interpreter_fingerprints(pairs, budget):
    """Verify reviewed interpreter bytes using the same capture security contract."""
    result = {}
    for path, digest in pairs:
        _canonical(path, budget)
        budget.add_read(_io(budget, path.lstat).st_size * 2)
        with _ledger() as owner:
            evidence = validation._validate_script_interpreter(path, os.geteuid(), budget.checkpoint, owner)
        if evidence.content_sha256 != digest:
            raise ValueError("interpreter review digest mismatch")
        result[path] = shebang_runtime_fingerprint(path, digest,
            device=evidence.identity.device, inode=evidence.identity.inode)
    return result


def _shebang(content, policy, fingerprints):
    """Match capture's strict bounded POSIX shebang contract, never env or arguments."""
    prefix = content[:4096]
    if not prefix.startswith(b"#!") or b"\n" not in prefix:
        raise ValueError("unsupported Script closure")
    line = prefix.split(b"\n", 1)[0]
    if b"\r" in line or b"\x00" in line:
        raise ValueError("unsupported Script closure")
    declaration = line[2:].decode("utf-8")
    path = Path(declaration)
    if (not declaration or declaration != declaration.strip()
            or any(char.isspace() for char in declaration) or str(path) != declaration
            or declaration not in policy.allowed_interpreters or path == Path("/usr/bin/env")):
        raise ValueError("unsupported Script interpreter")
    return fingerprints[path]


def _inventory(module_folders, scripts, trust, budget):
    """Select bounded direct-child members without importing or probing plugins."""
    result = []
    discovery_policy = ModuleDiscoveryPolicy(budget.policy.timeout_ms,
        budget.policy.max_scanned_entries, min(budget.policy.max_candidates, budget.policy.max_scanned_entries))
    for folder in module_folders:
        _within_roots(folder, trust, budget)
        inventory = enumerate_module_candidates_owned(folder, policy=discovery_policy,
            budget=budget.discovery, scan_counter=budget.add_scan)
        if not inventory.accepted:
            raise ValueError("Module discovery rejected")
        budget.add_candidate(len(inventory.candidates))
        for candidate in inventory.candidates:
            if candidate.kind != "python_source":
                raise ValueError("unsupported Module closure")
            result.append((candidate.source_path, candidate.kind, candidate.logical_name, None))
    for source in scripts:
        _within_roots(source.target, trust, budget)
        inventory = discover_prepared_script_entries(source.target, source.platform_policy,
            operation=budget, budget=budget)
        if not inventory.accepted:
            raise ValueError("Script discovery rejected")
        result.extend((entry.source_path, "script", entry.final_registered_name, source.platform_policy)
                      for entry in inventory.entries)
    return result


def _within_roots(path, trust, budget):
    """Require a unique explicit source root, never infer or widen it."""
    _canonical(path, budget)
    if sum(path.is_relative_to(root) for root in trust.source_roots) != 1:
        raise ValueError("deployment source outside unique root")


def _encode(trust):
    """Encode deterministic existing-v1 authority and pin exact emitted bytes."""
    assertions = []
    for assertion in trust.closure_assertions:
        item = asdict(assertion)
        item["source_path"] = str(assertion.source_path)
        assertions.append(item)
    document = dict(schema_version=1, source_roots=sorted(str(root) for root in trust.source_roots),
        allowed_interpreters=sorted(str(path) for path in trust.allowed_interpreters),
        allow_native_scripts=False, closure_assertions=assertions, python_runtime=None)
    if trust.python_runtime is not None:
        document["python_runtime"] = dict(executable=str(trust.python_runtime.executable),
            content_sha256=trust.python_runtime.content_sha256, bootstrap=trust.python_runtime.bootstrap)
    manifest = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(manifest) > _MAX_MANIFEST_BYTES:
        raise ValueError("deployment manifest size limit exceeded")
    return manifest, hashlib.sha256(manifest).hexdigest()


def generate_mixed_trust_manifest(*, module_folders: tuple[Path, ...], scripts: tuple[ConfiguredScript, ...],
        source_roots: tuple[Path, ...], reviewed_deployment_sha256: str,
        python_runtime: ArtifactPythonRuntimeAuthority | None = None,
        interpreter_digests: tuple[tuple[Path, str], ...] = (),
        policy: ConfiguredPreparationPolicy = ConfiguredPreparationPolicy(), cancellation=None) -> tuple[bytes, str]:
    """Generate complete offline authority from explicit frozen, reviewed deployment inputs.

    Only POSIX shebang Scripts and single-file Python source Modules are supported.
    Regenerate from all intended sources; no prior manifest is merged or overwritten.
    Hashing does not attest review: the caller supplies that independent prerequisite.
    """
    trust = _inputs(module_folders, scripts, source_roots, reviewed_deployment_sha256,
        python_runtime, interpreter_digests, policy, cancellation)
    budget = _Budget(policy, cancellation)
    for root in trust.source_roots:
        _canonical(root, budget)
        if not _io(budget, root.is_dir):
            raise ValueError("deployment root must be a directory")
    fingerprint = None
    if python_runtime is not None:
        _canonical(python_runtime.executable, budget)
        budget.add_read(_io(budget, python_runtime.executable.lstat).st_size * 2)
        with _ledger() as owner:
            evidence, fingerprint = validation.validate_python_runtime(
                python_runtime, os.geteuid(), budget.checkpoint, owner)
    fingerprints = _interpreter_fingerprints(interpreter_digests, budget)
    inventory = _inventory(module_folders, scripts, trust, budget)
    assertions, policies, identities = {}, {}, {}
    for path, kind, name, script_policy in inventory:
        _within_roots(path, trust, budget)
        content, status = _read_source(path, budget, executable=kind == "script")
        key = (path, kind, name)
        identity = (status.st_dev, status.st_ino)
        if identity in identities and identities[identity] != path:
            raise ValueError("duplicate deployment source identity")
        identities[identity] = path
        runtime = _shebang(content, script_policy, fingerprints) if kind == "script" else fingerprint
        assertion = ArtifactClosureAssertion(path, kind, name, hashlib.sha256(content).hexdigest(),
            runtime, reviewed_deployment_sha256)
        if key in assertions and (assertions[key] != assertion or policies[key] != script_policy):
            raise ValueError("conflicting deployment authority")
        assertions[key], policies[key] = assertion, script_policy
    complete = ConfiguredTrustPolicy(trust.source_roots, trust.allowed_interpreters,
        closure_assertions=tuple(assertions[key] for key in sorted(assertions)), python_runtime=python_runtime)
    budget.checkpoint()
    result = _encode(complete)
    budget.checkpoint()
    return result


@contextmanager
def _output_stream(stream):
    """Close once while preserving an active body failure and uncertain custody."""
    try:
        yield stream
    except BaseException as primary:
        try:
            stream.close()
        except BaseException as cleanup_error:
            _retain_output_stream(primary, stream, cleanup_error)
        raise
    else:
        try:
            stream.close()
        except BaseException as primary:
            _retain_output_stream(primary, stream, primary)
            raise


def _retain_output_stream(primary, stream, cleanup_error):
    """Expose uncertain ownership as diagnostics, never as close-retry authority."""
    primary.deployment_output_stream_owner = stream
    primary.deployment_output_close_uncertain = True
    primary.add_note(f"deployment output close uncertain: {type(cleanup_error).__name__}")


def write_mixed_trust_manifest(output: Path, **inputs) -> str:
    """Write only a new manifest; return its pin only after successful close."""
    if not isinstance(output, Path) or not output.is_absolute():
        raise ValueError("absolute manifest output required")
    manifest, pin = generate_mixed_trust_manifest(**inputs)
    stream = output.open("xb")
    try:
        with _output_stream(stream):
            os.fstat(stream.fileno())
            if stream.write(manifest) != len(manifest):
                raise OSError("incomplete deployment manifest write")
    except BaseException as primary:
        try:
            output.lstat()
            # Observation cannot authorize atomic deletion of a possibly replaced path.
            primary.deployment_output_cleanup_pending = True
            primary.add_note("deployment output cleanup pending: ownership continuity unproven")
        except FileNotFoundError:
            pass  # Confirmed absence settles the incomplete-output obligation.
        except BaseException as cleanup_error:
            primary.deployment_output_cleanup_pending = True
            primary.add_note(f"deployment output cleanup pending: {type(cleanup_error).__name__}")
        raise
    return pin
