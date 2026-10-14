"""Offline mixed trust contracts and bounded failure paths. Author: DawsonLin."""

import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

from topsailai.hooks import deployment_script_authorization as generator
from topsailai.hooks.artifact_contracts import ArtifactPythonRuntimeAuthority
from topsailai.hooks.configured_bootstrap import load_configured_trust_manifest
from topsailai.hooks.configured_contracts import ConfiguredPreparationPolicy, ConfiguredScript
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.deployment_authorization import generate_module_trust_manifest

ROOT = Path(__file__).resolve().parents[3] / ".tmp/summary-scripts/step110"


@pytest.fixture
def deployment(tmp_path):
    """Create explicitly reviewed fixture authority under task basetemp."""
    tmp_path.chmod(0o700)
    sources = tmp_path / "sources"
    sources.mkdir(mode=0o700)
    modules = sources / "modules"
    scripts = sources / "scripts"
    modules.mkdir(mode=0o700)
    scripts.mkdir(mode=0o700)
    module = modules / "observer.py"
    module.write_text("raise RuntimeError('must not import')\ndef main():\n    return None\n")
    executable = Path(sys.executable).resolve(strict=True)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    policy = ExecutablePlatformPolicy("posix", (str(executable),))
    for name in ("z", "A"):
        path = scripts / name
        path.write_text(f"#!{executable}\nraise RuntimeError('must not execute')\n")
        path.chmod(0o700)
    return dict(module_folders=(modules,), scripts=(ConfiguredScript(scripts, policy),),
        source_roots=(sources,), reviewed_deployment_sha256="a" * 64,
        python_runtime=ArtifactPythonRuntimeAuthority(executable, digest),
        interpreter_digests=((executable, digest),))


def generate(deployment, **overrides):
    """Apply explicit per-call input overrides without ambient authority."""
    return generator.generate_mixed_trust_manifest(**(deployment | overrides))


def test_deterministic_roundtrip_and_unchanged_modules(deployment, tmp_path):
    """No plugin is imported and emitted bytes round-trip through the pinned loader."""
    manifest, pin = generate(deployment)
    assert generate(deployment) == (manifest, pin)
    document = json.loads(manifest)
    assert [(item["kind"], item["logical_name"]) for item in document["closure_assertions"]] == [
        ("python_source", "observer"), ("script", "A"), ("script", "z")]
    assert not document["allow_native_scripts"]
    output = tmp_path / "manifest"
    assert generator.write_mixed_trust_manifest(output, **deployment) == pin
    trust, _ = load_configured_trust_manifest(output, pin)
    assert len(trust.closure_assertions) == 3
    module_options = {key: deployment[key] for key in (
        "module_folders", "source_roots", "reviewed_deployment_sha256", "python_runtime")}
    old = generate_module_trust_manifest(**module_options)
    assert generate(deployment, scripts=(), interpreter_digests=()) == old
    with pytest.raises(ValueError):
        load_configured_trust_manifest(output, "b" * 64)
    with pytest.raises(FileExistsError):
        generator.write_mixed_trust_manifest(output, **deployment)
    assert output.read_bytes() == manifest


def test_script_only_empty_and_membership_regeneration(deployment):
    """Full explicit regeneration removes deleted members, without ambient merging."""
    folder = deployment["scripts"][0].target
    kwargs = dict(module_folders=(), python_runtime=None)
    manifest, _ = generate(deployment, **kwargs)
    assert json.loads(manifest)["python_runtime"] is None
    assert len(json.loads(manifest)["closure_assertions"]) == 2
    print(f"Deleted fixture Script: {folder / 'z'}")
    (folder / "z").unlink()
    assert len(json.loads(generate(deployment)[0])["closure_assertions"]) == 2
    print(f"Deleted fixture Script: {folder / 'A'}")
    (folder / "A").unlink()
    assert len(json.loads(generate(deployment)[0])["closure_assertions"]) == 1
    (folder / "new").write_text(f"#!{deployment['python_runtime'].executable}\npass\n")
    (folder / "new").chmod(0o700)
    assert len(json.loads(generate(deployment)[0])["closure_assertions"]) == 2
    assert json.loads(generate(deployment, scripts=(), interpreter_digests=(), **kwargs)[0])["closure_assertions"] == []


