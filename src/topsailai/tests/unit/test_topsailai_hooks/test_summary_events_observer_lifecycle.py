"""Explicit configured observer lifecycle regressions. Author: DawsonLin."""

import importlib
import json
import os
import shutil
from pathlib import Path

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks, ConfiguredTrustPolicy, HookSettings
from topsailai.hooks.configuration import HookLimits
from topsailai.hooks.configured_contracts import ConfiguredPreparationRequest
from topsailai.hooks.configured_executor import ConfiguredHookExecutor, HookOperation
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
from topsailai.hooks.contracts import ValidationError
from tests.summary_catalog_support import SUMMARY_CATALOG, PHASE_ONE_DECLARATIONS, PHASE_TWO_DECLARATIONS
from tests.legacy_summary_adapter_support import LegacySummaryHookAdapter
from topsailai.hooks.points.context.summary_contracts import SUMMARY_POINTS
from tests.legacy_prepared_support import build_summary_preparation_request
from topsailai.tests.unit.test_topsailai_hooks.test_configured_preparation import _runtime, _assertion
from topsailai.tests.unit.test_topsailai_hooks.test_summary_hook_points import classification

OBSERVER = Path(__file__).resolve().parents[3] / "hooks/points/context/summary_events_observer"
POINTS_ROOT = OBSERVER.parent
ACTIVE = tuple(point for point in SUMMARY_POINTS if point.phase_one_eligible)
# Observed 1091ms censored plan; 2x rounded headroom, two Modules plus terminal.
FUNCTIONAL_SETTINGS = HookSettings(limits=HookLimits(
    handler_timeout_ms=2250, dispatch_timeout_ms=4750))


def configuration(points_root=None):
    """Opt in only the eight exact Catalog-owned definitions, without scripts."""
    return build_summary_preparation_request(points_root=points_root, settings=FUNCTIONAL_SETTINGS).configuration


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    """Own a private runtime and explicitly pin the real observer source."""
    for name in tuple(os.environ):
        if name.startswith("TOPSAILAI_EVENTS_"):
            monkeypatch.delenv(name)
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    points = tmp_path / "points"
    for point in configuration().hook_points:
        shutil.copytree(point.module_folder, points / point.module_folder.parent.name / "modules",
            ignore=shutil.ignore_patterns("__pycache__"))
    runtime, scope = _runtime(points, root, settings=FUNCTIONAL_SETTINGS)
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        closure_assertions=tuple(_assertion(source, source.stem)
            for point in configuration(points).hook_points
            for source in sorted(point.module_folder.glob("*.py"))),
        python_runtime=trust.python_runtime)
    try:
        yield runtime, scope, root
    finally:
        runtime.close()
        assert not runtime._backend.cleanup_debts()


def prepare(lifecycle, config=None, disabled=frozenset()):
    """Use the real prepared pipeline with a test-only legacy bridge."""
    runtime, scope, _ = lifecycle
    request = ConfiguredPreparationRequest(configuration=config if config is not None else configuration(lifecycle[2].parent / "points"),
        catalog=SUMMARY_CATALOG, disabled_hook_names=disabled)
    registrar = ConfiguredHookRegistrar.from_prepared(runtime, scope, request)
    executor = ConfiguredHookExecutor(runtime, scope, registrar, SUMMARY_CATALOG)
    return registrar, executor, LegacySummaryHookAdapter(executor)


def emit(adapter, point, identity="lifecycle-1"):
    """Deliver a valid checkpoint through the test bridge and real executor."""
    checkpoint = point.name.split("__")[2] + "_" + point.name.split("__")[3].rsplit("_", 1)[0]
    return adapter.begin(point.layer, operation=HookOperation(identity)).emit(
        checkpoint, **classification(point))


def events(lifecycle):
    """Inspect actual JSONL files written by isolated workers, not recorder mocks."""
    result = []
    for path in lifecycle[2].rglob("*.events"):
        result.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    return [event for event in result if event["event_type"] == "summary.hook.observed"]


