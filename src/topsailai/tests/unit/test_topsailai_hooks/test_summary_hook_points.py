"""U3 catalog, point scaffolding, and operation checkpoint tests.

Author: DawsonLin
"""

from dataclasses import FrozenInstanceError
import importlib
import subprocess
import sys

import pytest

from topsailai.hooks.configured_executor import HookOperation
from topsailai.hooks.contracts import DispatchReport, ValidationError
from tests.summary_catalog_support import SUMMARY_CATALOG, create_summary_catalog
from tests.summary_catalog_support import PHASE_TWO_DECLARATIONS
from topsailai.hooks.points.context import SUMMARY_POINTS
from topsailai.hooks.points.context.summary_adapter import (
    DirectSummaryOperation, _CHECKPOINTS, summary_operation,
)
from topsailai.hooks.points.context.summary_payloads import validate_summary_payload


class Executor:
    """Capture exact dispatch arguments without registration or business code."""

    def __init__(self, callback=None):
        """Keep calls local to one test."""
        self.calls = []
        self.callback = callback
        self.report = DispatchReport("event", 0, rejection_reason="observer_rejected")

    def dispatch(self, point, *, payload, operation):
        """Record the call before optionally simulating observer behavior."""
        self.calls.append((point, payload, operation))
        if self.callback:
            self.callback()
        return self.report


@pytest.fixture(autouse=True)
def direct_recorder(monkeypatch):
    """Bind a local recorder to real point entries without the legacy adapter."""
    active = []
    original_init = Executor.__init__

    def initialize(self, callback=None):
        """Select the recorder created by the current test."""
        original_init(self, callback)
        active[:] = [self]

    monkeypatch.setattr(Executor, "__init__", initialize)
    for points in _CHECKPOINTS.values():
        for selected in points.values():
            def entry(*, operation_id, _selected=selected, **metadata):
                """Validate the actual payload and capture direct-entry arguments."""
                payload = _selected.build_payload(operation_id=operation_id, **metadata)
                return active[0].dispatch(_selected.POINT, payload=payload,
                                          operation=HookOperation(operation_id))
            monkeypatch.setattr(selected, selected.NAME, entry)


def classification(point):
    """Return only allowed bounded error metadata."""
    if point.outcome != "error":
        return {}
    result = dict(error_category="unknown", failed_stage=(
        "application_unknown" if point.is_apply_error else "generation_unknown"))
    if point.is_apply_error:
        result["partial_apply_possible"] = False
    return result


@pytest.mark.parametrize("point", SUMMARY_POINTS)
def test_point_package_and_builder(point):
    """All ten directories alias U2 rather than duplicating schema authority."""
    phase = point.name.split("__")[2]
    action = point.name.split("__")[3]
    package = importlib.import_module(f"topsailai.hooks.points.context.{phase}_{action}")
    assert package.NAME == point.name == point.definition.name
    assert package.POINT is point.declaration
    assert package.POINT.phase == point.outcome
    assert package.POINT.definition.major_version == 1
    assert package.POINT.definition.payload_limit_bytes == 8192
    payload = package.build_payload(operation_id="op-1", **classification(point))
    assert validate_summary_payload(point, payload, operation_id="op-1").to_payload() == payload
    assert "layer" not in payload
    with pytest.raises((TypeError, ValidationError)):
        package.build_payload(operation_id="op-1", layer=point.layer)


def test_explicit_catalog_and_exports():
    """Eight eligible points are catalog-owned; phase two is metadata only."""
    expected = {p.name for p in SUMMARY_POINTS if p.phase_one_eligible}
    assert {p.name for p in SUMMARY_CATALOG.declarations} == expected
    assert create_summary_catalog() == SUMMARY_CATALOG
    assert {p.name for p in PHASE_TWO_DECLARATIONS} == {p.name for p in SUMMARY_POINTS if not p.phase_one_eligible}
    for point in SUMMARY_POINTS:
        if point.phase_one_eligible:
            assert SUMMARY_CATALOG.require(point.name) == point.declaration
        else:
            with pytest.raises(KeyError):
                SUMMARY_CATALOG.require(point.name)