@pytest.mark.parametrize("override", [
    {"reviewed_deployment_sha256": None}, {"policy": None}, {"cancellation": object()},
    {"module_folders": []}, {"module_folders": ("bad",)}, {"scripts": []}, {"scripts": (None,)},
    {"python_runtime": None}, {"interpreter_digests": []},
    {"interpreter_digests": (None,)}, {"interpreter_digests": ((Path('/usr/bin/python'), None),)},
    {"interpreter_digests": ()}, {"source_roots": []},
])
def test_invalid_shape_rejected_before_io(deployment, override, monkeypatch):
    """Malformed authority never authorizes dependent filesystem observations."""
    def forbidden(*args, **kwargs):
        """Fail if input validation touches the filesystem."""
        pytest.fail("unexpected filesystem I/O")
    monkeypatch.setattr(generator, "_canonical", forbidden)
    with pytest.raises(ValueError):
        generate(deployment, **override)


@pytest.mark.parametrize("case", ["duplicate_module", "duplicate_interpreter", "extra_interpreter",
    "windows", "native", "duplicate_policy", "relative_policy", "wrong_digest", "wrong_runtime",
    "outside", "overlap", "root_file", "missing", "symlink", "nonexecutable", "hardlink", "special"])
def test_authority_and_membership_rejections(deployment, tmp_path, case):
    """Unsafe roots, policies, formats, and identities fail closed."""
    overrides = {}
    source = deployment["scripts"][0]
    executable, digest = deployment["interpreter_digests"][0]
    if case == "duplicate_module":
        overrides["module_folders"] = deployment["module_folders"] * 2
    elif case == "duplicate_interpreter":
        overrides["interpreter_digests"] = deployment["interpreter_digests"] * 2
    elif case == "extra_interpreter":
        overrides["interpreter_digests"] = ((executable, digest), (Path('/unselected'), digest))
    elif case in ("windows", "native", "duplicate_policy", "relative_policy"):
        policy = ExecutablePlatformPolicy("windows" if case == "windows" else "posix",
            (str(executable), str(executable)) if case == "duplicate_policy" else
            (("relative",) if case == "relative_policy" else (str(executable),)),
            (".exe",) if case == "native" else ())
        if case == "relative_policy":
            with pytest.raises(ValueError):
                ConfiguredScript(source.target, policy)
            return
        overrides["scripts"] = (ConfiguredScript(source.target, policy),)
    elif case == "wrong_digest":
        overrides["interpreter_digests"] = ((executable, "b" * 64),)
    elif case == "wrong_runtime":
        overrides["python_runtime"] = ArtifactPythonRuntimeAuthority(executable, "b" * 64)
    elif case == "outside":
        overrides["source_roots"] = (deployment["module_folders"][0],)
    elif case == "overlap":
        overrides["source_roots"] = (deployment["source_roots"][0], source.target)
    elif case == "root_file":
        overrides["source_roots"] = (source.target / "A",)
    elif case == "missing":
        overrides["scripts"] = (ConfiguredScript(source.target / "missing", source.platform_policy),)
    elif case == "symlink":
        (source.target / "link").symlink_to(source.target / "A")
    elif case == "nonexecutable":
        (source.target / "A").chmod(0o600)
    elif case == "hardlink":
        import os
        os.link(source.target / "A", source.target / "link")
    elif case == "special":
        import os
        os.mkfifo(source.target / "fifo")
    with pytest.raises((ValueError, OSError, generator.validation.ArtifactValidationError)):
        generate(deployment, **overrides)