def report_evidence(report):
    """Bound framework diagnostics without inspecting plugin return values."""
    unified = report.unified_result
    evidence = {
        "elapsed_ms": report.elapsed_ms, "deadline_exhausted": report.deadline_exhausted,
        "rejection_reason": report.rejection_reason, "remaining_budget_ms": "unknown",
        "handlers": [] if unified is None else [{
            "name": item.handler.name[:128], "status": item.status,
            "not_run_reason": item.not_run_reason,
            "category": None if item.error is None else item.error.category,
            "elapsed_ms": item.timing.elapsed_ms, "cleanup": item.cleanup.state,
            "cleanup_category": None if item.cleanup.diagnostic is None else item.cleanup.diagnostic.category,
            "returned_present": item.returned.present,
            "returned_representation": item.returned.representation,
        } for item in unified.handlers[:16]],
        "handler_count": 0 if unified is None else len(unified.handlers),
    }
    print("HOOK_REPORT_EVIDENCE " + json.dumps(evidence, sort_keys=True))
    return evidence


def assert_recorded(result, recorded=True):
    """Require the transported observer acknowledgement and successful isolation."""
    assert result.report.rejection_reason is None, report_evidence(result.report)
    handlers = [item for item in result.report.unified_result.handlers if item.handler.kind == "module"]
    observers = [item for item in handlers if item.handler.name == result.report.unified_result.hook_point_name + ":observer"]
    assert len(observers) == 1, report_evidence(result.report)
    assert observers[0].status == "success", report_evidence(result.report)
    assert observers[0].returned.value == {"recorded": recorded}, report_evidence(result.report)


def test_all_eight_points_emit_real_safe_events(lifecycle):
    """Explicit preparation captures and executes the real observer for every point."""
    registrar, _, adapter = prepare(lifecycle)
    assert len(registrar.dispositions) == 8
    assert all(item.kind == "registered" for item in registrar.dispositions), registrar.dispositions
    config = configuration()
    assert [item.hook_name for item in config.hook_points] == [p.name for p in PHASE_ONE_DECLARATIONS]
    for item in config.hook_points:
        assert item.inject_hook_context
        assert item.module_folder == POINTS_ROOT / item.hook_name.removeprefix("hook__context__").replace("__", "_") / "modules"
        assert item.script is None and not item.module_args and not item.module_kwargs
    for point in ACTIVE:
        before = len(events(lifecycle))
        assert_recorded(emit(adapter, point))
        observed = events(lifecycle)
        assert len(observed) == before + 1
        event = next(event for event in observed if event["payload"]["point_name"] == point.name)
        assert event["source"] == "hooks.summary_events_observer"
        assert set(event["payload"]) == point.allowed_fields
        assert event["payload"]["operation_id"] == "lifecycle-1"
        assert event["payload"]["schema_version"] == 1
        assert event["payload"]["outcome"] == point.outcome
        assert str(OBSERVER) not in json.dumps(event["payload"])
    assert len(events(lifecycle)) == 8


@pytest.mark.parametrize("point", PHASE_TWO_DECLARATIONS, ids=lambda point: point.name)
def test_phase_two_not_configured_or_emitted(lifecycle, point):
    """Inactive configuration is rejected before observer discovery or dispatch."""
    assert point.name not in {p.hook_name for p in configuration().hook_points}
    config = ConfiguredHooks((ConfiguredHookPoint(point.name, point.definition,
        module_folder=OBSERVER, inject_hook_context=True),), FUNCTIONAL_SETTINGS)
    registrar, executor, adapter = prepare(lifecycle, config)
    assert registrar.dispositions[0].reason == "catalog_rejected"
    with pytest.raises(KeyError):
        executor.dispatch(point, payload={}, operation=HookOperation("inactive"))
    with pytest.raises(ValidationError):
        adapter.begin("user2agent").emit("after_summary_generate")
    assert events(lifecycle) == []


