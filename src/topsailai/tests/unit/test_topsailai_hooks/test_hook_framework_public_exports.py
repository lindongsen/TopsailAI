"""Public package-root export tests for Hook framework readiness APIs."""

from __future__ import annotations

import topsailai.hooks as hooks


def test_framework_readiness_contracts_are_publicly_exported() -> None:
    """Every documented readiness contract must be reachable from the package root."""
    names = {
        "ConfiguredHookBinding",
        "ConfiguredHookBootstrap",
        "ConfiguredHookExecutor",
        "ConfiguredHookRegistrar",
        "HookInvocationView",
        "HookOperation",
        "HookPointBlockedError",
        "HookPointCatalog",
        "HookPointDeclaration",
        "RegistrationEnsureResult",
        "RegistrationFailureKind",
        "RegistrationState",
        "hook_point",
        "load_configured_hook_bootstrap",
        "load_configured_trust_manifest",
    }

    assert names <= set(hooks.__all__)
    assert all(getattr(hooks, name, None) is not None for name in names)


def test_unified_result_contracts_are_publicly_exported() -> None:
    """All eight foundation records must be public without runtime adoption."""
    names = {"HandlerIdentity", "ReturnedValue", "ResultDiagnostic", "ResultTiming", "ResultCleanup", "ResultDecision", "HandlerResult", "HookPointResult"}
    assert names <= set(hooks.__all__)
    assert all(getattr(hooks, name, None) is not None for name in names)


def test_ordinary_runtime_exposes_only_waiting_execution() -> None:
    """Ordinary execution must not expose a nonwaiting compatibility entry."""
    assert not hasattr(hooks.HookRuntime, "emit")
    assert callable(hooks.HookRuntime.dispatch)
    assert callable(hooks.HookRuntime.adispatch)


def test_configured_execution_has_no_nonwaiting_api_or_receipt() -> None:
    """Remove nonwaiting entries and the receipt from every public boundary."""
    from topsailai.hooks import contracts, configured_runtime

    assert not hasattr(hooks.HookRuntime, "emit_configured")
    assert not hasattr(configured_runtime, "emit_configured")
    assert not hasattr(hooks.ConfiguredHookExecutor, "aemit")
    assert not hasattr(hooks.HookRuntime, "_observe_background_completion")
    assert "DeliveryReceipt" not in hooks.__all__
    assert not hasattr(hooks, "DeliveryReceipt")
    assert not hasattr(contracts, "DeliveryReceipt")
    assert callable(hooks.HookRuntime.dispatch_configured)
    assert callable(hooks.HookRuntime.adispatch_configured)
