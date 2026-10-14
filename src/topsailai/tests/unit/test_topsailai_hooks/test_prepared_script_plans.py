"""Complete multi-Script prepared plans. Author: DawsonLin."""

from pathlib import Path

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, ConfiguredScript, EventDefinition, HookSettings
from topsailai.hooks import configured_preparation as preparation
from topsailai.hooks.configured_trust import ConfiguredTrustPolicy
from tests.unit.test_topsailai_hooks import test_configured_preparation as helpers
from tests.unit.test_topsailai_hooks.test_configured_preparation import secure_test_root
from tests.unit.test_topsailai_hooks.test_prepared_script_sources import POLICY, script


@pytest.fixture(autouse=True)
def task_root(monkeypatch):
    """Keep reused fixtures inside the S1 temporary owner tree."""
    monkeypatch.setattr(helpers, "_PHASE_B_ROOT",
        Path(__file__).resolve().parents[3] / ".tmp/summary-scripts/s1/fixtures")


def point(folder, name="hook_alpha"):
    """Create a generic point with an explicitly authorized Script source."""
    return ConfiguredHookPoint(name, EventDefinition(f"test.{name}", 1),
        script=ConfiguredScript(folder, platform_policy=POLICY))


@pytest.mark.parametrize("executable", [False, True])
@pytest.mark.parametrize("count", [0, 1, 3])
def test_every_script_retained(secure_test_root, executable, count):
    """Real trusted capture preserves all names and exact sealed indices."""
    sources, root, _ = secure_test_root
    paths = [script(sources / name) for name in ("z", "A", "b")[:count]]
    runtime, scope = helpers._runtime(sources, root)
    trust = runtime.configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        closure_assertions=tuple(helpers._assertion(path, path.name, "script") for path in paths),
        python_runtime=trust.python_runtime, allowed_interpreters=tuple(Path(value) for value in POLICY.allowed_interpreters))
    try:
        image = preparation.prepare_private(runtime,
            ConfiguredHooks((point(sources),), HookSettings()), scope, _executable=executable)
        assert image.accepted, getattr(image, "errors", ())
        plan = image.plans[0]
        assert len(plan.script_artifact_identities) == count
        if executable:
            scripts = plan.executable.default_script_hook.scripts
            assert [item.identity.name for item in scripts] == sorted(path.name for path in paths)
            assert [item.inventory_index for item in scripts] == list(range(count))
        assert image.close().accepted
    finally:
        runtime.close()


def authorize(runtime, paths):
    """Inject exact fixture authority without granting production trust."""
    trust = runtime.configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        closure_assertions=tuple(helpers._assertion(path, path.stem if path.suffix == ".py" else path.name,
            "python_source" if path.suffix == ".py" else "script") for path in paths),
        python_runtime=trust.python_runtime,
        allowed_interpreters=tuple(Path(value) for value in POLICY.allowed_interpreters))


def test_private_multiple_executable_points_rejected_before_allocation(secure_test_root, monkeypatch):
    """Reject an unsupported private image without constructing custody."""
    sources, root, _ = secure_test_root
    runtime, scope = helpers._runtime(sources, root)
    def forbidden(*args, **kwargs):
        """Detect any attempted ownership allocation."""
        pytest.fail("allocated unsupported multiple-point image")
    monkeypatch.setattr(preparation, "PreparationOwnership", forbidden)
    try:
        result = preparation.prepare_private(runtime, ConfiguredHooks(
            (point(sources, "hook_one"), point(sources, "hook_two")), HookSettings()),
            scope, _executable=True)
        assert not result.accepted and result.errors == ("invalid_configuration",)
    finally:
        runtime.close()


def test_passive_points_keep_shared_capture_indexes(secure_test_root, monkeypatch):
    """Observe actual global indexes without inventing independent plans."""
    sources, root, _ = secure_test_root
    paths = [script(sources / name) for name in ("one", "two")]
    runtime, scope = helpers._runtime(sources, root)
    authorize(runtime, paths)
    observed = []
    original = preparation._map_capture_batch
    def record(batch, lease):
        """Retain the exact mapper result for identity assertions."""
        result = original(batch, lease)
        observed.extend(result)
        return result
    monkeypatch.setattr(preparation, "_map_capture_batch", record)
    try:
        image = preparation.prepare_private(runtime, ConfiguredHooks(tuple(
            point(path, f"hook_{path.name}") for path in paths), HookSettings()), scope)
        assert image.accepted
        assert [item.entry_index for item in observed] == [0, 1]
        assert len({item.lease.identity for item in observed}) == 1
        assert [item.work.entry.source_path for item in observed] == paths
        assert image.close().accepted
    finally:
        runtime.close()


