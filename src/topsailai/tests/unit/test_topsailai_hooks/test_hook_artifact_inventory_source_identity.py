"""Physical inventory source identity regressions. Author: DawsonLin."""
import hashlib

import pytest

from topsailai.hooks import (
    ArtifactCaptureOwner, ArtifactCaptureTrust, ArtifactClosureAssertion,
    ArtifactCaptureRequest, ExecutablePlatformPolicy, HookScriptEntry,
)
from topsailai.hooks.artifact_identity import native_runtime_fingerprint
from topsailai.tests.unit.test_topsailai_hooks.test_hook_artifact_cleanup_retry import _native_bytes


def _pair(tmp_path, *, unique=False):
    """Create two separately trusted sources and unchanged registered aliases."""
    root = tmp_path / "sources"
    root.mkdir(mode=0o700)
    output = tmp_path / "artifacts"
    output.mkdir(mode=0o700)
    requests, assertions, aliases, contents = [], [], [], []
    for index, alias in enumerate(("Z", "A")):
        directory = root / str(index)
        directory.mkdir(mode=0o700)
        source = directory / (f"physical{index}" if unique else "physical")
        content = _native_bytes() + bytes([index])
        source.write_bytes(content)
        source.chmod(0o500)
        requests.append(ArtifactCaptureRequest(source, "script", source.name, ExecutablePlatformPolicy("posix")))
        assertions.append(ArtifactClosureAssertion(source, "script", source.name,
            hashlib.sha256(content).hexdigest(), native_runtime_fingerprint(), str(index + 1) * 64))
        aliases.append(HookScriptEntry(source, source.name, alias))
        contents.append(content)
    trust = ArtifactCaptureTrust((root,), (), True, tuple(assertions))
    return ArtifactCaptureOwner(artifact_root=str(output), trust=trust), tuple(requests), tuple(aliases), tuple(contents), output


@pytest.mark.parametrize("unique", (False, True))
def test_trusted_sources_remain_separately_addressable(tmp_path, unique):
    """Preserve aliases, trust, immutable bytes and stable indexed fingerprints."""
    owner, requests, aliases, contents, output = _pair(tmp_path, unique=unique)
    snapshot = (requests, aliases)
    try:
        first = owner.capture(requests)
        assert first.accepted and first.artifact is not None
        artifact = first.artifact
        for index, entry in enumerate(artifact.entries):
            assert entry.index == index
            assert entry.logical_name == requests[index].logical_name
            assert entry.validation.source_path == aliases[index].source_path
            assert entry.validation.deployment_sha256 == str(index + 1) * 64
            assert entry.content_sha256 == hashlib.sha256(contents[index]).hexdigest()
            assert entry.relative_path == f"entry-{index:06d}/{requests[index].logical_name}"
            assert (artifact.directory / entry.relative_path).read_bytes() == contents[index]
        identity = artifact.identity
        assert not owner.dispose(artifact).cleanup_pending
        second = owner.capture(requests)
        assert second.accepted and second.artifact.identity == identity
        assert not owner.dispose(second.artifact).cleanup_pending
        reverse = owner.capture(tuple(reversed(requests)))
        assert reverse.accepted and reverse.artifact.identity != identity
        assert (requests, aliases) == snapshot
        assert tuple(item.final_registered_name for item in aliases) == ("Z", "A")
        assert tuple(r.source_path.read_bytes() for r in requests) == contents
    finally:
        owner.close()
    assert owner.cleanup_debts() == () and list(output.iterdir()) == []
    print("cleanup confirmed: exact owned capture directories removed")


def test_duplicate_source_rejected_without_capture(tmp_path):
    """Aliases cannot authorize a duplicate source path or allocate a directory."""
    owner, requests, aliases, _, output = _pair(tmp_path)
    try:
        assert aliases[0].registered_name != aliases[1].registered_name
        result = owner.capture((requests[0], requests[0]))
        assert not result.accepted and result.artifact is None
        assert result.errors == ("invalid_artifact_request",)
        assert list(output.iterdir()) == [] and owner.cleanup_debts() == ()
    finally:
        owner.close()