@pytest.mark.parametrize("layer", ["user2agent", "agent2llm"])
def test_operation_all_checkpoints(layer):
    """Same-layer checkpoints reuse one exact operation and valid payloads."""
    executor = Executor()
    session = DirectSummaryOperation(layer)
    assert len(session.operation.operation_id) == 32
    for point in SUMMARY_POINTS:
        if point.layer != layer or not point.phase_one_eligible:
            continue
        checkpoint = point.name.split("__")[2] + "_" + point.name.split("__")[3].rsplit("_", 1)[0]
        result = session.emit(checkpoint, **classification(point))
        assert result is executor.report
        declaration, payload, operation = executor.calls[-1]
        assert declaration is point.declaration
        assert operation.operation_id == session.operation.operation_id
        assert validate_summary_payload(point, payload, operation_id=operation.operation_id)
    assert len(executor.calls) == 4


@pytest.mark.parametrize("layer", [None, "", "other", True, [], "USER2AGENT"])
def test_invalid_layer(layer):
    """Malformed layers never reach dispatch."""
    executor = Executor()
    with pytest.raises(TypeError if isinstance(layer, list) else ValidationError):
        summary_operation(layer)
    assert not executor.calls


@pytest.mark.parametrize("checkpoint", [None, [], "", "after_summary_generate", "before_summary_generate_agent2llm", "hook__context__before__summary_generate_agent2llm", SUMMARY_POINTS[0].declaration])
def test_invalid_checkpoint(checkpoint):
    """Caller names, declarations, foreign layers, and phase two are not selectors."""
    executor = Executor()
    session = DirectSummaryOperation("user2agent")
    with pytest.raises(ValidationError):
        session.emit(checkpoint)
    assert not executor.calls


@pytest.mark.parametrize("operation", [HookOperation("x" * 129), HookOperation("with space"), HookOperation("unicode-é")])
def test_invalid_supplied_operation(operation):
    """Generic IDs cannot bypass the narrower U2 summary boundary."""
    executor = Executor()
    with pytest.raises(ValidationError):
        DirectSummaryOperation("user2agent", operation=operation).emit("before_summary_generate")
    assert not executor.calls


@pytest.mark.parametrize("checkpoint,metadata", [
    ("before_summary_generate", {"error_category": "unknown"}),
    ("error_summary_generate", {}),
    ("error_summary_generate", {"error_category": "persistence", "failed_stage": "generation_unknown"}),
    ("error_summary_apply", {"error_category": "unknown", "failed_stage": "runtime_rebuild", "partial_apply_possible": False}),
    ("error_summary_apply", {"error_category": "unknown", "failed_stage": "application_unknown"}),
])
def test_invalid_classification_does_not_consume(checkpoint, metadata):
    """Validation failures neither execute nor reserve a checkpoint."""
    executor = Executor()
    session = DirectSummaryOperation("user2agent")
    with pytest.raises(ValidationError):
        session.emit(checkpoint, **metadata)
    assert not executor.calls
    point = next(p for p in SUMMARY_POINTS if p.layer == "user2agent" and p.name == "hook__context__" + checkpoint.split("_", 1)[0] + "__" + checkpoint.split("_", 1)[1] + "_user2agent")
    assert session.emit(checkpoint, **classification(point)) is executor.report


def test_sequential_duplicates_and_independent_operations():
    """Duplicates validate before skipping; separate operations remain independent."""
    executor = Executor()
    operation = HookOperation("supplied-1")
    session = DirectSummaryOperation("user2agent", operation=operation)
    assert session.emit("before_summary_generate") is executor.report
    with pytest.raises(ValidationError):
        session.emit("before_summary_generate", error_category="invalid")
    duplicate = session.emit("before_summary_generate")
    assert duplicate.already_handled and duplicate.report is None
    with pytest.raises(FrozenInstanceError):
        duplicate.already_handled = False
    assert session.emit("after_summary_apply") is executor.report
    second = DirectSummaryOperation("user2agent")
    assert second.operation.operation_id != operation.operation_id
    assert second.emit("before_summary_generate") is executor.report
    assert len(executor.calls) == 3
    assert executor.calls[0][2].operation_id == operation.operation_id


def test_reentrant_duplicate_marked_before_dispatch():
    """Observer reentry finds the mark without deadlocking or executing again."""
    duplicates = []
    executor = Executor(lambda: duplicates.append(session.emit("before_summary_generate")))
    session = DirectSummaryOperation("agent2llm")
    session.emit("before_summary_generate")
    assert duplicates[0].already_handled
    assert len(executor.calls) == 1


@pytest.mark.parametrize("error", [RuntimeError("observer failure"), KeyboardInterrupt(), SystemExit()])
def test_entry_failure_never_emits_business_error(error):
    """Preserve failure identity and the checkpoint mark without recursion."""
    def fail():
        """Raise the exact observer or host signal."""
        raise error

    executor = Executor(fail)
    session = DirectSummaryOperation("user2agent")
    with pytest.raises(type(error)) as caught:
        session.emit("before_summary_generate")
    assert caught.value is error
    assert session.emit("before_summary_generate").already_handled
    assert len(executor.calls) == 1
    executor.callback = None
    session.emit("error_summary_generate", error_category="unknown", failed_stage="generation_unknown")
    assert len(executor.calls) == 2


