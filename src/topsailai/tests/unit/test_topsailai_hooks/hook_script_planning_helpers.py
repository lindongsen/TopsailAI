"""Helpers for the future static-discovery to terminal-plan bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from topsailai.hooks import (
    Binding,
    HookScriptDiscoveryResult,
    HookScriptEntry,
)


MISSING_CONTRACT = (
    "R7 hook_script planning bridge contract missing: "
    "build_hook_point_binding_plan_from_discovery"
)


def require_planning_bridge() -> Callable[..., Any]:
    """Return the future pure planning API or fail explicitly in the test body."""
    try:
        from topsailai.hooks.hook_script import (
            build_hook_point_binding_plan_from_discovery,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        raise AssertionError(MISSING_CONTRACT) from exc
    assert callable(build_hook_point_binding_plan_from_discovery), MISSING_CONTRACT
    return build_hook_point_binding_plan_from_discovery


def module_binding(module_name: str, **changes: object) -> Binding:
    """Build one discovered module binding for bridge planning controls."""
    from dataclasses import replace

    binding = Binding(
        binding_id=f"module:{module_name}",
        event_name="conversation.started",
        event_version=1,
        handler_ref=f"discovered.{module_name}:main",
    )
    return replace(binding, **changes)


def accepted_discovery(*names: str, root: Path) -> HookScriptDiscoveryResult:
    """Build one accepted immutable discovery result in caller-provided order."""
    entries = tuple(
        HookScriptEntry(source_path=(root / name).resolve(), basename=name)
        for name in names
    )
    return HookScriptDiscoveryResult(True, entries=entries)


def rejected_discovery(error: str = "hook_script target is invalid") -> HookScriptDiscoveryResult:
    """Build one atomically rejected discovery result with no entries."""
    return HookScriptDiscoveryResult(False, errors=(error,))


def build_plan(
    discovery_result: HookScriptDiscoveryResult | None,
    *,
    modules: tuple[Binding, ...] = (),
    configured: bool = True,
    capacity: int = 8,
) -> Any:
    """Invoke the future bridge after its in-body availability assertion."""
    build = require_planning_bridge()
    return build(
        hook_point="conversation.started",
        module_bindings=modules,
        bindings_per_event=capacity,
        hook_script_configured=configured,
        discovery_result=discovery_result,
    )


def plan_bindings(result: Any) -> tuple[Any, ...]:
    """Require an immutable candidate binding plan."""
    assert hasattr(result, "bindings"), "planning result must expose bindings"
    assert type(result.bindings) is tuple, "planning bindings must be immutable"
    return result.bindings


def terminal_entries(result: Any) -> tuple[Any, ...]:
    """Require immutable ordered metadata on the unique terminal binding."""
    terminal = plan_bindings(result)[-1]
    assert terminal.binding_id == "hook_script"
    assert hasattr(terminal, "entries"), "terminal binding must expose planned entries"
    assert type(terminal.entries) is tuple, "planned entries must be immutable"
    return terminal.entries
