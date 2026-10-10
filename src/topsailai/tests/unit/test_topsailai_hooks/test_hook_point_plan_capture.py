"""Real sealed complete candidate capture regressions. Author: DawsonLin."""
import hashlib
import sys
import time
from pathlib import Path

import pytest

from topsailai.hooks.artifact_contracts import (
    ArtifactCapturePolicy, ArtifactCaptureTrust, ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
)
from topsailai.hooks.artifact_identity import native_runtime_fingerprint, python_runtime_fingerprint
from topsailai.hooks.hook_script_discovery import (
    ExecutablePlatformPolicy, HookScriptDiscoveryResult, HookScriptEntry,
)
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.tests.unit.test_topsailai_hooks.test_hook_artifact_cleanup_retry import _native_bytes


def api():
    """Require the new additive capture API inside attributable RED tests."""
    from topsailai.hooks.hook_point_plan_capture import build_hook_point_candidate
    from topsailai.hooks.hook_point_plan_contracts import ModuleSource
    return build_hook_point_candidate, ModuleSource


def fixtures(tmp_path, *, bad_main=False):
    """Create trusted same-basename sources with distinct explicit identities."""
    build, source_type = api()
    root, output = tmp_path / "sources", tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    executable = Path(sys.executable).resolve()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    status = executable.stat()
    runtime = python_runtime_fingerprint(executable, digest, device=status.st_dev, inode=status.st_ino)
    assertions, modules, scripts = [], [], []
    import_marker, call_marker = tmp_path / "imported", tmp_path / "called"
    for index, alias in enumerate(("Z", "A")):
        directory = root / str(index)
        directory.mkdir(mode=0o700)
        module = directory / "u05a_canary.py"
        body = f"from pathlib import Path\nPath({str(import_marker)!r}).write_text('child')\n"
        body += "main = 3\n" if bad_main and index == 1 else f"def main(*args, **kwargs):\n    Path({str(call_marker)!r}).write_text('called')\n"
        module.write_text(body)
        module.chmod(0o400)
        modules.append(source_type(alias, module, "u05a_canary", "python_source", "u05a_canary:main"))
        assertions.append(ArtifactClosureAssertion(module, "python_source", "u05a_canary",
            hashlib.sha256(module.read_bytes()).hexdigest(), runtime, str(index + 1) * 64))
        script = directory / "physical"
        script.write_bytes(_native_bytes() + bytes([index]))
        script.chmod(0o500)
        scripts.append(HookScriptEntry(script, "physical", alias))
        assertions.append(ArtifactClosureAssertion(script, "script", "physical",
            hashlib.sha256(script.read_bytes()).hexdigest(), native_runtime_fingerprint(), str(index + 3) * 64))
    trust = ArtifactCaptureTrust((root,), (), True, tuple(assertions), ArtifactPythonRuntimeAuthority(executable, digest))
    inputs = dict(modules=tuple(modules), script_discovery=HookScriptDiscoveryResult(True, tuple(scripts)),
        platform_policy=ExecutablePlatformPolicy("posix"), trust=trust, artifact_root=str(output),
        probe_backend=IsolatedProcessBackend(temp_root=str(tmp_path)), policy=ArtifactCapturePolicy())
    return build, inputs, output, import_marker, call_marker


def test_real_complete_same_basename_capture(tmp_path):
    """Associate aliases with exact indexed sealed bytes and source trust."""
    build, inputs, output, imported, called = fixtures(tmp_path)
    before = inputs.copy()
    first = build("point", **inputs)
    second = build("point", **inputs)
    try:
        plan = first.plan
        assert [item.identity.name for item in plan.modules] == ["A", "Z"]
        assert [item.identity.name for item in plan.default_script_hook.scripts] == ["A", "Z"]
        items = plan.modules + plan.default_script_hook.scripts
        assert [item.inventory_index for item in items] == list(range(4))
        assert len({item.captured_path for item in items}) == 4
        for item in items:
            assert item.captured_path.read_bytes() == item.source_path.read_bytes()
            assert item.content_sha256 == hashlib.sha256(item.captured_path.read_bytes()).hexdigest()
            assertion = next(a for a in inputs["trust"].closure_assertions if a.source_path == item.source_path)
            assert item.deployment_sha256 == assertion.deployment_sha256
        assert plan.fingerprint == second.plan.fingerprint
        assert imported.exists() and not called.exists()
        assert "u05a_canary" not in sys.modules
        assert inputs == before
        item = plan.modules[0]
        sealed = item.captured_path.read_bytes()
        item.source_path.chmod(0o600)
        item.source_path.write_text("main = 9\n")
        assert item.captured_path.read_bytes() == sealed
    finally:
        assert first.close().accepted
        assert second.close().accepted
    assert list(output.iterdir()) == []