@pytest.mark.parametrize("disabled", [False, True])
def test_unconfigured_and_disabled_do_not_emit(lifecycle, disabled):
    """Importing packages never enables an empty or explicitly disabled request."""
    runtime, _, _ = lifecycle
    generation = runtime._registry.generation
    importlib.import_module("topsailai.hooks.points.context.summary_events_observer")
    importlib.import_module("topsailai.workspace.agent_shell")
    assert runtime._registry.generation == generation
    config = configuration() if disabled else ConfiguredHooks((), FUNCTIONAL_SETTINGS)
    names = frozenset(point.name for point in PHASE_ONE_DECLARATIONS) if disabled else frozenset()
    _, _, adapter = prepare(lifecycle, config, names)
    result = emit(adapter, ACTIVE[0])
    assert result.report.rejection_reason is not None
    assert events(lifecycle) == []


def test_standard_agent_chat_construction_does_not_enable_observer(tmp_path, monkeypatch):
    """Construct the real ordinary chat without summary configuration or model I/O."""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from topsailai.events import EventCollector, EventConfig
    from topsailai.events import collector as event_module
    from topsailai.workspace import agent_shell, hook_instruction
    from topsailai.workspace.plugin_instruction.base import cache

    path = tmp_path / "standard-chat.events"
    collector = EventCollector(EventConfig(file_path=str(path), retention_days=0))
    monkeypatch.setattr(event_module, "_collector_instance", collector)
    monkeypatch.setattr(cache, "g_ai_agent", None)
    monkeypatch.setattr(hook_instruction, "FILE_INPUT_COMPLETIONS", str(tmp_path / "completions"))
    monkeypatch.setattr(hook_instruction.HookInstruction, "setup_readline_completion", Mock())
    agent = SimpleNamespace(runtime=SimpleNamespace(llm_model=SimpleNamespace(
        max_tokens=3000, temperature=0.3)), hooks_after_init_prompt=[],
        hooks_after_new_session=[], hooks_pre_chat=[], messages=[],
        run=Mock(side_effect=AssertionError("LLM conversation must not start")))
    factory = Mock(return_value=agent)
    monkeypatch.setattr(agent_shell, "get_ai_agent", factory)
    monkeypatch.setattr(agent_shell, "get_message", Mock(return_value=""))
    for name in ("record_project_history", "create_session_meta", "cleanup_session_meta_files"):
        monkeypatch.setattr(agent_shell, name, Mock())
    try:
        chat = agent_shell.get_agent_chat(system_prompt="isolated construction", session_id="",
            agent_name="observer-regression", message="do not run", need_input_message=False,
            need_print_session=False, need_project_workspace_lock=False,
            need_set_agent_name_to_thread_local=False)
        assert isinstance(chat, agent_shell.AgentChat)
        factory.assert_called_once()
        assert not hasattr(chat.ctx_runtime_data, "summary_hooks_executor")
        assert chat.control_server is None
        agent.run.assert_not_called()
        collector.record("test.collector.ready", payload={}, flush=True)
        observed = [json.loads(line) for line in path.read_text().splitlines()]
        assert any(event["event_type"] == "test.collector.ready" for event in observed)
        assert not any(event["event_type"] == "summary.hook.observed" for event in observed)
    finally:
        collector.close()


def test_legacy_module_still_usable_without_observer(lifecycle, tmp_path):
    """An explicit legacy module retains its original static invocation contract."""
    runtime, _, _ = lifecycle
    folder = tmp_path / "legacy"
    folder.mkdir(mode=0o700)
    source = folder / "legacy.py"
    source.write_text("def main(value):\n    return value\n")
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy((folder,),
        closure_assertions=(_assertion(source, "legacy"),), python_runtime=trust.python_runtime)
    point = ACTIVE[0]
    config = ConfiguredHooks((ConfiguredHookPoint(point.name, point.definition,
        module_folder=folder, module_args=("legacy",)),), FUNCTIONAL_SETTINGS)
    _, _, adapter = prepare(lifecycle, config)
    result = emit(adapter, point)
    assert result.report.unified_result.handlers[0].returned.value == "legacy", report_evidence(result.report)
    assert events(lifecycle) == []


