"""Heavy-task Hook Point declaration, payload and event contract tests.

Author: DawsonLin
"""

import importlib.util
from pathlib import Path

import pytest

import topsailai.events as events
import topsailai.hooks as hooks
from topsailai.hooks.hook_point_catalog import HookPointCatalog
from topsailai.hooks.points.workspace.after_heavy_task_warning import (
    hook__workspace__after__heavy_task_warning as warn,
)
from topsailai.hooks.points.workspace.after_heavy_task_warning.point import (
    NAME as WARN_NAME,
    POINT as WARN_POINT,
)
from topsailai.hooks.points.workspace.after_heavy_task_warning.payloads import (
    build_payload as build_warning,
)
from topsailai.hooks.points.workspace.error_heavy_task_terminated import (
    hook__workspace__error__heavy_task_terminated as terminate,
)
from topsailai.hooks.points.workspace.error_heavy_task_terminated.point import (
    NAME as TERM_NAME,
    POINT as TERM_POINT,
)
from topsailai.hooks.points.workspace.error_heavy_task_terminated.payloads import (
    build_payload as build_terminated,
)

WARNING = {"schema_version": 1, "continuous_summary_times": 6, "threshold": 5}
TERMINATED = {
    "schema_version": 1, "continuous_summary_times": 12,
    "threshold": 5, "fatal_offset": 7,
}
POINTS_ROOT = Path(hooks.__file__).parent / "points" / "workspace"


@pytest.fixture(autouse=True)
def isolated_points():
    """Restore the process-wide point snapshot around every test."""
    hooks.initialize_hook_points({})
    yield
    hooks.initialize_hook_points({})


def load_module(point_folder):
    """Import one bundled Module file exactly as the framework does."""
    path = POINTS_ROOT / point_folder / "modules" / "record_event.py"
    spec = importlib.util.spec_from_file_location(f"probe_{point_folder}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_declarations_validate_and_join_one_catalog():
    """Both points satisfy the declaration contract and stay distinct."""
    catalog = HookPointCatalog((WARN_POINT, TERM_POINT))
    assert len(catalog.declarations) == 2
    assert WARN_POINT.phase == "success"
    assert TERM_POINT.phase == "error"
    assert WARN_POINT.owner == TERM_POINT.owner == "workspace.heavy_task"
    assert WARN_POINT.failure_policy == TERM_POINT.failure_policy == "report"


def test_declared_names_match_directory_layout():
    """The name segments must resolve to the on-disk point directory."""
    assert WARN_NAME == "hook__workspace__after__heavy_task_warning"
    assert TERM_NAME == "hook__workspace__error__heavy_task_terminated"
    assert WARN_POINT.definition.name == WARN_NAME
    assert TERM_POINT.definition.name == TERM_NAME
    assert (POINTS_ROOT / "after_heavy_task_warning").is_dir()
    assert (POINTS_ROOT / "error_heavy_task_terminated").is_dir()


@pytest.mark.parametrize("builder,payload", [
    (build_warning, WARNING),
    (build_terminated, TERMINATED),
])
def test_payload_builder_returns_detached_metadata(builder, payload):
    """A valid payload is accepted and returned as an independent copy."""
    result = builder(dict(payload))
    assert result == payload
    assert result is not payload


@pytest.mark.parametrize("builder,payload", [
    (build_warning, WARNING),
    (build_terminated, TERMINATED),
])
@pytest.mark.parametrize("mutation", [
    lambda value: {key: item for key, item in value.items() if key != "threshold"},
    lambda value: {**value, "unexpected": 1},
    lambda value: {**value, "schema_version": 2},
    lambda value: {**value, "threshold": True},
    lambda value: {**value, "threshold": -1},
    lambda value: {**value, "threshold": "5"},
    lambda value: {**value, "continuous_summary_times": None},
])
def test_payload_builder_rejects_invalid_metadata(builder, payload, mutation):
    """Missing, unknown and wrongly typed fields are all rejected."""
    with pytest.raises(ValueError):
        builder(mutation(dict(payload)))


def test_payload_builder_rejects_non_mapping():
    """A non-dict payload never reaches schema validation."""
    with pytest.raises(ValueError):
        build_warning([("schema_version", 1)])
    with pytest.raises(ValueError):
        build_terminated("not-a-mapping")


@pytest.mark.parametrize("folder,payload,event_type,source", [
    ("after_heavy_task_warning", WARNING, "heavy_task.warning",
     "hooks.heavy_task_warning"),
    ("error_heavy_task_terminated", TERMINATED, "heavy_task.terminated",
     "hooks.heavy_task_terminated"),
])
def test_module_records_one_exact_event(folder, payload, event_type, source,
                                        monkeypatch):
    """The bundled Module records exactly one documented event."""
    module = load_module(folder)
    calls = []
    monkeypatch.setattr(module, "record_event", lambda **kwargs: calls.append(kwargs))
    assert module.main(**payload) == {"recorded": True}
    assert calls == [{"event_type": event_type, "source": source,
                      "payload": payload, "flush": True}]


@pytest.mark.parametrize("folder,payload", [
    ("after_heavy_task_warning", WARNING),
    ("error_heavy_task_terminated", TERMINATED),
])
def test_module_recording_failure_is_isolated(folder, payload, monkeypatch):
    """A recording failure reports False and never raises into the agent turn."""
    module = load_module(folder)

    def explode(**kwargs):
        """Simulate a backend failure."""
        raise RuntimeError("backend down")

    monkeypatch.setattr(module, "record_event", explode)
    assert module.main(**payload) == {"recorded": False}


@pytest.mark.parametrize("call,payload,event_type,source", [
    (warn, WARNING, "heavy_task.warning", "hooks.heavy_task_warning"),
    (terminate, TERMINATED, "heavy_task.terminated",
     "hooks.heavy_task_terminated"),
])
def test_named_function_dispatches_bundled_module(call, payload, event_type,
                                                  source, monkeypatch):
    """The named function validates then dispatches the bundled recorder.

    The framework imports the Module file fresh on every dispatch, so patching
    the source module attribute is what the fresh import observes.
    """
    calls = []
    monkeypatch.setattr(events, "record_event", lambda **kwargs: calls.append(kwargs))
    result = call(**payload)
    assert result.status == "success"
    assert calls == [{"event_type": event_type, "source": source,
                      "payload": payload, "flush": True}]


@pytest.mark.parametrize("call", [
    lambda: warn(schema_version=1),
    lambda: terminate(schema_version=1, continuous_summary_times=12),
])
def test_named_function_never_raises_on_invalid_payload(call):
    """Invalid caller metadata is reported, never raised into business code."""
    assert call() is None