def test_empty_candidate_needs_no_capture(tmp_path):
    """Always create the default without touching an absent artifact root."""
    build, _ = api()
    candidate = build("point", platform_policy=ExecutablePlatformPolicy("posix"),
        trust=ArtifactCaptureTrust((tmp_path,)), artifact_root=str(tmp_path / "absent"),
        probe_backend=IsolatedProcessBackend(temp_root=str(tmp_path)), policy=ArtifactCapturePolicy())
    assert candidate.plan.modules == ()
    assert candidate.plan.default_script_hook.scripts == ()
    assert candidate.close().accepted and candidate.close().accepted
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("failure", ("duplicate", "entry", "deadline", "source"))
def test_atomic_failure(tmp_path, failure):
    """Reject complete candidate failure without leaving partial capture."""
    build, inputs, output, _, _ = fixtures(tmp_path, bad_main=failure == "entry")
    if failure == "duplicate":
        inputs["modules"] = (inputs["modules"][0],) * 2
    if failure == "deadline":
        inputs["deadline"] = time.monotonic() - 1.0
    if failure == "source":
        inputs["modules"][1].source_path.chmod(0o600)
        inputs["modules"][1].source_path.write_text("main = 4\n")
    with pytest.raises(ValueError):
        build("point", **inputs)
    assert list(output.iterdir()) == []


def test_probe_backend_is_exclusively_owned(tmp_path):
    """Never infer candidate custody from concurrent caller backend debt deltas."""
    build, inputs, _, _, _ = fixtures(tmp_path)
    candidate = build("point", **inputs)
    try:
        assert candidate._backend is not inputs["probe_backend"]
        assert candidate._backend._temp_root == inputs["probe_backend"]._temp_root
    finally:
        candidate.close()


def test_cleanup_debt_retry_retains_exact_capture(tmp_path, monkeypatch):
    """Keep unpublished bytes under custody until exact removal settles."""
    import types
    from topsailai.hooks import artifact_cleanup
    build, inputs, output, _, _ = fixtures(tmp_path)
    candidate = build("point", **inputs)
    unrelated = output / "unrelated"
    unrelated.mkdir(mode=0o700)
    original = artifact_cleanup.os
    def fail(path, *args, **kwargs):
        """Fail only indexed-directory cleanup without changing the shared os module."""
        if str(path).startswith("entry-"):
            raise OSError("injected removal failure")
        return original.rmdir(path, *args, **kwargs)
    isolated = types.SimpleNamespace(**{name: getattr(original, name) for name in dir(original)})
    isolated.rmdir = fail
    monkeypatch.setattr(artifact_cleanup, "os", isolated)
    result = candidate.close()
    assert result.cleanup_pending
    debt = candidate.cleanup_debts()[0]
    assert not candidate.retry_cleanup(debt.debt_id)
    monkeypatch.setattr(artifact_cleanup, "os", original)
    assert candidate.retry_cleanup(debt.debt_id)
    assert candidate.cleanup_debts() == ()
    assert list(output.iterdir()) == [unrelated]
    assert not candidate.retry_cleanup("foreign")


def test_interrupted_probe_retains_primary_and_custody(tmp_path, monkeypatch):
    """Preserve host interrupt identity and recover exact owned captures."""
    from topsailai.hooks import hook_point_plan_capture as capture
    build, inputs, output, _, _ = fixtures(tmp_path)
    interrupt = KeyboardInterrupt()
    def stop(*args, **kwargs):
        """Interrupt the first probe before any plugin invocation."""
        raise interrupt
    monkeypatch.setattr(capture, "probe_candidate", stop)
    with pytest.raises(KeyboardInterrupt) as caught:
        build("point", **inputs)
    assert caught.value is interrupt
    assert caught.value.recovery_owner.cleanup_debts() == ()
    assert list(output.iterdir()) == []