@pytest.mark.parametrize("header", [b"no shebang\n", b"#!/usr/bin/env\n", b"#! /bad\n", b"#!/bad arg\n",
    b"#!/bad\r\n", b"#!/bad\x00\n", b"#!\xff\n", b"#!/bad", b"#!\n"])
def test_strict_shebang(header, deployment):
    """Discovery's prefix recognition never substitutes for strict capture syntax."""
    path = deployment["scripts"][0].target / "A"
    path.write_bytes(header)
    with pytest.raises((ValueError, generator.validation.ArtifactValidationError)):
        generate(deployment)


@pytest.mark.parametrize("policy", [ConfiguredPreparationPolicy(max_candidates=1),
    ConfiguredPreparationPolicy(max_scanned_entries=1), ConfiguredPreparationPolicy(max_artifact_bytes=1)])
def test_aggregate_limits(deployment, policy):
    """Aggregate limits include all selected directories and interpreter bytes."""
    with pytest.raises(ValueError):
        generate(deployment, policy=policy)


def test_cancelled_and_expired(deployment, monkeypatch):
    """One immutable deadline and latched cancellation prevent generation."""
    event = threading.Event()
    event.set()
    with pytest.raises(ValueError, match="stopped"):
        generate(deployment, cancellation=event)
    times = iter((0.0, 20.0))
    monkeypatch.setattr(generator, "time", type("Clock", (), {"monotonic": staticmethod(lambda: next(times))}))
    with pytest.raises(ValueError, match="stopped"):
        generate(deployment)


def test_stable_read_detects_named_replacement(deployment, monkeypatch):
    """A replacement after reading cannot inherit reviewed source authority."""
    path = deployment["module_folders"][0] / "observer.py"
    real_read = generator.os.read
    changed = False
    def replace(descriptor, size):
        """Replace only the exact fixture source after its first data read."""
        nonlocal changed
        content = real_read(descriptor, size)
        if content.startswith(b"raise RuntimeError") and not changed:
            changed = True
            replacement = path.with_name("replacement")
            replacement.write_bytes(content)
            replacement.replace(path)
        return content
    monkeypatch.setattr(generator, "os", type("OSProxy", (), {
        "__getattr__": lambda self, name: getattr(__import__('os'), name), "read": staticmethod(replace)})())
    with pytest.raises(ValueError, match="changed"):
        generate(deployment)


def test_duplicate_inputs_coalesce_but_policy_conflicts_reject(deployment):
    """Only identical fully validated assertions may coalesce."""
    assert generate(deployment, scripts=deployment["scripts"] * 2) == generate(deployment)
    source = deployment["scripts"][0]
    policy = ExecutablePlatformPolicy("posix", (str(deployment["python_runtime"].executable), str(Path('/bin/sh').resolve())))
    other = ConfiguredScript(source.target, policy)
    shell = Path('/bin/sh').resolve()
    with pytest.raises(ValueError, match="conflicting"):
        generate(deployment, scripts=(source, other), interpreter_digests=deployment["interpreter_digests"] +
            ((shell, hashlib.sha256(shell.read_bytes()).hexdigest()),))


def test_exclusive_writer_refuses_alias_and_invalid_output(deployment, tmp_path):
    """Existing symlinks and relative output never overwrite deployed bytes."""
    target = tmp_path / "existing"
    target.write_bytes(b"original")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        generator.write_mixed_trust_manifest(link, **deployment)
    with pytest.raises(ValueError):
        generator.write_mixed_trust_manifest(Path("relative"), **deployment)
    assert target.read_bytes() == b"original"


def test_manifest_size_bound(deployment, monkeypatch):
    """Oversized emitted authority is rejected, never truncated."""
    monkeypatch.setattr(generator, "_MAX_MANIFEST_BYTES", 1)
    with pytest.raises(ValueError, match="manifest size"):
        generate(deployment)


@pytest.mark.parametrize("header", [b"bad\n", b"#!/bad", b"#!/bad\r\n", b"#!/bad\x00\n",
    b"#!\n", b"#! /bad\n", b"#!/bad arg\n", b"#!/bad\n", b"#!/usr/bin/env\n"])
