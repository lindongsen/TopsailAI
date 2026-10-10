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