def test_checkpoint_idempotency_and_distinct_identity(lifecycle):
    """Adapter-wide identity custody suppresses duplicates but permits new operations."""
    _, _, adapter = prepare(lifecycle)
    assert_recorded(emit(adapter, ACTIVE[0], "same"))
    duplicate = emit(adapter, ACTIVE[0], "same")
    assert duplicate.already_handled and duplicate.report is None
    assert len(events(lifecycle)) == 1
    assert_recorded(emit(adapter, ACTIVE[0], "distinct"))
    assert {event["payload"]["operation_id"] for event in events(lifecycle)} == {"same", "distinct"}


@pytest.mark.parametrize("field", ["layer", "path", "messages", "history", "session", "config",
    "environment", "credentials", "exception", "traceback"])
def test_sensitive_payload_rejected_at_lifecycle_boundary(lifecycle, field):
    """Representative nonempty secrets cannot cross configured payload validation."""
    _, executor, _ = prepare(lifecycle)
    point = ACTIVE[0]
    payload = {"schema_version": 1, "operation_id": "unsafe", "point_name": point.name,
        "outcome": point.outcome, field: "/private/path token=secret message history"}
    with pytest.raises(ValidationError):
        executor.dispatch(SUMMARY_CATALOG.require(point.name), payload=payload,
            operation=HookOperation("unsafe"))
    assert events(lifecycle) == []


def test_recorder_exception_isolated_in_real_worker(lifecycle, tmp_path, monkeypatch):
    """Inject only a child recorder failure while retaining real captured delivery."""
    runtime, _, _ = lifecycle
    _, _, adapter = prepare(lifecycle)
    injection = tmp_path / "child-injection"
    injection.mkdir(mode=0o700)
    (injection / "sitecustomize.py").write_text(
        "import topsailai.events, logging\n"
        "logging.getLogger().addHandler(logging.StreamHandler())\n"
        "logging.getLogger().setLevel(logging.WARNING)\n"
        "def fail(**kwargs):\n"
        "    raise RuntimeError('/private/path token=secret recorder failure')\n"
        "topsailai.events.record_event = fail\n")
    original = runtime._backend._worker_environment
    received = []
    execute = runtime._backend.execute_captured_module

    def environment():
        """Add a test-only startup injection without propagating event settings."""
        values = original()
        values["PYTHONPATH"] = str(injection) + os.pathsep + values["PYTHONPATH"]
        return values

    def capture(*args, **kwargs):
        """Observe the unchanged backend result and worker stderr for leak checks."""
        result = execute(*args, **kwargs)
        received.append(result)
        return result

    monkeypatch.setattr(runtime._backend, "_worker_environment", environment)
    monkeypatch.setattr(runtime._backend, "execute_captured_module", capture)
    assert_recorded(emit(adapter, ACTIVE[0]), recorded=False)
    assert received and all(item.cleanup_confirmed for item in received)
    stderr = b"".join(item.stderr for item in received)
    assert b"summary_hook_event_record_failed" in stderr
    assert b"token=secret" not in stderr
    assert b"/private/path" not in stderr
    assert b"Traceback" not in stderr
    assert events(lifecycle) == []


def test_observer_assertions_allow_additional_point_member(lifecycle):
    """Adding a member needs no change to shared observer acknowledgement assertions."""
    runtime, _, root = lifecycle
    folder = configuration(root.parent / "points").hook_points[0].module_folder
    source = folder / "additional.py"
    source.write_text("def main(*, hook_context):\n    return False\n")
    trust = runtime._configured_trust
    runtime._configured_trust = ConfiguredTrustPolicy(trust.source_roots,
        closure_assertions=trust.closure_assertions + (_assertion(source, source.stem),),
        python_runtime=trust.python_runtime)
    _, _, adapter = prepare(lifecycle)
    result = emit(adapter, ACTIVE[0], "additional-member")
    assert_recorded(result)
    names = [item.handler.name for item in result.report.unified_result.handlers]
    assert ACTIVE[0].name + ":additional" in names and names[-1] == "hook_script"
    additional = next(item for item in result.report.unified_result.handlers
        if item.handler.name == ACTIVE[0].name + ":additional")
    assert additional.status == "success", additional
    assert additional.returned.present and additional.returned.value is False
    assert len(events(lifecycle)) == 1