def protocol_script(path, value, trace=None):
    """Create a real correlated result-channel Script."""
    trace_code = (f"with open({str(trace)!r}, 'a') as stream:\n    stream.write({value!r} + '\\n')\n"
                  if trace is not None else "")
    path.write_text(f"#!{POLICY.allowed_interpreters[0]}\n" +
        "import json, os, struct, sys\nrequest = json.loads(sys.stdin.buffer.read())\n" +
        "result = {key: request[key] for key in ('protocol_version', 'delivery_id', 'invocation_id', 'entry_index')}\n" +
        trace_code + f"result['value'] = {value!r}\nprint({value!r})\n" +
        "body = json.dumps(result).encode()\nos.write(int(os.environ['TOPSAILAI_HOOK_RESULT_FD']), struct.pack('!I', len(body)) + body)\n")
    path.chmod(0o700)
    return path


def test_public_points_register_independently_and_execute_all_members(secure_test_root, monkeypatch):
    """Real public registration isolates failure and ordered returns per point."""
    from topsailai.hooks.configured_contracts import SummaryPreparationRequest
    from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor
    from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
    sources, root, _ = secure_test_root
    module_folder = sources / "modules"
    script_folder = sources / "scripts"
    module_folder.mkdir(mode=0o700)
    script_folder.mkdir(mode=0o700)
    module = module_folder / "first.py"
    trace = sources.parent / "execution-trace"
    module.write_text(f"def main():\n    with open({str(trace)!r}, 'a') as stream:\n"
        "        stream.write('module\\n')\n    return 'module'\n")
    scripts = [protocol_script(script_folder / name, name, trace) for name in ("z", "A")]
    other = protocol_script(sources / "other", "other")
    bad = script(sources / "bad")
    runtime, scope = helpers._runtime(sources, root)
    authorize(runtime, [module, *scripts, other])
    declarations = tuple(HookPointDeclaration(f"hook__test__before__{name}",
        EventDefinition(f"hook__test__before__{name}", 1), "before", "sync", "test")
        for name in ("many", "other", "bad"))
    catalog = HookPointCatalog(declarations)
    configuration = ConfiguredHooks((
        ConfiguredHookPoint(declarations[0].name, declarations[0].definition,
            module_folder=module_folder, script=ConfiguredScript(script_folder, platform_policy=POLICY)),
        ConfiguredHookPoint(declarations[1].name, declarations[1].definition,
            script=ConfiguredScript(other, platform_policy=POLICY)),
        ConfiguredHookPoint(declarations[2].name, declarations[2].definition,
            script=ConfiguredScript(bad, platform_policy=POLICY))), HookSettings())
    from topsailai.hooks import script_runner
    decoded = []
    real_decode = script_runner.decode_script_result
    def observe_decode(*args, **kwargs):
        """Observe real correlated wire values without replacing transport or validation."""
        result = real_decode(*args, **kwargs)
        decoded.append((kwargs["entry_index"], result.value))
        return result
    monkeypatch.setattr(script_runner, "decode_script_result", observe_decode)
    indexes = []
    original = preparation._build_executable_plan
    def record(selected, captured):
        """Observe true point-local capture without changing publication."""
        indexes.append([item.entry_index for item in captured])
        return original(selected, captured)
    monkeypatch.setattr(preparation, "_build_executable_plan", record)
    try:
        registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope,
            SummaryPreparationRequest(configuration, catalog))
        assert [item.kind for item in registrar.dispositions] == ["registered", "registered", "unavailable_preparation_failure"]
        assert indexes == [[0, 1, 2], [0]]
        executor = ConfiguredHookExecutor(runtime, scope, registrar, catalog)
        report = executor.dispatch(declarations[0], payload={})
        assert report.rejection_reason is None
        handlers = report.unified_result.handlers
        assert [item.handler.kind for item in handlers] == ["module", "default_script_hook"]
        assert handlers[0].returned.value == "module"
        assert trace.read_text().splitlines() == ["module", "A", "z"]
        assert decoded == [(0, "A"), (1, "z")]
        assert [item.returned.value for item in handlers[-1].children] == [
            {"exit_code": 0, "stdout": name.encode() + b"\n", "stderr": b"",
             "stdout_dropped": 0, "stderr_dropped": 0} for name in ("A", "z")]
        print("PREPARED_REAL_RETURN_EVIDENCE", decoded, trace.read_text().splitlines())
        raw = handlers[-1].returned.value
        assert [(item.entry_index, item.status.value, item.exit_code,
                 item.cleanup_confirmed, item.cleanup_debt) for item in raw] == [
            (0, "success", 0, True, None), (1, "success", 0, True, None)]
        assert [item.handler.name for item in handlers[-1].children] == ["A", "z"]
        assert [item.returned.value["stdout"] for item in handlers[-1].children] == [b"A\n", b"z\n"]
        assert all(item.status == "success" and item.cleanup.state == "safe" for item in handlers)
        second = executor.dispatch(declarations[1], payload={})
        assert second.unified_result.handlers[0].children[0].returned.value["stdout"] == b"other\n"
        assert not runtime.cleanup_debts()
        registrar.close()
    finally:
        runtime.close()


