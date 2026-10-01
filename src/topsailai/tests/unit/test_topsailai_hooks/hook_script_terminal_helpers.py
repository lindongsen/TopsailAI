"""Helpers for future framework-owned terminal hook_script contracts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from topsailai.hooks import Binding


MISSING_CONTRACT = (
    "R5 hook_script terminal-binding contract missing: "
    "build_hook_point_binding_plan and terminal settlement helpers"
)


def require_terminal_contract() -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    """Return future production APIs or fail attributably inside the test body."""
    try:
        from topsailai.hooks.hook_script import (
            build_hook_point_binding_plan,
            hook_script_ready,
            settle_unconfigured_hook_script,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        raise AssertionError(MISSING_CONTRACT) from exc
    assert callable(build_hook_point_binding_plan), MISSING_CONTRACT
    assert callable(hook_script_ready), MISSING_CONTRACT
    assert callable(settle_unconfigured_hook_script), MISSING_CONTRACT
    return build_hook_point_binding_plan, hook_script_ready, settle_unconfigured_hook_script


def module_binding(module_name: str, **changes: object) -> Binding:
    """Build one discovered module binding whose identity follows its module name."""
    binding = Binding(
        binding_id=f"module:{module_name}",
        event_name="conversation.started",
        event_version=1,
        handler_ref=f"discovered.{module_name}:main",
    )
    return replace(binding, **changes)


def build_plan(
    bindings: tuple[Binding, ...],
    *,
    hook_point: str = "conversation.started",
    capacity: int = 8,
    configured: bool = False,
) -> Any:
    """Invoke the future terminal-binding builder after an in-body contract check."""
    build, _, _ = require_terminal_contract()
    return build(
        hook_point=hook_point,
        module_bindings=bindings,
        bindings_per_event=capacity,
        hook_script_configured=configured,
    )


def plan_bindings(result: Any) -> tuple[Any, ...]:
    """Require one immutable binding plan from the future result."""
    assert hasattr(result, "bindings"), "terminal plan result must expose bindings"
    assert type(result.bindings) is tuple, "terminal binding plan must be immutable"
    return result.bindings
