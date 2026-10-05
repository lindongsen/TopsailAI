"""Focused U07 trust, closure, and immutable-source validation tests."""

from __future__ import annotations

import hashlib
import os
import platform
import struct
import sys
from pathlib import Path

import pytest

from topsailai.hooks import (
    ArtifactCaptureOwner,
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
    ExecutablePlatformPolicy,
)
from topsailai.hooks.artifact_identity import native_runtime_fingerprint


def _native(tmp_path: Path):
    source_root = tmp_path / "source"
    artifact_root = tmp_path / "artifacts"
    source_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    source = source_root / "tool"
    machine = {"x86_64": 62, "aarch64": 183}[platform.machine()]
    data = b"\x7fELF" + bytes([2 if struct.calcsize("P") == 8 else 1]) + b"\x00" * 13 + machine.to_bytes(2, "little")
    source.write_bytes(data)
    source.chmod(0o500)
    policy = ExecutablePlatformPolicy("posix")
    request = ArtifactCaptureRequest(source, "script", "tool", policy)
    assertion = ArtifactClosureAssertion(source, "script", "tool", hashlib.sha256(data).hexdigest(), native_runtime_fingerprint(), "2" * 64)
    return source_root, artifact_root, source, request, assertion


def test_capture_source_ancestry_and_root_ambiguity(tmp_path: Path) -> None:
    """Reject a source outside its sole canonical authority root."""
    root, artifacts, source, request, assertion = _native(tmp_path)
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((other,), (), True, (assertion,)))
    assert owner.capture((request,)).errors == ("trust_rejected",)
    owner.close()


def test_capture_permissions_acl_and_capabilities(tmp_path: Path) -> None:
    """Reject a group-writable executable while retaining safe files."""
    root, artifacts, source, request, assertion = _native(tmp_path)
    source.chmod(0o520)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), True, (assertion,)))
    assert owner.capture((request,)).errors == ("trust_rejected",)
    owner.close()


def test_capture_requires_owner_pinned_closure(tmp_path: Path) -> None:
    """Reject missing and digest-mismatched host closure assertions."""
    root, artifacts, _, request, assertion = _native(tmp_path)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), True, ()))
    assert owner.capture((request,)).errors == ("unsupported_artifact_closure",)
    owner.close()
    wrong = ArtifactClosureAssertion(assertion.source_path, assertion.kind, assertion.logical_name, "0" * 64, assertion.runtime_sha256, assertion.deployment_sha256)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), True, (wrong,)))
    assert owner.capture((request,)).errors == ("unsupported_artifact_closure",)
    owner.close()


def test_script_only_and_empty_without_python_authority(tmp_path: Path) -> None:
    """Admit native and empty capture without inspecting Python authority."""
    root, artifacts, _, request, assertion = _native(tmp_path)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), True, (assertion,), None))
    assert owner.capture((request,)).accepted
    assert owner.capture(()).accepted
    owner.close()


def test_capture_interpreter_and_runtime_binding(tmp_path: Path) -> None:
    """Reject a module when explicit bootstrap authority is absent."""
    root, artifacts, _, _, _ = _native(tmp_path)
    module = root / "plugin.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    module.chmod(0o400)
    assertion = ArtifactClosureAssertion(module, "python_source", "plugin", hashlib.sha256(module.read_bytes()).hexdigest(), "0" * 64, "3" * 64)
    request = ArtifactCaptureRequest(module, "python_source", "plugin")
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), False, (assertion,), None))
    assert owner.capture((request,)).errors == ("unsupported_platform",)
    owner.close()


def test_python_bootstrap_authority_support_matrix(tmp_path: Path) -> None:
    """Reject a noncanonical trusted bootstrap path structurally or physically."""
    root, artifacts, _, _, _ = _native(tmp_path)
    executable = Path(sys.executable).resolve()
    authority = ArtifactPythonRuntimeAuthority(executable, "0" * 64)
    module = root / "plugin.py"
    module.write_bytes(b"x=1\n")
    module.chmod(0o400)
    request = ArtifactCaptureRequest(module, "python_source", "plugin")
    assertion = ArtifactClosureAssertion(module, "python_source", "plugin", hashlib.sha256(module.read_bytes()).hexdigest(), "0" * 64, "4" * 64)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), False, (assertion,), authority))
    assert owner.capture((request,)).errors in (("trust_rejected",), ("unsupported_platform",))
    owner.close()