@pytest.mark.parametrize("count", [128, 129])
def test_mixed_point_limit_before_capture(secure_test_root, monkeypatch, count):
    """Count Modules and Scripts together without allocating a capture lease."""
    sources, root, _ = secure_test_root
    runtime, scope = helpers._runtime(sources, root)
    selected = point(sources)
    module = preparation._ModuleWork(0, selected, sources, None)
    member = preparation._ScriptWork(0, selected, None)
    monkeypatch.setattr(preparation, "_build_work_sequence",
        lambda *args: (module,) + (member,) * (count - 1))
    seen = []
    def capture(works, *args):
        """Stop at the capture boundary without authorizing physical work."""
        seen.append(len(works))
        raise preparation._PreparationRejected("artifact_rejected")
    monkeypatch.setattr(preparation, "_capture_work_sequence", capture)
    try:
        result = preparation.prepare_private(runtime,
            ConfiguredHooks((selected,), HookSettings()), scope, _executable=True)
        assert result.errors == (("artifact_rejected",) if count == 128 else ("capacity_exceeded",))
        assert seen == ([128] if count == 128 else [])
        assert not runtime.cleanup_debts()
    finally:
        runtime.close()


@pytest.mark.parametrize("mode", ["settled_error", "pending", "deadline", "cancelled", "script_pending"])
def test_prepared_multi_script_barriers(secure_test_root, mode):
    """Execute the captured complete shape without replaying unsafe successors."""
    import threading
    from topsailai.hooks.contracts import HookStatus
    from topsailai.hooks.hook_point_executor import execute_hook_point
    from topsailai.hooks.hook_point_plan_ownership import HookPointReader, PublishedHookPoint
    from topsailai.hooks.process_state import WorkerResult
    from tests.unit.test_topsailai_hooks.test_hook_point_executor import Runner
    from tests.unit.test_topsailai_hooks.test_process_backend import _context
    sources, root, _ = secure_test_root
    modules, scripts = sources / "modules", sources / "scripts"
    modules.mkdir(mode=0o700)
    scripts.mkdir(mode=0o700)
    module = modules / "first.py"
    module.write_text("def main():\n    return None\n")
    paths = [script(scripts / name) for name in ("z", "A")]
    runtime, scope = helpers._runtime(sources, root)
    authorize(runtime, [module, *paths])
    image = None
    try:
        configured = ConfiguredHookPoint("hook_alpha", EventDefinition("test.alpha", 1),
            module_folder=modules, script=ConfiguredScript(scripts, platform_policy=POLICY))
        image = preparation.prepare_private(runtime,
            ConfiguredHooks((configured,), HookSettings()), scope, _executable=True)
        assert image.accepted
        reader = HookPointReader(PublishedHookPoint(image.plans[0].executable, 1), None, None)
        cancel, now = threading.Event(), [1.]
        runner = Runner([(HookStatus.ERROR, False) if mode == "script_pending"
                         else (HookStatus.SUCCESS, True), (HookStatus.SUCCESS, True)])
        def execute(**call):
            """Supply independent cleanup/stop facts at the Module boundary."""
            if mode == "deadline":
                now[0] = 10.
            if mode == "cancelled":
                cancel.set()
            return WorkerResult("error" if mode == "settled_error" else "success",
                cleanup_confirmed=mode != "pending")
        report = execute_hook_point(reader=reader, context=_context(),
            module_executor=execute, script_runner=runner, deadline=10.,
            cancellation=cancel, capacity=8, clock=lambda: now[0])
        assert [item.handler.kind for item in report.handlers] == ["module", "default_script_hook"]
        expected_calls = 2 if mode == "settled_error" else 1 if mode == "script_pending" else 0
        assert len(runner.calls) == expected_calls
        if mode in ("pending", "script_pending"):
            assert report.cleanup.state == "pending"
        if expected_calls:
            assert [item.handler.name for item in report.handlers[-1].children] == ["A", "z"]
        else:
            assert report.handlers[-1].status == "not_run"
        if mode == "script_pending":
            assert report.handlers[-1].children[1].status == "not_run"
    finally:
        if image is not None and image.accepted:
            assert image.close().accepted
        runtime.close()


