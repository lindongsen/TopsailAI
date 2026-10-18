"""Hook proposal decoding and non-consuming real probe. Author: DawsonLin."""
from dataclasses import replace

import pytest

from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.control_proposals import CONTROL_POINT, validated_proposals
from topsailai.ai_base.llm_control.request_control import REQUEST_CONTROL, RequestControl
from topsailai.hooks.result_contracts import (
    HandlerIdentity, HandlerResult, HookPointResult, ReturnedValue, ResultDiagnostic,
)


def envelope(value=None, *, kind="module", representation="direct", status="success", point=CONTROL_POINT):
    """Build a valid public envelope while varying the opaque returned data."""
    terminal = HandlerResult("e", point, 0, HandlerIdentity("s", "s", "default_script_hook"))
    handler = HandlerResult("e", point, 0, HandlerIdentity("m", "m", kind),
                            status=status, returned=ReturnedValue(True, representation, value))
    if kind == "script":
        terminal = replace(terminal, children=(handler,))
        return HookPointResult("e", point, 0, handlers=(terminal,))
    return HookPointResult("e", point, 0, handlers=(handler, terminal))


@pytest.fixture
def issued():
    """Issue one pending reference from an isolated real registry."""
    registry = RequestControl()
    t = AttemptTarget("b", 1, "i", "a")
    registry.bind(t)
    return registry, t, registry.submit(t, "c", "force_retry").proposal


@pytest.mark.parametrize("value", [None, False, {}, {"operation": "hard_interrupt"}, lambda: None])
def test_opaque_values_are_not_commands(issued, value):
    """No normalization or callback execution occurs on returned payloads."""
    registry, t, _ = issued
    assert validated_proposals(envelope(value), t, registry=registry) == ()


def test_no_opaque_property_access(issued):
    """Even hostile objects cannot execute properties during decoding."""
    class Hostile:
        """Fail if the decoder observes anything except exact type."""
        def __getattribute__(self, name):
            """Expose accidental duck typing as a test failure."""
            raise AssertionError("opaque property access")
    registry, t, _ = issued
    assert validated_proposals(envelope(Hostile()), t, registry=registry) == ()
    assert validated_proposals(Hostile(), t, registry=registry) == ()


def test_exact_provenance_duplicates_and_selection(issued):
    """Successful returns are candidates only, revalidated again on selection."""
    registry, t, p = issued
    result = envelope(p)
    duplicate = replace(result.handlers[0], handler=HandlerIdentity("m2", "m2", "module"))
    result = replace(result, handlers=(result.handlers[0], duplicate, result.handlers[-1]))
    assert validated_proposals(result, t, registry=registry) == (p,)
    assert registry.status("c").state == "queued"
    assert validated_proposals(envelope(replace(p)), t, registry=registry) == ()
    assert validated_proposals(envelope(p), replace(t, generation=2), registry=registry) == ()
    assert validated_proposals(envelope(p), None, registry=registry) == ()
    registry.select(t, p)
    assert validated_proposals(result, t, registry=registry) == ()


def test_wrong_result_channel_and_failure(issued):
    """Scripts, transported values, wrong points and errors confer no control."""
    registry, t, p = issued
    for result in (envelope(p, kind="script"), envelope(p, representation="transported"),
                   envelope(p, point="hook__llm__before__other")):
        assert validated_proposals(result, t, registry=registry) == ()
    result = envelope(p)
    module, terminal = result.handlers
    for returned in (ReturnedValue(), ReturnedValue(True, "direct", None)):
        changed = replace(result, handlers=(replace(module, returned=returned), terminal))
        assert validated_proposals(changed, t, registry=registry) == ()
    error = replace(module, status="error", returned=ReturnedValue(), error=ResultDiagnostic("failed", "failed"))
    changed = replace(result, status="completed_with_errors", handlers=(error, terminal))
    assert validated_proposals(changed, t, registry=registry) == ()
    assert validated_proposals(replace(result, status="timeout"), t, registry=registry) == ()


def test_real_direct_entry_probe_does_not_consume():
    """Framework reimports the real internal Module and preserves exact identity."""
    from topsailai.hooks.point_entry import execute_point
    from topsailai.hooks.points.llm.before_first_byte_wait_tick.modules.control_probe import main
    t = AttemptTarget("probe-test-route", 1, "probe-invocation", "probe-attempt")
    REQUEST_CONTROL.bind(t)
    try:
        p = REQUEST_CONTROL.submit(t, "probe-command", "hard_interrupt").proposal
        payload = dict(binding_id=t.binding_id, generation=t.generation,
                       invocation_id=t.invocation_id, attempt_id=t.attempt_id, phase="creating")
        assert main(**payload) is p
        result = execute_point(CONTROL_POINT, (), payload=payload)
        assert validated_proposals(result, t, registry=REQUEST_CONTROL) == (p,)
        assert REQUEST_CONTROL.status("probe-command").state == "queued"
        assert main(**payload) is p
    finally:
        REQUEST_CONTROL.retire(t)