def test_python_source_with_canonical_runtime_authority(tmp_path: Path) -> None:
    """Capture Python source only with exact ordinary-CPython bootstrap evidence."""
    root, artifacts, _, _, _ = _native(tmp_path)
    executable = Path(sys.executable).resolve(strict=True)
    executable_bytes = executable.read_bytes()
    executable_status = executable.stat()
    executable_digest = hashlib.sha256(executable_bytes).hexdigest()
    from topsailai.hooks.artifact_identity import python_runtime_fingerprint

    runtime_digest = python_runtime_fingerprint(
        executable,
        executable_digest,
        device=executable_status.st_dev,
        inode=executable_status.st_ino,
    )
    module = root / "plugin.py"
    module.write_bytes(b"VALUE = 1\n")
    module.chmod(0o400)
    request = ArtifactCaptureRequest(module, "python_source", "plugin")
    assertion = ArtifactClosureAssertion(
        module,
        "python_source",
        "plugin",
        hashlib.sha256(module.read_bytes()).hexdigest(),
        runtime_digest,
        "6" * 64,
    )
    authority = ArtifactPythonRuntimeAuthority(executable, executable_digest)
    trust = ArtifactCaptureTrust((root,), (), False, (assertion,), authority)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=trust)
    result = owner.capture((request,))
    assert result.accepted and result.artifact is not None
    assert result.artifact.entries[0].mode == 0o400
    owner.close()


def test_python_runtime_revalidation_rejects_same_size_digest_change(
    monkeypatch,
) -> None:
    """Reject changed Python runtime bytes even when the observed size is unchanged."""
    import topsailai.hooks.artifact_validation as validation
    from topsailai.hooks.artifact_cleanup import DescriptorLedger

    executable, digest, _ = _python_authority()
    authority = ArtifactPythonRuntimeAuthority(executable, digest)
    real_hash = validation.hash_descriptor
    calls = 0

    def changed_second_digest(descriptor, limit, checkpoint):
        nonlocal calls
        observed_digest, observed_size = real_hash(descriptor, limit, checkpoint)
        calls += 1
        if calls == 2:
            observed_digest = ("0" if observed_digest[0] != "0" else "1") + observed_digest[1:]
        return observed_digest, observed_size

    monkeypatch.setattr(validation, "hash_descriptor", changed_second_digest)
    ledger = DescriptorLedger()
    with pytest.raises(validation.ArtifactValidationError) as raised:
        validation.validate_python_runtime(authority, os.getuid(), lambda: None, ledger)
    assert raised.value.token == "artifact_source_changed"
    assert calls == 2 and not ledger.has_outstanding()


@pytest.mark.parametrize("mutation", ("mode", "acl"))
def test_python_runtime_revalidation_rejects_ancestor_security_change(
    monkeypatch, mutation: str,
) -> None:
    """Reject changed runtime-ancestor security after the initial hash."""
    import topsailai.hooks.artifact_validation as validation
    from topsailai.hooks.artifact_cleanup import DescriptorLedger

    executable, digest, _ = _python_authority()
    authority = ArtifactPythonRuntimeAuthority(executable, digest)
    real_hash = validation.hash_descriptor
    real_status = validation._validate_directory_status
    real_metadata = validation._require_fd_metadata_absent
    hashed = False

    def initial_hash_then_mutation_window(descriptor, limit, checkpoint):
        nonlocal hashed
        result = real_hash(descriptor, limit, checkpoint)
        hashed = True
        return result

    def changed_status(status, expected_uid, *, require_read=False):
        if hashed and mutation == "mode":
            raise validation.ArtifactValidationError("trust_rejected")
        return real_status(status, expected_uid, require_read=require_read)

    def changed_metadata(descriptor, *, directory, checkpoint=None):
        if hashed and mutation == "acl" and directory:
            raise validation.ArtifactValidationError("trust_rejected")
        return real_metadata(
            descriptor, directory=directory, checkpoint=checkpoint
        )

    monkeypatch.setattr(validation, "hash_descriptor", initial_hash_then_mutation_window)
    monkeypatch.setattr(validation, "_validate_directory_status", changed_status)
    monkeypatch.setattr(validation, "_require_fd_metadata_absent", changed_metadata)
    ledger = DescriptorLedger()
    with pytest.raises(validation.ArtifactValidationError) as raised:
        validation.validate_python_runtime(authority, os.getuid(), lambda: None, ledger)
    assert raised.value.token == "artifact_source_changed"
    assert hashed and not ledger.has_outstanding()