def test_strict_parser_independent_of_discovery(header):
    """Capture-compatible parser rejects even when discovery is not involved."""
    with pytest.raises(ValueError):
        generator._shebang(header, ExecutablePlatformPolicy("posix", ("/usr/bin/env",)), {})


@pytest.mark.parametrize("primary", [False, True])
@pytest.mark.parametrize("interrupt", [False, True])
def test_ledger_retains_cleanup_authority(monkeypatch, primary, interrupt):
    """Pending descriptor cleanup preserves the host primary and recovery owner."""
    class Ledger:
        """Model exact outstanding cleanup without touching actual descriptors."""
        count = 1
        def close_all(self):
            """Inject one cleanup interruption or ordinary failure."""
            if interrupt:
                raise KeyboardInterrupt()
            return (OSError(),)
    monkeypatch.setattr(generator, "DescriptorLedger", Ledger)
    original = SystemExit("host")
    with pytest.raises(BaseException) as caught:
        with generator._ledger():
            if primary:
                raise original
    if primary:
        assert caught.value is original
        assert caught.value.deployment_descriptor_owner.count == 1
    else:
        assert caught.value.deployment_descriptor_owner.count == 1


def test_canonical_alias_and_noncanonical_spelling(deployment, tmp_path):
    """Reject source aliases and lexical parent traversal before reading bytes."""
    budget = generator._Budget(ConfiguredPreparationPolicy(), None)
    link = tmp_path / "alias"
    link.symlink_to(deployment["source_roots"][0], target_is_directory=True)
    with pytest.raises(ValueError, match="noncanonical"):
        generator._canonical(link, budget)
    with pytest.raises(ValueError, match="noncanonical"):
        generator._canonical(deployment["source_roots"][0] / "modules" / "..", budget)