def test_configuration_and_invocation_fingerprint(tmp_path):
    """Detach mutable options and make semantic changes change the fingerprint."""
    from dataclasses import replace
    from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions
    from topsailai.hooks.module_invocation_protocol import ModuleInvocation
    build, inputs, _, _, _ = fixtures(tmp_path)
    argv, environment = ["literal"], [["KEY", "VALUE"]]
    options = HookScriptExecutionOptions(argv, None, environment)
    first = build("point", **inputs, options=options)
    argv.append("later")
    environment[0][1] = "changed"
    changed = dict(inputs)
    changed["modules"] = (replace(inputs["modules"][0], invocation=ModuleInvocation([{"x": [1]}], {})), inputs["modules"][1])
    second = build("point", **changed, options=options)
    try:
        assert first.plan.options.argv == ("literal",)
        assert first.plan.options.environment == (("KEY", "VALUE"),)
        assert first.plan.fingerprint != second.plan.fingerprint
        with pytest.raises(TypeError):
            second.plan.modules[1].invocation.args[0]["x"] = ()
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("mode", ("malformed", "correlation", "debt", "interrupt_debt", "late"))
def test_probe_failure_custody(tmp_path, monkeypatch, mode):
    """Reject malformed observations and retain bytes until exact process recovery."""
    from dataclasses import replace
    from topsailai.hooks import hook_point_plan_capture as capture
    from topsailai.hooks.module_discovery_probe import ModuleManifestEntry
    from topsailai.hooks.process_state import WorkerResult, CleanupDebt
    build, inputs, output, _, _ = fixtures(tmp_path)
    interrupt = KeyboardInterrupt()
    def probe(backend, root, hook, logical, path, timeout):
        """Inject a boundary result, not a substitute for real capture evidence."""
        if mode in ("debt", "interrupt_debt"):
            backend._debts["owned"] = CleanupDebt("owned", "pending", None, "test")
        if mode == "interrupt_debt":
            raise interrupt
        if mode == "late":
            monkeypatch.setattr(capture.time, "monotonic", lambda: inputs["deadline"] + 1)
        entry = ModuleManifestEntry(logical, path, (hook, str(root), logical), "main", True, "ready")
        if mode == "correlation":
            entry = replace(entry, source_path=path.parent / "wrong.py")
        value = {"load_status": "ready", "entry_valid": True}
        if mode == "malformed":
            value["extra"] = True
        return entry, WorkerResult("success", value, cleanup_confirmed=mode != "debt", cleanup_debt="owned" if mode == "debt" else None)
    monkeypatch.setattr(capture, "probe_candidate", probe)
    if mode == "late":
        inputs["deadline"] = time.monotonic() + 20.0
    error_type = KeyboardInterrupt if mode == "interrupt_debt" else ValueError
    with pytest.raises(error_type) as caught:
        build("point", **inputs)
    owner = caught.value.recovery_owner
    if mode in ("debt", "interrupt_debt"):
        assert owner.cleanup_debts()[0].debt_id == "owned"
        assert list(output.iterdir())
        def retry(debt_id):
            """Confirm exact fake obligation settlement for custody test."""
            assert debt_id == "owned"
            owner._backend._debts.pop(debt_id)
            return True
        monkeypatch.setattr(owner._backend, "retry_cleanup", retry)
        assert owner.retry_cleanup("owned")
    assert list(output.iterdir()) == []


def test_cross_kind_names_and_no_scripts(tmp_path):
    """Accept equal names across kinds and retain a terminal with zero Scripts."""
    build, inputs, _, _, _ = fixtures(tmp_path)
    inputs["script_discovery"] = None
    with build("point", **inputs) as candidate:
        assert len(candidate.plan.handlers) == 3
        assert candidate.plan.default_script_hook.scripts == ()


