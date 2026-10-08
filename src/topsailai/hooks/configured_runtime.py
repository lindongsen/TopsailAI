"""Runtime composition helpers for configured preparation."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from topsailai.hooks.configured_contracts import (
    ConfiguredHooks,
    ConfiguredTrustPolicy,
    PrepareConfiguredResult,
)

if TYPE_CHECKING:
    from topsailai.hooks.runtime import HookRuntime, HookScope


def detach_configured_trust(
    configured_trust: ConfiguredTrustPolicy | None,
) -> ConfiguredTrustPolicy | None:
    """Validate and detach configured authority before resource allocation."""
    if configured_trust is None:
        return None
    if type(configured_trust) is not ConfiguredTrustPolicy:
        raise ValueError("invalid configured trust policy")
    return ConfiguredTrustPolicy(
        source_roots=tuple(configured_trust.source_roots),
        allowed_interpreters=tuple(configured_trust.allowed_interpreters),
        allow_native_scripts=configured_trust.allow_native_scripts,
        closure_assertions=tuple(configured_trust.closure_assertions),
        python_runtime=configured_trust.python_runtime,
    )


def get_configured_trust(runtime: HookRuntime) -> ConfiguredTrustPolicy | None:
    """Return the immutable detached configured trust authority."""
    return runtime._configured_trust


def prepare_configured(
    runtime: HookRuntime,
    configuration: ConfiguredHooks,
    scope: HookScope,
    *,
    cancellation: threading.Event | None = None,
) -> PrepareConfiguredResult:
    """Validate the U09-A public boundary without performing discovery."""
    from topsailai.hooks.runtime import HookScope

    with runtime._lock:
        generation = runtime._registry.generation
        if type(configuration) is not ConfiguredHooks:
            return PrepareConfiguredResult(
                False, generation, errors=("invalid_configuration",)
            )
        if type(scope) is not HookScope or scope._runtime is not runtime:
            return PrepareConfiguredResult(False, generation, errors=("invalid_scope",))
        if cancellation is not None and type(cancellation) is not threading.Event:
            return PrepareConfiguredResult(
                False, generation, errors=("invalid_configuration",)
            )
        if runtime._state != "running":
            return PrepareConfiguredResult(False, generation, errors=("runtime_closed",))
        if not runtime._owns_open_scope(scope):
            return PrepareConfiguredResult(False, generation, errors=("scope_closed",))
        if runtime._configured_trust is None:
            return PrepareConfiguredResult(
                False, generation, errors=("trust_policy_missing",)
            )
        if cancellation is not None and cancellation.is_set():
            return PrepareConfiguredResult(False, generation, errors=("cancelled",))
        return PrepareConfiguredResult(False, generation, errors=("internal_error",))