@pytest.mark.parametrize("stage", ["module", "script"])
@pytest.mark.parametrize("stop", ["deadline", "cancelled"])
def test_real_prepared_process_stop_barriers(secure_test_root, monkeypatch, stage, stop):
    """Real workers stop before successors and settle exact processes and channels."""
    import asyncio
    import json
    import subprocess
    import threading
    import time
    from topsailai.hooks.configuration import HookLimits
    from topsailai.hooks.configured_contracts import SummaryPreparationRequest
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor
    from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
    from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration

    sources, root, _ = secure_test_root
    modules, scripts = sources / "modules", sources / "scripts"
    modules.mkdir(mode=0o700)
    scripts.mkdir(mode=0o700)
    trace = sources.parent / "stop-trace"
    module = modules / "first.py"
    module.write_text("import time\ndef main():\n" +
        f"    with open({str(trace)!r}, 'a') as stream:\n        stream.write('module\\n')\n" +
        ("    time.sleep(30)\n" if stage == "module" else "    return 'module'\n"))
    paths = [protocol_script(scripts / name, name, trace) for name in ("z", "A")]
    if stage == "script":
        first = scripts / "A"
        content = first.read_text()
        first.write_text(content.replace("result['value']", "import time\ntime.sleep(30)\nresult['value']", 1))
    settings = HookSettings(limits=HookLimits(dispatch_timeout_ms=5000))
    runtime, scope = helpers._runtime(sources, root, settings=settings)
    authorize(runtime, [module, *paths])
    declaration = HookPointDeclaration("hook__test__before__stop", EventDefinition(
        "hook__test__before__stop", 1), "before", "sync", "test")
    catalog = HookPointCatalog((declaration,))
    configuration = ConfiguredHooks((ConfiguredHookPoint(declaration.name,
        declaration.definition, module_folder=modules,
        script=ConfiguredScript(scripts, platform_policy=POLICY)),), settings)
    signal, finished = threading.Event(), threading.Event()
    processes, observed = [], []
    original_popen = subprocess.Popen
    def track_process(*args, **kwargs):
        """Retain exact process objects while preserving launch behavior."""
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process
    def cancel_when_started():
        """Use child-created readiness, not a fixed cancellation sleep."""
        deadline = time.monotonic() + 10
        while not finished.wait(0.01) and time.monotonic() < deadline:
            lines = trace.read_text().splitlines() if trace.exists() else []
            if lines == (["module"] if stage == "module" else ["module", "A"]):
                observed.extend(lines)
                signal.set()
                return
    watcher = None
    registrar = None
    try:
        registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope,
            SummaryPreparationRequest(configuration, catalog))
        assert registrar.dispositions[0].kind == "registered"
        executor = ConfiguredHookExecutor(runtime, scope, registrar, catalog)
        # Preparation probes are excluded: observe actual dispatch processes only.
        monkeypatch.setattr(subprocess, "Popen", track_process)
        if stop == "cancelled":
            watcher = threading.Thread(target=cancel_when_started)
            watcher.start()
        started = time.monotonic()
        if stop == "cancelled" and stage == "script":
            with pytest.raises(asyncio.CancelledError):
                executor.dispatch(declaration, payload={}, cancellation=signal)
        else:
            report = executor.dispatch(declaration, payload={}, cancellation=signal)
            assert report.unified_result.status == ("timeout" if stop == "deadline" else "cancelled")
            if stage == "module":
                assert report.unified_result.handlers[-1].status == "not_run"
            else:
                children = report.unified_result.handlers[-1].children
                assert children[0].status == "timeout"
                assert children[1].status == "not_run"
            assert report.unified_result.cleanup.state == "safe"
        assert time.monotonic() - started < 10
        expected = ["module"] if stage == "module" else ["module", "A"]
        assert trace.read_text().splitlines() == expected
        if stop == "cancelled":
            assert signal.is_set() and observed == expected
        assert len(processes) == (1 if stage == "module" else 2)
        assert all(process.poll() is not None for process in processes)
        assert all(stream is None or stream.closed for process in processes
                   for stream in (process.stdin, process.stdout, process.stderr))
        assert not runtime.cleanup_debts()
        print("PREPARED_REAL_STOP_EVIDENCE " + json.dumps({
            "stage": stage, "stop": stop, "trace": expected,
            "pids": [process.pid for process in processes],
            "exit_codes": [process.returncode for process in processes],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "cleanup_debts": 0, "channels_closed": True}))
    finally:
        finished.set()
        if watcher is not None:
            watcher.join(2)
            assert not watcher.is_alive()
        if registrar is not None:
            registrar.close()
        runtime.close()