@pytest.mark.parametrize("pending", (False, True))
def test_later_trust_failure_is_atomic_with_retry_custody(tmp_path, monkeypatch, pending):
    """Do not publish partial bytes or lose cleanup authority after later failure."""
    import topsailai.hooks.artifact_cleanup as cleanup
    owner, requests, _, _, output = _pair(tmp_path)
    unrelated = output / "unrelated"
    unrelated.mkdir(mode=0o700)
    requests[1].source_path.chmod(0o700)
    requests[1].source_path.write_bytes(_native_bytes() + b"different")
    requests[1].source_path.chmod(0o500)
    real_rmdir = cleanup.os.rmdir

    def fail_owned_removal(path, *args, **kwargs):
        """Inject cleanup failure only for an owned indexed directory."""
        if path == "entry-000000":
            raise OSError("fixture cleanup failure")
        return real_rmdir(path, *args, **kwargs)

    if pending:
        monkeypatch.setattr(cleanup.os, "rmdir", fail_owned_removal)
    try:
        result = owner.capture(requests)
        assert not result.accepted and result.artifact is None
        if pending:
            assert result.errors == ("artifact_cleanup_pending",)
            assert result.recovery_owner is owner
            assert len(owner.cleanup_debts()) == 1
            monkeypatch.setattr(cleanup.os, "rmdir", real_rmdir)
            assert owner.retry_cleanup(owner.cleanup_debts()[0].debt_id)
        else:
            assert result.errors == ("unsupported_artifact_closure",)
        assert owner.cleanup_debts() == ()
        assert list(output.iterdir()) == [unrelated]
    finally:
        monkeypatch.setattr(cleanup.os, "rmdir", real_rmdir)
        owner.close()
    assert unrelated.exists()
    print("cleanup confirmed: owned captures removed and unrelated directory preserved")


def test_python_sources_share_physical_name_without_host_import(tmp_path):
    """Keep same-named Modules in separate sealed locators with exact runtime trust."""
    import sys
    from pathlib import Path
    from topsailai.hooks import ArtifactPythonRuntimeAuthority
    from topsailai.hooks.artifact_identity import python_runtime_fingerprint
    root = tmp_path / "sources"
    output = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    executable = Path(sys.executable).resolve(strict=True)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    status = executable.stat()
    runtime = python_runtime_fingerprint(executable, digest, device=status.st_dev, inode=status.st_ino)
    requests, assertions, contents = [], [], []
    for index in range(2):
        directory = root / str(index)
        directory.mkdir(mode=0o700)
        source = directory / "inventory_canary.py"
        content = f"raise RuntimeError('must not import {index}')\n".encode()
        source.write_bytes(content)
        source.chmod(0o400)
        requests.append(ArtifactCaptureRequest(source, "python_source", "inventory_canary"))
        assertions.append(ArtifactClosureAssertion(source, "python_source", "inventory_canary",
            hashlib.sha256(content).hexdigest(), runtime, str(index + 1) * 64))
        contents.append(content)
    trust = ArtifactCaptureTrust((root,), (), False, tuple(assertions), ArtifactPythonRuntimeAuthority(executable, digest))
    with ArtifactCaptureOwner(artifact_root=str(output), trust=trust) as owner:
        result = owner.capture(tuple(requests))
        assert result.accepted and result.artifact is not None
        for index, entry in enumerate(result.artifact.entries):
            assert entry.index == index and entry.logical_name == "inventory_canary"
            assert entry.validation.source_path == requests[index].source_path
            assert entry.validation.runtime_sha256 == runtime
            assert (result.artifact.directory / entry.relative_path).read_bytes() == contents[index]
        assert "inventory_canary" not in sys.modules
    assert list(output.iterdir()) == [] and owner.cleanup_debts() == ()
    print("cleanup confirmed: both owned Module locators removed")