def test_entry_result_does_not_emit_error():
    """Return observer reports unchanged; business classification is caller-owned."""
    executor = Executor()
    session = DirectSummaryOperation("user2agent")
    executor.report = ("error",)
    assert session.emit("before_summary_generate") is executor.report
    assert len(executor.calls) == 1


def test_imports_do_not_activate_execution(monkeypatch):
    """Reload composition under guards against runtime creation or dispatch."""
    import topsailai.hooks.configured_executor as executor_module
    import topsailai.hooks.configured_registration as registration_module
    import topsailai.hooks.runtime as runtime_module
    import tests.summary_catalog_support as catalog_module

    def forbidden(*args, **kwargs):
        """Fail immediately if metadata import attempts activation."""
        pytest.fail("point import attempted runtime activation")

    monkeypatch.setattr(runtime_module.HookRuntime, "__init__", forbidden)
    monkeypatch.setattr(runtime_module.HookScope, "__init__", forbidden)
    monkeypatch.setattr(registration_module.ConfiguredHookRegistrar, "__init__", forbidden)
    monkeypatch.setattr(registration_module.ConfiguredHookRegistrar, "ensure_registered", forbidden)
    monkeypatch.setattr(executor_module.ConfiguredHookExecutor, "__init__", forbidden)
    monkeypatch.setattr(executor_module.ConfiguredHookExecutor, "dispatch", forbidden)
    for point in SUMMARY_POINTS:
        phase = point.name.split("__")[2]
        action = point.name.split("__")[3]
        prefix = f"topsailai.hooks.points.context.{phase}_{action}"
        for suffix in (".point", ".payloads", ""):
            importlib.reload(importlib.import_module(prefix + suffix))
    catalog = importlib.reload(catalog_module)
    assert len(catalog.SUMMARY_CATALOG.declarations) == 8
    for point in catalog.PHASE_TWO_DECLARATIONS:
        with pytest.raises(KeyError):
            catalog.SUMMARY_CATALOG.require(point.name)


def test_fresh_business_imports_without_summary_catalog():
    """Fresh business imports neither load nor expose the removed aggregate."""
    code = """
import importlib
import importlib.util
import sys
import topsailai.hooks.points as points
importlib.import_module('topsailai.hooks.points.context.summary_adapter')
importlib.import_module('topsailai.hooks.points.workspace.before_input_message')
assert not hasattr(points, 'SUMMARY_CATALOG')
assert not hasattr(points, 'create_summary_catalog')
assert 'tests.summary_catalog_support' not in sys.modules
assert 'topsailai.hooks.points.catalog' not in sys.modules
assert importlib.util.find_spec('topsailai.hooks.points.catalog') is None
import topsailai.hooks.points.context as context
import topsailai.hooks.points.context.summary_adapter as adapter
for module in (context, adapter):
    for name in ('SummaryHookAdapter', 'SummaryHookOperation'):
        assert not hasattr(module, name)
        assert name not in module.__all__
assert context.SummaryCheckpointResult is adapter.SummaryCheckpointResult
assert 'tests.legacy_summary_adapter_support' not in sys.modules
print('fresh business imports OK; no Summary aggregate')
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fresh business imports OK" in result.stdout


@pytest.mark.parametrize("operation_id", ["x", "A_z-9" * 25 + "abc"])
def test_summary_operation_id_valid_boundaries(operation_id):
    """One-character and 128-character ASCII operation IDs remain supported."""
    executor = Executor()
    operation = HookOperation(operation_id)
    session = DirectSummaryOperation("agent2llm", operation=operation)
    session.emit("before_summary_generate")
    assert executor.calls[0][2].operation_id == operation.operation_id
    assert executor.calls[0][1]["operation_id"] == operation_id


def test_distinct_supplied_operation_ids_remain_independent():
    """Different direct operations retain independent checkpoint custody."""
    executor = Executor()
    for operation_id in ("first-operation", "second-operation"):
        operation = DirectSummaryOperation("user2agent", operation=HookOperation(operation_id))
        assert operation.emit("before_summary_generate") is executor.report
        assert operation.emit("before_summary_generate").already_handled
    assert [call[2].operation_id for call in executor.calls] == [
        "first-operation", "second-operation"]