def test_native_script_requires_host_opt_in(tmp_path: Path) -> None:
    """Reject native execution when the host does not grant native authority."""
    root, artifacts, _, request, assertion = _native(tmp_path)
    trust = ArtifactCaptureTrust((root,), (), False, (assertion,))
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=trust)
    assert owner.capture((request,)).errors == ("trust_rejected",)
    owner.close()


def _python_authority() -> tuple[Path, str, str]:
    """Return canonical authority and fingerprint for the running CPython."""
    from topsailai.hooks.artifact_identity import python_runtime_fingerprint

    executable = Path(sys.executable).resolve(strict=True)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    status = executable.stat()
    fingerprint = python_runtime_fingerprint(
        executable, digest, device=status.st_dev, inode=status.st_ino
    )
    return executable, digest, fingerprint


def test_real_shebang_script_without_python_authority(tmp_path: Path) -> None:
    """Capture an exact real shebang script without Python bootstrap lookup."""
    interpreter = Path("/bin/sh").resolve(strict=True)
    root, artifacts, _, _, _ = _native(tmp_path)
    script = root / "run-hook"
    content = f"#!{interpreter}\nexit 0\n".encode()
    script.write_bytes(content)
    script.chmod(0o500)
    interpreter_bytes = interpreter.read_bytes()
    interpreter_status = interpreter.stat()
    from topsailai.hooks.artifact_identity import shebang_runtime_fingerprint

    runtime = shebang_runtime_fingerprint(
        interpreter,
        hashlib.sha256(interpreter_bytes).hexdigest(),
        device=interpreter_status.st_dev,
        inode=interpreter_status.st_ino,
    )
    policy = ExecutablePlatformPolicy("posix", (str(interpreter),))
    request = ArtifactCaptureRequest(script, "script", script.name, policy)
    assertion = ArtifactClosureAssertion(
        script,
        "script",
        script.name,
        hashlib.sha256(content).hexdigest(),
        runtime,
        "7" * 64,
    )
    trust = ArtifactCaptureTrust((root,), (interpreter,), False, (assertion,), None)
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=trust)
    result = owner.capture((request,))
    assert result.accepted and result.artifact is not None
    captured = result.artifact.directory / result.artifact.entries[0].relative_path
    assert captured.read_bytes() == content
    owner.close()


def test_locally_compiled_extension_positive_control(tmp_path: Path) -> None:
    """Capture a locally compiled compatible extension without importing it."""
    import importlib.machinery
    import subprocess

    root, artifacts, _, _, _ = _native(tmp_path)
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    source_code = tmp_path / "fixture.c"
    extension = root / f"fixture{suffix}"
    source_code.write_text("int topsailai_fixture(void) { return 7; }\n", encoding="utf-8")
    subprocess.run(
        ["cc", "-shared", "-fPIC", "-o", str(extension), str(source_code)],
        check=True,
        capture_output=True,
        text=True,
    )
    extension.chmod(0o400)
    executable, digest, runtime = _python_authority()
    request = ArtifactCaptureRequest(extension, "python_extension", "fixture")
    assertion = ArtifactClosureAssertion(
        extension,
        "python_extension",
        "fixture",
        hashlib.sha256(extension.read_bytes()).hexdigest(),
        runtime,
        "8" * 64,
    )
    trust = ArtifactCaptureTrust(
        (root,), (), False, (assertion,), ArtifactPythonRuntimeAuthority(executable, digest)
    )
    before = "fixture" in sys.modules
    owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=trust)
    result = owner.capture((request,))
    assert result.accepted and result.artifact is not None
    assert ("fixture" in sys.modules) is before
    owner.close()