def test_source_byte_limit(deployment, monkeypatch):
    """Read limit rejects source size before allocating unbounded buffers."""
    monkeypatch.setattr(generator, "_MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="byte limit"):
        generate(deployment)


def test_cross_input_duplicate_identity(deployment):
    """Hardlinked files across separate selections cannot evade identity checks."""
    import os
    source = deployment["scripts"][0]
    other = source.target.parent / "other"
    other.mkdir(mode=0o700)
    os.link(source.target / "A", other / "copy")
    with pytest.raises(ValueError, match="duplicate deployment source identity"):
        generate(deployment, scripts=(source, ConfiguredScript(other, source.platform_policy)))


def test_module_discovery_failure_and_extension(deployment):
    """Modules remain single-file source closure; unsupported extensions are explicit."""
    import importlib.machinery
    folder = deployment["module_folders"][0]
    with pytest.raises(ValueError, match="Module discovery"):
        generate(deployment, module_folders=(folder / "observer.py",))
    extension = folder / ("native" + importlib.machinery.EXTENSION_SUFFIXES[0])
    extension.write_bytes(b"not an authorized extension")
    with pytest.raises(ValueError, match="unsupported Module"):
        generate(deployment)


@pytest.mark.parametrize("failure", ["short", "interrupt", "cleanup"])
def test_writer_failure_preserves_primary_and_never_advertises_pin(deployment, tmp_path, monkeypatch, failure):
    """Failed writes retain pending output without retrying close or unlinking."""
    output = tmp_path / "failed-manifest"
    real_open = Path.open
    primary = KeyboardInterrupt("host")
    class Stream:
        """Wrap one owned file and inject write failure without global I/O mutation."""
        def __init__(self, stream):
            """Take ownership of the exact fixture stream."""
            self.stream = stream
            self.closes = 0
        def fileno(self):
            """Expose its real descriptor for exact named identity."""
            return self.stream.fileno()
        def close(self):
            """Close exactly once even when a host primary is active."""
            self.closes += 1
            self.stream.close()
        def write(self, data):
            """Write partial bytes then inject the selected failure."""
            self.stream.write(data[:1])
            if failure == "interrupt":
                raise primary
            return 1
    wrappers = []
    def opened(path, *args, **kwargs):
        """Instrument only exclusive output, not input authority reads."""
        stream = real_open(path, *args, **kwargs)
        if path == output and args and args[0] == "xb":
            stream = Stream(stream)
            wrappers.append(stream)
        return stream
    monkeypatch.setattr(Path, "open", opened)
    if failure == "cleanup":
        real_lstat = Path.lstat
        def lstat(path, *args, **kwargs):
            """Fail only output observation to retain explicit diagnostics."""
            if path == output:
                raise OSError("cleanup")
            return real_lstat(path, *args, **kwargs)
        monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(BaseException) as caught:
        generator.write_mixed_trust_manifest(output, **deployment)
    assert wrappers[0].closes == 1
    if failure == "interrupt":
        assert caught.value is primary
    assert caught.value.deployment_output_cleanup_pending is True
    assert "cleanup pending" in caught.value.__notes__[0]
    assert output.read_bytes()



@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_successful_body_cleanup_interrupt_retains_independent_obligations(tmp_path, monkeypatch, interrupt_type):
    """Retain exact ledger custody and settle other descriptors without close replay."""
    import os
    from types import SimpleNamespace
    from topsailai.hooks import artifact_cleanup

    primary = interrupt_type("cleanup interrupted")
    attempts = []
    real_close = os.close
    local_os = SimpleNamespace(**vars(os))
    def close(descriptor):
        """Close once, then interrupt the first uncertain outcome."""
        attempts.append(descriptor)
        real_close(descriptor)
        if len(attempts) == 1:
            raise primary
    local_os.close = close
    monkeypatch.setattr(artifact_cleanup, "os", local_os)
    descriptors = []
    with pytest.raises(interrupt_type) as caught:
        with generator._ledger() as owner:
            descriptors.append(owner.open(tmp_path / "first", os.O_CREAT | os.O_RDWR, 0o600))
            descriptors.append(owner.open(tmp_path / "second", os.O_CREAT | os.O_RDWR, 0o600))
    assert caught.value is primary
    assert caught.value.deployment_descriptor_owner is owner
    assert owner.count == 2
    assert attempts == descriptors[:1]
    assert os.fstat(descriptors[1]).st_size == 0
    assert owner.close_all() == ()
    assert attempts == descriptors
    assert owner.count == 1  # The first ambiguous outcome remains explicit.
    assert owner.close_all() == ()
    assert attempts == descriptors
    assert "cleanup interrupted" in primary.__notes__[0]


@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("replacement", [False, True])
def test_initial_output_probe_retains_pending_cleanup(tmp_path, monkeypatch, failure_type, replacement):
    """An unproven created identity never authorizes deletion or a success pin."""
    import os
    from types import SimpleNamespace

    output = tmp_path / "manifest"
    primary = failure_type("initial identity probe")
    monkeypatch.setattr(generator, "generate_mixed_trust_manifest", lambda **inputs: (b"manifest", "pin"))
    local_os = SimpleNamespace(**vars(os))
    def fstat(descriptor):
        """Fail the first identity probe, optionally after replacing its pathname."""
        if replacement:
            print(f"Deleted owned output fixture for replacement: {output}")
            output.unlink()
            output.write_bytes(b"replacement")
        raise primary
    local_os.fstat = fstat
    monkeypatch.setattr(generator, "os", local_os)
    with pytest.raises(failure_type) as caught:
        generator.write_mixed_trust_manifest(output)
    assert caught.value is primary
    assert primary.deployment_output_cleanup_pending is True
    assert "ownership continuity unproven" in primary.__notes__[0]
    assert output.read_bytes() == (b"replacement" if replacement else b"")
    with pytest.raises(FileExistsError):
        generator.write_mixed_trust_manifest(output)


@pytest.mark.parametrize("replacement", [False, True])
def test_output_write_failure_protects_replacement_or_confirms_absence(tmp_path, monkeypatch, replacement):
    """Known creation identity grants no authority over a later replacement."""
    output = tmp_path / "manifest"
    primary = OSError("write failed")
    real_open = Path.open
    wrappers = []
    monkeypatch.setattr(generator, "generate_mixed_trust_manifest", lambda **inputs: (b"manifest", "pin"))
    class Stream:
        """Keep the created inode open while replacing its named path."""
        def __init__(self, stream):
            """Retain exact fixture stream ownership."""
            self.stream = stream
            self.closes = 0
        def fileno(self):
            """Allow the initial identity observation."""
            return self.stream.fileno()
        def close(self):
            """Close once without replaying ambiguous operations."""
            self.closes += 1
            self.stream.close()
        def write(self, data):
            """Replace or remove only the owned fixture before failing."""
            print(f"Deleted owned output fixture during write: {output}")
            output.unlink()
            if replacement:
                output.write_bytes(b"replacement")
            raise primary
    def opened(path, mode="r", *args, **kwargs):
        """Wrap exclusive creation only; leave replacement writes untouched."""
        stream = real_open(path, mode, *args, **kwargs)
        if path == output and mode == "xb":
            stream = Stream(stream)
            wrappers.append(stream)
        return stream
    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(OSError) as caught:
        generator.write_mixed_trust_manifest(output)
    assert caught.value is primary
    assert wrappers[0].closes == 1
    if replacement:
        assert output.read_bytes() == b"replacement"
        assert primary.deployment_output_cleanup_pending is True
        assert "ownership continuity unproven" in primary.__notes__[0]
    else:
        assert not output.exists()
        assert not hasattr(primary, "deployment_output_cleanup_pending")


@pytest.mark.parametrize("stage", ["probe", "write", "success"])
@pytest.mark.parametrize("primary_type", [OSError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("close_type", [OSError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("path_state", ["owned", "replacement", "absent"])
def test_writer_combined_failure_preserves_primary_and_uncertain_owner(
        tmp_path, monkeypatch, stage, primary_type, close_type, path_state):
    """Cross body/close failures without replay, exception replacement or unsafe unlink."""
    import os
    from types import SimpleNamespace

    output = tmp_path / "manifest"
    primary = primary_type("body failure")
    cleanup_error = close_type("close failure")
    real_open = Path.open
    real_fstat = os.fstat
    wrappers = []
    frames = []
    monkeypatch.setattr(generator, "generate_mixed_trust_manifest", lambda **inputs: (b"manifest", "pin"))
    class Stream:
        """Own one real stream with an injected ambiguous close result."""
        def __init__(self, stream):
            """Record the exact created file and close-attempt counter."""
            self.stream = stream
            self.closes = 0
        def fileno(self):
            """Expose the descriptor only for the original identity probe."""
            return self.stream.fileno()
        def write(self, data):
            """Record partial output and inject the original write exception."""
            if stage == "write":
                self.stream.write(data[:1])
                fail_body()
            return self.stream.write(data)
        def close(self):
            """Attempt one close and model failure after physical settlement."""
            self.closes += 1
            self.stream.close()
            if path_state == "replacement":
                output.rename(tmp_path / "retained-original")
                output.write_bytes(b"replacement")
            elif path_state == "absent":
                print(f"Deleted owned output fixture during close: {output}")
                output.unlink()
            raise cleanup_error
    def fail_body():
        """Keep an observable original traceback frame for identity assertions."""
        frames.append(sys._getframe())
        raise primary
    def fstat(descriptor):
        """Inject failure before identity exists, without global os mutation."""
        if stage == "probe":
            fail_body()
        return real_fstat(descriptor)
    def opened(path, mode="r", *args, **kwargs):
        """Wrap only exclusive output creation; replacements use ordinary I/O."""
        stream = real_open(path, mode, *args, **kwargs)
        if path == output and mode == "xb":
            stream = Stream(stream)
            wrappers.append(stream)
        return stream
    local_os = SimpleNamespace(**vars(os))
    local_os.fstat = fstat
    monkeypatch.setattr(generator, "os", local_os)
    monkeypatch.setattr(Path, "open", opened)
    expected = cleanup_error if stage == "success" else primary
    with pytest.raises(type(expected)) as caught:
        generator.write_mixed_trust_manifest(output)
    assert caught.value is expected
    assert wrappers[0].closes == 1
    assert expected.deployment_output_stream_owner is wrappers[0]
    assert expected.deployment_output_close_uncertain is True
    assert expected.__notes__[0] == f"deployment output close uncertain: {close_type.__name__}"
    if stage != "success":
        traceback = expected.__traceback__
        observed_frames = []
        while traceback is not None:
            observed_frames.append(traceback.tb_frame)
            traceback = traceback.tb_next
        assert frames[0] in observed_frames
    if path_state != "absent":
        assert expected.deployment_output_cleanup_pending is True
        assert output.read_bytes() == (b"replacement" if path_state == "replacement" else
            b"" if stage == "probe" else b"m" if stage == "write" else b"manifest")
    else:
        assert not output.exists()
        assert not hasattr(expected, "deployment_output_cleanup_pending")


@pytest.mark.parametrize("race", ["identifier_reuse", "after_observation"])
@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt, SystemExit])
def test_writer_failure_never_unlinks_reused_or_racing_output(tmp_path, monkeypatch, race, failure_type):
    """Inject historical identity reuse or post-stat replacement without deletion authority."""
    import os
    from types import SimpleNamespace

    output = tmp_path / "manifest"
    primary = failure_type("write failure")
    real_open, real_lstat, real_unlink = Path.open, Path.lstat, Path.unlink
    wrappers, observations, deletions = [], [], []
    monkeypatch.setattr(generator, "generate_mixed_trust_manifest", lambda **inputs: (b"manifest", "pin"))
    class Stream:
        """Close the original descriptor before replacing its pathname."""
        def __init__(self, stream):
            """Retain exact stream and historical identity solely for test observation."""
            self.stream, self.closes = stream, 0
            self.identity = os.fstat(stream.fileno())
        def fileno(self):
            """Return the original descriptor for the initial probe."""
            return self.stream.fileno()
        def write(self, data):
            """Inject the exact primary without producing a successful pin."""
            raise primary
        def close(self):
            """Close once; release the inode before the reuse scenario creates a replacement."""
            self.closes += 1
            self.stream.close()
            if race == "identifier_reuse":
                replace_output()
    def replace_output():
        """Replace only this fixture output and log its deletion."""
        print(f"Deleted owned output fixture for race: {output}")
        real_unlink(output)
        output.write_bytes(b"replacement")
    def opened(path, mode="r", *args, **kwargs):
        """Wrap only exclusive output creation."""
        stream = real_open(path, mode, *args, **kwargs)
        if path == output and mode == "xb":
            stream = Stream(stream)
            wrappers.append(stream)
        return stream
    def lstat(path, *args, **kwargs):
        """Model reuse deterministically or replace after the captured observation."""
        status = real_lstat(path, *args, **kwargs)
        if path == output:
            observations.append(status)
            if race == "after_observation":
                replace_output()
            old = wrappers[0].identity
            return SimpleNamespace(st_dev=old.st_dev, st_ino=old.st_ino)
        return status
    def unlink(path, *args, **kwargs):
        """Record any unauthorized cleanup deletion attempt."""
        if path == output:
            deletions.append(path)
            raise AssertionError("output unlink is not authorized")
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(failure_type) as caught:
        generator.write_mixed_trust_manifest(output)
    assert caught.value is primary
    assert wrappers[0].closes == 1
    assert len(observations) == 1
    assert not deletions
    assert primary.deployment_output_cleanup_pending is True
    assert output.read_bytes() == b"replacement"
