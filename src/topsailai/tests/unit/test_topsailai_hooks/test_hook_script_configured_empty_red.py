"""RED contracts for configured accepted-empty hook_script settlement metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import topsailai.hooks as hooks
from topsailai.hooks import (
    Binding,
    HookScriptDiscoveryResult,
    HookScriptEntry,
    build_hook_point_binding_plan_from_discovery,
    hook_script_ready,
    settle_unconfigured_hook_script,
)

_MISSING_API = "configured-empty settlement API missing: settle_configured_empty_hook_script"
_HOOK_POINT = "conversation.started"


def _settlement_api():
    """Return the proposed public API after one attributable RED assertion."""
    api = getattr(hooks, "settle_configured_empty_hook_script", None)
    assert callable(api), _MISSING_API
    return api


def _module_binding(
    name: str = "alpha",
    *,
    binding_id: str | None = None,
    requires_success: tuple[str, ...] = (),
) -> Binding:
    """Build one public in-memory module binding."""
    return Binding(
        binding_id=binding_id or f"module:{name}",
        event_name=_HOOK_POINT,
        event_version=1,
        handler_ref=f"fixtures.{name}:main",
        requires_success=requires_success,
    )


def _bridge(
    discovery_result: Any,
    *,
    hook_point: Any = _HOOK_POINT,
    module_bindings: Any = (),
    bindings_per_event: Any = 1,
):
    """Build the corresponding configured terminal plan through the public bridge."""
    return build_hook_point_binding_plan_from_discovery(
        hook_point=hook_point,
        module_bindings=module_bindings,
        bindings_per_event=bindings_per_event,
        hook_script_configured=True,
        discovery_result=discovery_result,
    )


def _settle(
    api,
    discovery_result: Any,
    *,
    hook_point: Any = _HOOK_POINT,
    module_bindings: Any = (),
    bindings_per_event: Any = 1,
):
    """Invoke the proposed result constructor with matching public planning inputs."""
    return api(
        hook_point=hook_point,
        module_bindings=module_bindings,
        bindings_per_event=bindings_per_event,
        discovery_result=discovery_result,
    )


def _assert_settlement(outcome: Any, status: str, error_category: str | None) -> None:
    """Require the complete fixed metadata-only settlement record."""
    assert outcome.status == status
    assert outcome.error_category == error_category
    assert outcome.entry_results == ()
    assert outcome.started is False


def test_configured_accepted_empty_settles_as_successful_zero_work() -> None:
    """Accepted empty discovery produces exact successful not-started metadata."""
    api = _settlement_api()
    discovery = HookScriptDiscoveryResult(True)
    original = discovery
    plan = _bridge(discovery)

    assert plan.accepted is True
    assert len(plan.bindings) == 1
    assert plan.bindings[-1].configured is True
    assert plan.bindings[-1].entries == ()

    outcome = _settle(api, discovery)

    _assert_settlement(outcome, "success", None)
    assert discovery is original
    assert discovery == HookScriptDiscoveryResult(True)


def test_configured_accepted_nonempty_is_rejected_without_execution() -> None:
    """Accepted pending entries cannot be reported as successful empty work."""
    api = _settlement_api()
    entries = (HookScriptEntry(Path("/in-memory/hook"), "hook"),)
    discovery = HookScriptDiscoveryResult(True, entries=entries)
    plan = _bridge(discovery)

    assert plan.accepted is True
    assert plan.bindings[-1].entries == entries

    outcome = _settle(api, discovery)

    _assert_settlement(outcome, "error", "hook_script_nonempty_entries")
    assert discovery.entries is entries
    assert discovery == HookScriptDiscoveryResult(True, entries=entries)


def test_rejected_discovery_preserves_plan_diagnostics_and_rejects_settlement() -> None:
    """An explicit discovery rejection remains visible and never becomes success."""
    api = _settlement_api()
    errors = ("configured target rejected",)
    discovery = HookScriptDiscoveryResult(False, errors=errors)
    plan = _bridge(discovery)

    assert plan.accepted is False
    assert plan.bindings == ()
    assert plan.errors is errors

    outcome = _settle(api, discovery)

    _assert_settlement(outcome, "error", "hook_script_plan_rejected")
    assert discovery.errors is errors


def test_invalid_discovery_states_return_plan_rejection_without_mutation() -> None:
    """Malformed, missing, and contradictory discovery metadata fail closed."""
    api = _settlement_api()
    entry = HookScriptEntry(Path("/in-memory/hook"), "hook")
    candidates = (
        None,
        object(),
        HookScriptDiscoveryResult(accepted=1),
        HookScriptDiscoveryResult(True, entries=[]),
        HookScriptDiscoveryResult(True, entries=("invalid",)),
        HookScriptDiscoveryResult(False, errors=[]),
        HookScriptDiscoveryResult(False, errors=(1,)),
        HookScriptDiscoveryResult(True, errors=("unexpected",)),
        HookScriptDiscoveryResult(False, entries=(entry,), errors=("rejected",)),
        HookScriptDiscoveryResult(False),
    )

    for candidate in candidates:
        before = repr(candidate)
        outcome = _settle(api, candidate)

        _assert_settlement(outcome, "error", "hook_script_plan_rejected")
        assert repr(candidate) == before


def test_invalid_planning_inputs_return_plan_rejection() -> None:
    """The constructor reuses public planning validation without partial success."""
    api = _settlement_api()
    discovery = HookScriptDiscoveryResult(True)
    cases = (
        {"hook_point": ""},
        {"module_bindings": []},
        {"bindings_per_event": 0},
        {"module_bindings": (_module_binding(binding_id="hook_script"),), "bindings_per_event": 2},
        {
            "module_bindings": (
                _module_binding(requires_success=("module:earlier",)),
            ),
            "bindings_per_event": 2,
        },
    )

    for overrides in cases:
        arguments = {
            "hook_point": _HOOK_POINT,
            "module_bindings": (),
            "bindings_per_event": 1,
        }
        arguments.update(overrides)
        plan = _bridge(discovery, **arguments)
        assert plan.accepted is False
        assert plan.bindings == ()

        outcome = _settle(api, discovery, **arguments)
        _assert_settlement(outcome, "error", "hook_script_plan_rejected")


def test_readiness_remains_caller_owned_for_configured_empty_metadata() -> None:
    """Settlement construction neither checks nor publishes predecessor readiness."""
    api = _settlement_api()
    discovery = HookScriptDiscoveryResult(True)
    modules = (_module_binding(),)
    plan = _bridge(discovery, module_bindings=modules, bindings_per_event=2)
    terminal = plan.bindings[-1]

    assert plan.accepted is True
    assert hook_script_ready(terminal, {}) is False
    assert hook_script_ready(terminal, {"module:alpha": "cleanup_pending"}) is False
    assert hook_script_ready(terminal, {"module:alpha": "error"}) is True

    before = plan
    outcome = _settle(
        api,
        discovery,
        module_bindings=modules,
        bindings_per_event=2,
    )

    _assert_settlement(outcome, "success", None)
    assert plan is before
    assert not hasattr(outcome, "published")
    assert not hasattr(outcome, "ready")


def test_configured_entry_is_separate_from_unchanged_legacy_settlement() -> None:
    """The new constructor does not broaden or replace legacy unconfigured behavior."""
    api = _settlement_api()
    entry = HookScriptEntry(Path("/in-memory/hook"), "hook")
    configured_empty = _bridge(HookScriptDiscoveryResult(True)).bindings[-1]
    configured_nonempty = _bridge(
        HookScriptDiscoveryResult(True, entries=(entry,))
    ).bindings[-1]
    unconfigured_empty = hooks.HookScriptBinding(
        binding_id="hook_script",
        hook_point=_HOOK_POINT,
        priority=2_147_483_647,
        after=(),
        framework_owned=True,
        terminal=True,
        configured=False,
    )
    unconfigured_nonempty = hooks.HookScriptBinding(
        binding_id="hook_script",
        hook_point=_HOOK_POINT,
        priority=2_147_483_647,
        after=(),
        framework_owned=True,
        terminal=True,
        configured=False,
        entries=(entry,),
    )

    _assert_settlement(
        settle_unconfigured_hook_script(configured_empty),
        "error",
        "hook_script_not_unconfigured",
    )
    _assert_settlement(
        settle_unconfigured_hook_script(configured_nonempty),
        "error",
        "hook_script_not_unconfigured",
    )
    _assert_settlement(settle_unconfigured_hook_script(unconfigured_empty), "success", None)
    _assert_settlement(
        settle_unconfigured_hook_script(unconfigured_nonempty),
        "error",
        "hook_script_nonempty_entries",
    )
    _assert_settlement(_settle(api, None), "error", "hook_script_plan_rejected")