def test_python_bootstrap_alias_copy_and_rejection_matrix(monkeypatch, tmp_path: Path) -> None:
    """Distinguish aliases, copied runtimes, symlink authority, and frozen hosts."""
    import shutil
    import subprocess

    executable, digest, _ = _python_authority()
    assert Path(sys.executable).resolve(strict=True) == executable

    (tmp_path / "symlink-authority").mkdir()
    root, artifacts, _, _, _ = _native(tmp_path / "symlink-authority")
    alias = tmp_path / "python-alias"
    alias.symlink_to(executable)
    module = root / "plugin.py"
    module.write_bytes(b"VALUE = 1\n")
    module.chmod(0o400)
    request = ArtifactCaptureRequest(module, "python_source", "plugin")
    assertion = ArtifactClosureAssertion(
        module, "python_source", "plugin", hashlib.sha256(module.read_bytes()).hexdigest(),
        "0" * 64, "9" * 64,
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust(
            (root,), (), False, (assertion,), ArtifactPythonRuntimeAuthority(alias, digest)
        ),
    )
    assert owner.capture((request,)).errors == ("unsupported_platform",)
    owner.close()

    (tmp_path / "frozen").mkdir()
    root, artifacts, _, _, _ = _native(tmp_path / "frozen")
    module = root / "plugin.py"
    module.write_bytes(b"VALUE = 1\n")
    module.chmod(0o400)
    request = ArtifactCaptureRequest(module, "python_source", "plugin")
    assertion = ArtifactClosureAssertion(
        module, "python_source", "plugin", hashlib.sha256(module.read_bytes()).hexdigest(),
        "0" * 64, "a" * 64,
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust(
            (root,), (), False, (assertion,), ArtifactPythonRuntimeAuthority(executable, digest)
        ),
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert owner.capture((request,)).errors == ("unsupported_platform",)
    monkeypatch.delattr(sys, "frozen", raising=False)
    owner.close()

    copied = tmp_path / "python-copy"
    shutil.copy2(executable, copied)
    copied.chmod(0o500)
    probe = subprocess.run(
        [
            str(copied),
            "-c",
            "import hashlib,os,pathlib,sys; p=pathlib.Path(sys.executable).resolve(); "
            "print(os.readlink('/proc/self/exe')); print(hashlib.sha256(p.read_bytes()).hexdigest())",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    observed_path, observed_digest = probe.stdout.splitlines()
    assert Path(observed_path) == copied
    assert observed_digest == hashlib.sha256(copied.read_bytes()).hexdigest()



def test_virtualenv_symlink_and_copied_runtime_capture(tmp_path: Path) -> None:
    """Capture modules inside real symlink and copied CPython bootstrap processes."""
    import shutil
    import subprocess

    probe = """
import hashlib
import pathlib
import sys
from topsailai.hooks import ArtifactCaptureOwner, ArtifactCaptureRequest, ArtifactCaptureTrust, ArtifactClosureAssertion, ArtifactPythonRuntimeAuthority
from topsailai.hooks.artifact_identity import python_runtime_fingerprint
base = pathlib.Path(sys.argv[1])
root = base / "source"
artifacts = base / "artifacts"
root.mkdir(mode=0o700)
artifacts.mkdir(mode=0o700)
module = root / "plugin.py"
content = b"VALUE = 1\\n"
module.write_bytes(content)
module.chmod(0o400)
executable = pathlib.Path(sys.executable).resolve(strict=True)
digest = hashlib.sha256(executable.read_bytes()).hexdigest()
status = executable.stat()
runtime = python_runtime_fingerprint(executable, digest, device=status.st_dev, inode=status.st_ino)
request = ArtifactCaptureRequest(module, "python_source", "plugin")
assertion = ArtifactClosureAssertion(module, "python_source", "plugin", hashlib.sha256(content).hexdigest(), runtime, "b" * 64)
owner = ArtifactCaptureOwner(artifact_root=str(artifacts), trust=ArtifactCaptureTrust((root,), (), False, (assertion,), ArtifactPythonRuntimeAuthority(executable, digest)))
result = owner.capture((request,))
print(result.accepted, result.errors)
owner.close()
"""
    source_parent = Path(__file__).resolve().parents[4]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_parent)

    copied = tmp_path / "copied-python"
    shutil.copy2(Path(sys.executable).resolve(strict=True), copied)
    copied.chmod(0o500)
    copied_case = tmp_path / "copied-case"
    copied_case.mkdir(mode=0o700)
    copied_result = subprocess.run(
        [str(copied), "-c", probe, str(copied_case)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert copied_result.stdout.splitlines()[0] == "True ()"

    virtualenv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--symlinks", "--system-site-packages", str(virtualenv)],
        check=True,
        capture_output=True,
        text=True,
    )
    virtualenv_case = tmp_path / "virtualenv-case"
    virtualenv_case.mkdir(mode=0o700)
    virtualenv_result = subprocess.run(
        [str(virtualenv / "bin" / "python"), "-c", probe, str(virtualenv_case)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert virtualenv_result.stdout.splitlines()[0] == "True ()"

def test_acl_capability_and_unsupported_enforcement(monkeypatch, tmp_path: Path) -> None:
    """Reject security metadata and fail closed when it cannot be observed."""
    import errno

    cases = (
        ("system.posix_acl_access", b"acl"),
        ("system.posix_acl_default", b"acl"),
        ("security.capability", b"capability"),
    )
    real_getxattr = os.getxattr
    for attribute, value in cases:
        case = tmp_path / attribute.replace(".", "-")
        case.mkdir()
        root, artifacts, _, request, assertion = _native(case)

        def getxattr(descriptor, name, *, _attribute=attribute, _value=value):
            if name == _attribute:
                return _value
            raise OSError(errno.ENODATA, "absent")

        monkeypatch.setattr(os, "getxattr", getxattr)
        owner = ArtifactCaptureOwner(
            artifact_root=str(artifacts),
            trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
        )
        assert owner.capture((request,)).errors == ("trust_rejected",)
        owner.close()

    (tmp_path / "unreadable").mkdir()
    root, artifacts, _, request, assertion = _native(tmp_path / "unreadable")

    def unreadable(descriptor, name):
        raise OSError(errno.EPERM, "denied")

    monkeypatch.setattr(os, "getxattr", unreadable)
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
    )
    assert owner.capture((request,)).errors == ("trust_rejected",)
    owner.close()

    monkeypatch.setattr(os, "getxattr", real_getxattr)
    monkeypatch.setattr(sys, "platform", "not-linux")
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
    )
    assert owner.capture((request,)).errors == ("unsupported_platform",)
    owner.close()


def test_real_capability_and_nonprivileged_permission_controls(tmp_path: Path) -> None:
    """Exercise a real capability rejection and a nonprivileged denied read."""
    import shutil
    import subprocess

    setcap = shutil.which("setcap")
    setpriv = shutil.which("setpriv")
    assert setcap is not None and setpriv is not None

    capability_case = tmp_path / "capability"
    capability_case.mkdir()
    root, artifacts, source, request, assertion = _native(capability_case)
    subprocess.run(
        [setcap, "cap_net_bind_service=ep", str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
    )
    assert owner.capture((request,)).errors == ("trust_rejected",)
    owner.close()
    subprocess.run([setcap, "-r", str(source)], check=True, capture_output=True, text=True)

    denied_root = tmp_path / "nonprivileged"
    denied_root.mkdir(mode=0o755)
    denied = denied_root / "root-only"
    denied.write_bytes(b"secret")
    denied.chmod(0o400)
    probe = subprocess.run(
        [setpriv, "--reuid=65534", "--regid=65534", "--clear-groups", "cat", str(denied)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0 and probe.stdout == ""


def test_source_and_ancestry_mutation_races(monkeypatch, tmp_path: Path) -> None:
    """Reject deterministic source, security metadata, symlink, and ancestry races."""
    import topsailai.hooks.artifact_store as store

    for mutation in ("same-inode", "metadata", "acl", "symlink", "ancestor"):
        case = tmp_path / mutation
        case.mkdir()
        root, artifacts, source, request, assertion = _native(case)
        owner = ArtifactCaptureOwner(
            artifact_root=str(artifacts),
            trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
        )
        real_revalidate = store.revalidate_source

        def mutate_then_revalidate(validated, checkpoint=lambda: None, *, _mutation=mutation):
            if _mutation == "same-inode":
                with source.open("ab") as stream:
                    stream.write(b"X")
            elif _mutation == "metadata":
                source.chmod(0o700)
            elif _mutation == "acl":
                _set_posix_acl(
                    source,
                    b"u::r-x,u:65534:r-x,g::---,m::r-x,o::---",
                    0x8000,
                )
            elif _mutation == "symlink":
                replacement = root / "replacement"
                replacement.write_bytes(source.read_bytes())
                replacement.chmod(0o500)
                source.unlink()
                source.symlink_to(replacement)
            else:
                moved = case / "source-moved"
                root.rename(moved)
                root.mkdir(mode=0o700)
                replacement = root / source.name
                replacement.write_bytes((moved / source.name).read_bytes())
                replacement.chmod(0o500)
            real_revalidate(validated, checkpoint)

        monkeypatch.setattr(store, "revalidate_source", mutate_then_revalidate)
        result = owner.capture((request,))
        assert result.errors == ("artifact_source_changed",), mutation
        assert result.artifact is None and not list(artifacts.iterdir()), mutation
        assert owner.cleanup_debts() == (), mutation
        owner.close()
        monkeypatch.setattr(store, "revalidate_source", real_revalidate)


def test_captured_artifact_survives_source_replacement(tmp_path: Path) -> None:
    """Keep sealed bytes independent from later source deletion and replacement."""
    root, artifacts, source, request, assertion = _native(tmp_path)
    original = source.read_bytes()
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
    )
    result = owner.capture((request,))
    assert result.accepted and result.artifact is not None
    captured = result.artifact.directory / result.artifact.entries[0].relative_path
    source.unlink()
    source.write_bytes(b"replacement")
    source.chmod(0o500)
    assert captured.read_bytes() == original
    assert result.artifact.entries[0].content_sha256 == hashlib.sha256(original).hexdigest()
    owner.close()


def _set_posix_acl(path: Path, text: bytes, acl_type: int) -> None:
    """Set one real POSIX ACL through libacl for an enforcement control."""
    import ctypes

    library = ctypes.CDLL("libacl.so.1", use_errno=True)
    library.acl_from_text.argtypes = (ctypes.c_char_p,)
    library.acl_from_text.restype = ctypes.c_void_p
    library.acl_set_file.argtypes = (ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
    library.acl_set_file.restype = ctypes.c_int
    library.acl_free.argtypes = (ctypes.c_void_p,)
    acl = library.acl_from_text(text)
    assert acl
    try:
        assert library.acl_set_file(os.fsencode(path), acl_type, acl) == 0
    finally:
        assert library.acl_free(acl) == 0


def test_real_access_and_default_acl_rejection(tmp_path: Path) -> None:
    """Reject real access and default ACL metadata from the host filesystem."""
    access_case = tmp_path / "access-acl"
    access_case.mkdir()
    root, artifacts, source, request, assertion = _native(access_case)
    _set_posix_acl(source, b"u::r-x,u:65534:r-x,g::---,m::r-x,o::---", 0x8000)
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
    )
    assert owner.capture((request,)).errors == ("trust_rejected",)
    owner.close()

    default_case = tmp_path / "default-acl"
    default_case.mkdir()
    root, artifacts, _, request, assertion = _native(default_case)
    _set_posix_acl(root, b"u::rwx,g::---,o::---", 0x4000)
    owner = ArtifactCaptureOwner(
        artifact_root=str(artifacts),
        trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
    )
    assert owner.capture((request,)).errors == ("trust_rejected",)
    owner.close()


def test_foreign_uid_setid_and_writable_ancestor_rejection(tmp_path: Path) -> None:
    """Reject foreign ownership, setid files, and writable source ancestry."""
    for name in ("foreign", "setid", "writable-ancestor"):
        case = tmp_path / name
        case.mkdir()
        root, artifacts, source, request, assertion = _native(case)
        if name == "foreign":
            os.chown(source, 65534, 65534)
        elif name == "setid":
            source.chmod(0o4500)
        else:
            root.chmod(0o1777)
        owner = ArtifactCaptureOwner(
            artifact_root=str(artifacts),
            trust=ArtifactCaptureTrust((root,), (), True, (assertion,)),
        )
        assert owner.capture((request,)).errors == ("trust_rejected",), name
        owner.close()