@pytest.mark.parametrize("field,value", [("modules", {}), ("modules", [None]),
    ("script_discovery", HookScriptDiscoveryResult(False)), ("platform_policy", None),
    ("trust", None), ("artifact_root", "relative"), ("probe_backend", None),
    ("policy", ArtifactCapturePolicy(max_entries=1)), ("deadline", True)])
def test_preallocation_boundaries(tmp_path, field, value):
    """Reject invalid metadata before artifact allocation or probing."""
    build, inputs, output, _, _ = fixtures(tmp_path)
    inputs[field] = value
    with pytest.raises(ValueError):
        build("point", **inputs)
    assert list(output.iterdir()) == []


def test_real_compiled_sealed_probe(tmp_path):
    """Preserve true CPython extension admission through captured bytes only."""
    from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import compile_extension
    build, inputs, _, _, _ = fixtures(tmp_path)
    root = inputs["trust"].source_roots[0]
    path = compile_extension(root, "u05a_compiled")
    path.chmod(0o400)
    _, source_type = api()
    inputs["modules"] = (source_type("Compiled", path, "u05a_compiled", "python_extension", "u05a_compiled:main"),)
    inputs["script_discovery"] = None
    from dataclasses import replace
    previous = inputs["trust"].closure_assertions[0]
    assertion = replace(previous, source_path=path, kind="python_extension", logical_name="u05a_compiled",
        content_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    inputs["trust"] = replace(inputs["trust"], closure_assertions=(assertion,))
    with build("point", **inputs) as candidate:
        item = candidate.plan.modules[0]
        assert item.source.kind == "python_extension"
        assert item.captured_path.read_bytes() == path.read_bytes()
        assert "u05a_compiled" not in sys.modules
        assert candidate._backend.cleanup_debts() == ()


@pytest.mark.parametrize("body_error,cleanup_error", [(False, False), (True, False), (False, True), (True, True)])
def test_context_failure_recovery(tmp_path, monkeypatch, body_error, cleanup_error):
    """Keep a body primary while exposing pending close or close interruption."""
    from topsailai.hooks.artifact_contracts import ArtifactDisposeResult
    build, inputs, _, _, _ = fixtures(tmp_path)
    candidate = build("point", **inputs)
    original = candidate.close
    primary = KeyboardInterrupt()
    def close():
        """Expose controlled cleanup failure after real capture."""
        if cleanup_error:
            raise OSError("cleanup failure")
        return ArtifactDisposeResult(True, cleanup_pending=True)
    monkeypatch.setattr(candidate, "close", close)
    try:
        with pytest.raises(BaseException) as caught:
            with candidate:
                if body_error:
                    raise primary
        if body_error:
            assert caught.value is primary
        assert caught.value.recovery_owner is candidate
    finally:
        monkeypatch.setattr(candidate, "close", original)
        candidate.close()
    with pytest.raises(RuntimeError):
        _ = candidate.plan


def test_process_retry_negative_boundaries():
    """Do not discard debt until exact backend settlement succeeds."""
    from types import SimpleNamespace
    from topsailai.hooks.hook_point_plan_ownership import HookPointCandidate
    candidate = HookPointCandidate(SimpleNamespace(retry_cleanup=lambda _: False, cleanup_debts=lambda: ()))
    candidate._probe_debts.add("owned")
    assert not candidate.retry_cleanup("owned")
    assert not candidate.retry_cleanup("foreign")
    assert "owned" in candidate._probe_debts


@pytest.mark.parametrize("mode", ("short", "mismatch", "cleanup", "interrupt"))
def test_capture_handoff_boundaries(tmp_path, monkeypatch, mode):
    """Exercise malformed capture correlation and cleanup interruption precedence."""
    from dataclasses import replace
    from types import SimpleNamespace
    from topsailai.hooks import hook_point_plan_capture as capture
    build, inputs, _, _, _ = fixtures(tmp_path)
    original = capture.ArtifactCaptureOwner.capture
    close = capture.ArtifactCaptureOwner.close
    def result(owner, *args, **kwargs):
        """Keep actual capture owner while corrupting only returned metadata."""
        actual = original(owner, *args, **kwargs)
        if mode in ("cleanup", "interrupt"):
            raise ValueError("primary") if mode == "cleanup" else KeyboardInterrupt()
        entries = actual.artifact.entries
        entries = entries[:-1] if mode == "short" else (replace(entries[0], index=1),) + entries[1:]
        proxy = SimpleNamespace(entries=entries, directory=actual.artifact.directory, identity=actual.artifact.identity)
        return replace(actual, artifact=proxy)
    monkeypatch.setattr(capture.ArtifactCaptureOwner, "capture", result)
    if mode in ("cleanup", "interrupt"):
        def broken_close(owner):
            """Interrupt cleanup without discarding its exact owner."""
            raise KeyboardInterrupt() if mode == "cleanup" else OSError("close")
        monkeypatch.setattr(capture.ArtifactCaptureOwner, "close", broken_close)
    with pytest.raises(KeyboardInterrupt if mode in ("cleanup", "interrupt") else ValueError) as caught:
        build("point", **inputs)
    owner = caught.value.recovery_owner
    monkeypatch.setattr(capture.ArtifactCaptureOwner, "close", close)
    assert owner.close().accepted


@pytest.mark.parametrize("value", (HookScriptDiscoveryResult(True, [None]), HookScriptDiscoveryResult(True, None)))
def test_invalid_script_container(tmp_path, value):
    """Validate discovery members before property access."""
    build, inputs, _, _, _ = fixtures(tmp_path)
    inputs["script_discovery"] = value
    with pytest.raises(ValueError):
        build("point", **inputs)


def test_alias_fingerprint_and_script_duplicate(tmp_path):
    """Alias changes affect semantics; Script duplicates reject before allocation."""
    from dataclasses import replace
    build, inputs, output, _, _ = fixtures(tmp_path)
    first = build("point", **inputs)
    changed = dict(inputs, modules=(replace(inputs["modules"][0], registered_name="Y"), inputs["modules"][1]))
    second = build("point", **changed)
    try:
        assert first.plan.fingerprint != second.plan.fingerprint
    finally:
        first.close()
        second.close()
    scripts = inputs["script_discovery"].entries
    inputs["script_discovery"] = HookScriptDiscoveryResult(True, (scripts[0], scripts[0]))
    with pytest.raises(ValueError):
        build("point", **inputs)
    assert list(output.iterdir()) == []


def test_untrusted_probe_runtime_rejects_before_capture(tmp_path):
    """Do not use an arbitrary worker module to validate trusted captured bytes."""
    build, inputs, output, _, _ = fixtures(tmp_path)
    inputs["probe_backend"]._worker_module = "untrusted.worker"
    with pytest.raises(ValueError):
        build("point", **inputs)
    assert list(output.iterdir()) == []


def test_scripts_only_alias_fallback(tmp_path):
    """Keep legacy basename fallback without requiring Module runtime probing."""
    from dataclasses import replace
    build, inputs, _, imported, called = fixtures(tmp_path)
    inputs["modules"] = ()
    scripts = inputs["script_discovery"].entries
    inputs["script_discovery"] = HookScriptDiscoveryResult(True, (replace(scripts[0], registered_name=None),))
    with build("point", **inputs) as candidate:
        assert candidate.plan.modules == ()
        assert candidate.plan.default_script_hook.scripts[0].identity.name == "physical"
        assert not imported.exists() and not called.exists()


def test_legacy_large_planning_does_not_inherit_candidate_limit(tmp_path):
    """Keep legacy planning capacity separate from new capture inventory bounds."""
    from topsailai.hooks.hook_script import build_hook_point_binding_plan_from_discovery
    build, inputs, output, imported, called = fixtures(tmp_path)
    entries = tuple(HookScriptEntry(tmp_path / f"legacy-{index:03d}", f"legacy-{index:03d}")
        for index in range(129))
    discovery = HookScriptDiscoveryResult(True, entries)
    legacy = build_hook_point_binding_plan_from_discovery(hook_point="point", module_bindings=(),
        bindings_per_event=1, hook_script_configured=True, discovery_result=discovery)
    assert legacy.accepted and len(legacy.bindings[-1].entries) == 129
    inputs.update(modules=(), script_discovery=discovery)
    with pytest.raises(ValueError, match="invalid script source collection"):
        build("point", **inputs)
    assert not imported.exists() and not called.exists()
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("body_type", (None, ValueError, KeyboardInterrupt, SystemExit))
@pytest.mark.parametrize("cleanup_type", (None, OSError, KeyboardInterrupt, SystemExit))
def test_context_exception_priority_matrix(tmp_path, monkeypatch, body_type, cleanup_type):
    """Cross exact exception identities with genuine capture debt and retry custody."""
    from types import SimpleNamespace
    from topsailai.hooks import artifact_cleanup
    build, inputs, output, _, _ = fixtures(tmp_path)
    candidate = build("point", **inputs)
    unrelated = output / "unrelated"
    unrelated.mkdir(mode=0o700)
    body = None if body_type is None else body_type("body")
    cleanup = None if cleanup_type is None else cleanup_type("cleanup")
    original_os, original_close = artifact_cleanup.os, candidate.close
    def fail_directory(path, *args, **kwargs):
        """Retain real indexed-directory removal debt without shared os mutation."""
        if str(path).startswith("entry-"):
            raise OSError("indexed cleanup failure")
        return original_os.rmdir(path, *args, **kwargs)
    def close():
        """Create actual cleanup debt before raising the selected cleanup exception."""
        result = original_close()
        assert result.cleanup_pending
        assert candidate.cleanup_debts()
        raise cleanup
    if cleanup is not None:
        isolated = SimpleNamespace(**{name: getattr(original_os, name) for name in dir(original_os)})
        isolated.rmdir = fail_directory
        monkeypatch.setattr(artifact_cleanup, "os", isolated)
        monkeypatch.setattr(candidate, "close", close)
    expected = body
    if cleanup is not None and (body is None or isinstance(body, Exception) and not isinstance(cleanup, Exception)):
        expected = cleanup
    caught = None
    try:
        with candidate:
            if body is not None:
                raise body
    except BaseException as error:
        caught = error
    finally:
        monkeypatch.setattr(candidate, "close", original_close)
        monkeypatch.setattr(artifact_cleanup, "os", original_os)
    try:
        assert caught is expected
        if cleanup is not None:
            assert caught.recovery_owner is candidate
            debts = candidate.cleanup_debts()
            assert len(debts) == 1
            assert not candidate.retry_cleanup("foreign")
            assert candidate.retry_cleanup(debts[0].debt_id)
        assert candidate.cleanup_debts() == ()
        assert list(output.iterdir()) == [unrelated]
        if caught is cleanup and body is not None:
            assert cleanup.__context__ is body
        if caught is not None:
            stack, seen = [(caught, frozenset())], set()
            while stack:
                error, ancestors = stack.pop()
                assert id(error) not in ancestors
                if id(error) in seen:
                    continue
                seen.add(id(error))
                stack.extend((edge, ancestors | {id(error)}) for edge in
                    (error.__cause__, error.__context__) if edge is not None)
    finally:
        assert candidate.close().accepted


@pytest.mark.parametrize("shared_diagnosis", (False, True))
def test_context_cleanup_interrupt_preserves_existing_body_chain(tmp_path, monkeypatch, shared_diagnosis):
    """Preserve prior body evidence while cutting only a cycle-forming back edge."""
    build, inputs, output, _, _ = fixtures(tmp_path)
    candidate = build("point", **inputs)
    original = candidate.close
    body, diagnosis, interrupt = ValueError("body"), RuntimeError("prior diagnosis"), KeyboardInterrupt("cleanup")
    body.__cause__ = diagnosis
    if shared_diagnosis:
        body.__context__ = diagnosis
    diagnosis.__context__ = interrupt
    def close():
        """Interrupt cleanup with the same pre-chained object."""
        raise interrupt
    monkeypatch.setattr(candidate, "close", close)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            with candidate:
                raise body
        assert caught.value is interrupt
        assert interrupt.recovery_owner is candidate
        assert interrupt.__context__ is body
        assert body.__cause__ is diagnosis
        assert diagnosis.__context__ is None
    finally:
        monkeypatch.setattr(candidate, "close", original)
        assert candidate.close().accepted
    assert list(output.iterdir()) == []
