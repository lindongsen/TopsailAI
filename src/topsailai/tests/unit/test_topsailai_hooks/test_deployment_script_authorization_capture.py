"""Generated mixed authority through real prepared registration. Author: DawsonLin."""

import hashlib
import sys
from pathlib import Path

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, ConfiguredScript, EventDefinition, HookRuntime, HookSettings
from topsailai.hooks.artifact_contracts import ArtifactPythonRuntimeAuthority
from topsailai.hooks.configured_bootstrap import load_configured_trust_manifest
from topsailai.hooks.configured_contracts import ConfiguredPreparationRequest
from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.deployment_script_authorization import write_mixed_trust_manifest
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy


@pytest.fixture
def mixed_tree(tmp_path):
    """Prepare task-local frozen sources without executing them during generation."""
    tmp_path.chmod(0o700)
    sources = tmp_path / "sources"
    modules = sources / "modules"
    scripts = sources / "scripts"
    modules.mkdir(parents=True, mode=0o700)
    sources.chmod(0o700)
    scripts.mkdir(mode=0o700)
    trace = tmp_path / "trace"
    (modules / "observer.py").write_text(f"def main():\n    with open({str(trace)!r}, 'a') as stream:\n"
        "        stream.write('module\\n')\n    return 'observed'\n")
    executable = Path(sys.executable).resolve(strict=True)
    policy = ExecutablePlatformPolicy("posix", (str(executable),))
    for name in ("z", "A"):
        path = scripts / name
        path.write_text(f"#!{executable}\nimport json, os, struct, sys\n"
            "request = json.loads(sys.stdin.buffer.read())\n"
            "result = {key: request[key] for key in ('protocol_version', 'delivery_id', 'invocation_id', 'entry_index')}\n"
            f"with open({str(trace)!r}, 'a') as stream:\n    stream.write({name!r} + '\\n')\n"
            "result['value'] = None\nbody = json.dumps(result).encode()\n"
            "os.write(int(os.environ['TOPSAILAI_HOOK_RESULT_FD']), struct.pack('!I', len(body)) + body)\n")
        path.chmod(0o700)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    inputs = dict(module_folders=(modules,), scripts=(ConfiguredScript(scripts, policy),),
        source_roots=(sources,), reviewed_deployment_sha256="a" * 64,
        python_runtime=ArtifactPythonRuntimeAuthority(executable, digest), interpreter_digests=((executable, digest),))
    return sources, modules, scripts, trace, inputs


def register(tree, tmp_path, trust):
    """Use real public prepared Registrar and Executor with generated authority."""
    sources, modules, scripts, _, inputs = tree
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    runtime = HookRuntime(HookSettings(), temp_root=str(root), configured_trust=trust)
    scope = runtime.open_scope()
    points = tuple(HookPointDeclaration(f"hook__test__before__{name}",
        EventDefinition(f"hook__test__before__{name}", 1), "before", "sync", "test") for name in ("mixed", "sibling"))
    catalog = HookPointCatalog(points)
    configuration = ConfiguredHooks((ConfiguredHookPoint(points[0].name, points[0].definition,
        module_folder=modules, script=inputs["scripts"][0]),
        ConfiguredHookPoint(points[1].name, points[1].definition)), HookSettings())
    registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope, ConfiguredPreparationRequest(configuration, catalog))
    return runtime, registrar, ConfiguredHookExecutor(runtime, scope, registrar, catalog), points


@pytest.mark.parametrize("stale", [False, True])
def test_generated_manifest_real_capture_and_sibling_isolation(mixed_tree, tmp_path, stale):
    """Stale Script authority rejects the complete point before any Module runs."""
    sources, modules, scripts, trace, inputs = mixed_tree
    output = tmp_path / "manifest"
    pin = write_mixed_trust_manifest(output, **inputs)
    assert not trace.exists()
    trust, _ = load_configured_trust_manifest(output, pin)
    assert {(item.kind, item.logical_name) for item in trust.closure_assertions} == {
        ("python_source", "observer"), ("script", "A"), ("script", "z")}
    if stale:
        with (scripts / "A").open("a") as stream:
            stream.write("# stale source\n")
    runtime, registrar, executor, points = register(mixed_tree, tmp_path, trust)
    try:
        assert registrar.dispositions[1].kind == "registered"
        if stale:
            assert registrar.dispositions[0].kind == "unavailable_preparation_failure"
            assert not trace.exists()
        else:
            assert registrar.dispositions[0].kind == "registered"
            report = executor.dispatch(points[0], payload={})
            assert report.rejection_reason is None
            assert trace.read_text().splitlines() == ["module", "A", "z"]
            handlers = report.unified_result.handlers
            assert [item.handler.kind for item in handlers] == ["module", "default_script_hook"]
            assert [item.handler.name for item in handlers[-1].children] == ["A", "z"]
            assert all(item.cleanup.state == "safe" for item in handlers)
        assert executor.dispatch(points[1], payload={}).rejection_reason is None
    finally:
        registrar.close()
        report = runtime.close()
        assert not runtime.cleanup_debts()
