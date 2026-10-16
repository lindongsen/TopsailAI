"""Catalog-derived envelope layer regressions. Author: DawsonLin."""

import asyncio
from dataclasses import replace

import pytest

from topsailai.hooks.configured_executor import ConfiguredHookExecutor, HookOperation
from topsailai.hooks.contracts import EventDefinition, ValidationError
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.hooks.points.context.summary_contracts import SUMMARY_POINTS
from topsailai.hooks.points.context.summary_payloads import build_summary_payload
from topsailai.tests.unit.test_topsailai_hooks.test_configured_executor import (
    _Registrar, _Runtime, _Scope,
)
from topsailai.tests.unit.test_topsailai_hooks.test_runtime_dispatch import _runtime
from topsailai.tests.unit.test_topsailai_hooks.test_summary_hook_points import classification


@pytest.mark.parametrize("contract", SUMMARY_POINTS, ids=lambda point: point.name)
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_summary_envelope_uses_point_suffix(contract, mode):
    """Both waiting facades derive every checkpoint layer from its declaration."""
    point = replace(contract.declaration, mode=mode)
    runtime = _Runtime()
    registrar = _Registrar()
    executor = ConfiguredHookExecutor(runtime, _Scope(), registrar, HookPointCatalog((point,)))
    operation = HookOperation("envelope-1", "parent-1")
    payload = build_summary_payload(contract, operation_id=operation.operation_id,
                                    **classification(contract))
    if mode == "sync":
        report = executor.dispatch(point, payload=payload, operation=operation)
    else:
        report = asyncio.run(executor.adispatch(point, payload=payload, operation=operation))
    event, = runtime.events
    assert report.rejection_reason is None
    assert event.layer == contract.layer
    assert event.name == point.name
    assert event.major_version == payload["schema_version"]
    assert event.operation_id == operation.operation_id
    assert event.parent_operation_id == operation.parent_operation_id
    assert event.purpose == point.phase
    assert "layer" not in event.payload
    payload["outcome"] = "changed"
    assert event.payload["outcome"] == contract.outcome
    with pytest.raises(TypeError):
        event.payload["layer"] = "other"


@pytest.mark.parametrize("name,event_name,expected", [
    ("hook_legacy_user2agent", "legacy.summary_user2agent", "hooks"),
    ("hook_legacy_agent2llm", "legacy.summary_agent2llm", "hooks"),
    ("hook__billing__before__invoice_customer", "hook__billing__before__invoice_customer", "customer"),
    ("hook__billing__before__invoice", "hook__billing__before__invoice", "hooks"),
])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_layer_derivation_is_generic_and_legacy_compatible(name, event_name, expected, mode):
    """Legacy events retain hooks; generic unified actions need no summary catalog."""
    point = HookPointDeclaration(name, EventDefinition(event_name, 1, {"type": "object"}),
                                "before", mode, "test")
    runtime = _Runtime()
    executor = ConfiguredHookExecutor(runtime, _Scope(), _Registrar(), HookPointCatalog((point,)))
    if mode == "sync":
        executor.dispatch(point, payload={})
    else:
        asyncio.run(executor.adispatch(point, payload={}))
    assert runtime.events[0].layer == expected
    assert runtime.events[0].name == event_name


@pytest.mark.parametrize("contract", SUMMARY_POINTS, ids=lambda point: point.name)
@pytest.mark.parametrize("value", ["user2agent", "agent2llm", None])
def test_summary_payload_layer_never_selects_envelope(contract, value):
    """Even matching or null payload layer keys violate the strict point contract."""
    with pytest.raises(ValidationError):
        build_summary_payload(contract, operation_id="op-1", layer=value,
                              **classification(contract))


@pytest.mark.parametrize("layer", ["user2agent", "agent2llm"])
def test_executor_and_real_runtime_construct_derived_envelope(tmp_path, monkeypatch, layer):
    """Executor dispatch reaches a real Runtime event without an independent layer."""
    runtime, scope = _runtime(tmp_path)
    contract = next(point for point in SUMMARY_POINTS
                    if point.layer == layer and point.name.split("__")[2] == "before")
    executor = ConfiguredHookExecutor(runtime, scope, _Registrar(),
                                      HookPointCatalog((contract.declaration,)))
    captured = []
    original = runtime.make_event

    def capture(*args, **kwargs):
        """Observe the real immutable event without replacing construction."""
        event = original(*args, **kwargs)
        captured.append(event)
        return event

    monkeypatch.setattr(runtime, "make_event", capture)
    try:
        result = executor.dispatch(contract.declaration, payload=build_summary_payload(
            contract, operation_id="real-1"), operation=HookOperation("real-1"))
        event, = captured
        assert event.layer == layer
        assert event.name == contract.name
        assert event.operation_id == "real-1"
        assert "layer" not in event.payload
        assert result.event_id == event.event_id
    finally:
        runtime.close()
        assert not runtime._backend.cleanup_debts()
