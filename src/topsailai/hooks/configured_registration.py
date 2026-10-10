"""Shared startup and lazy registration state for configured Hooks."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
from topsailai.hooks.configured_contracts import ConfiguredRegistrationResult
from topsailai.hooks.hook_point_catalog import HookPointCatalog

if TYPE_CHECKING:
    from topsailai.hooks.runtime import HookRuntime, HookScope


class RegistrationState(str, Enum):
    """Describe one configured Hook registration lifecycle state."""

    UNCONFIGURED = "unconfigured"
    UNINITIALIZED = "uninitialized"
    REGISTERING = "registering"
    READY = "ready"
    FAILED_DETERMINISTIC = "failed_deterministic"
    FAILED_TRANSIENT = "failed_transient"
    INVALIDATED = "invalidated"
    CLOSED = "closed"


class RegistrationFailureKind(str, Enum):
    """Classify registration rejection without message matching."""

    NONE = "none"
    DETERMINISTIC = "deterministic"
    TRANSIENT = "transient"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RegistrationEnsureResult:
    """Report one stable registration-state observation."""

    state: RegistrationState
    error_category: str | None = None
    failure_kind: RegistrationFailureKind = RegistrationFailureKind.NONE
    attempt: int = 0

    @property
    def ready(self) -> bool:
        """Return whether configured dispatch may proceed."""
        return self.state is RegistrationState.READY


@dataclass(slots=True)
class _RegistrationCell:
    """Hold mutable state protected by the Registrar condition."""

    state: RegistrationState
    attempt: int = 0
    error_category: str | None = None
    retry_at: float = 0.0


_TRANSIENT_ERRORS = frozenset({"capacity_exceeded", "cleanup_pending"})


class ConfiguredHookRegistrar:
    """Coordinate one application Scope's startup or lazy registrations."""

    def __init__(
        self,
        runtime: HookRuntime,
        scope: HookScope,
        bootstrap: ConfiguredHookBootstrap,
        catalog: HookPointCatalog,
        *,
        max_transient_attempts: int = 3,
        transient_backoff_seconds: float = 0.05,
    ) -> None:
        """Validate and own one immutable bootstrap generation."""
        if type(bootstrap) is not ConfiguredHookBootstrap or type(catalog) is not HookPointCatalog:
            raise ValueError("invalid configured Hook Registrar")
        if type(max_transient_attempts) is not int or not 1 <= max_transient_attempts <= 10:
            raise ValueError("invalid configured Hook Registrar")
        if type(transient_backoff_seconds) not in (int, float) or not 0 <= transient_backoff_seconds <= 60:
            raise ValueError("invalid configured Hook Registrar")
        for binding in bootstrap.hooks:
            catalog.require(binding.hook_name)
        self._runtime = runtime
        self._scope = scope
        self._bootstrap = bootstrap
        self._catalog = catalog
        self._max_transient_attempts = max_transient_attempts
        self._transient_backoff_seconds = float(transient_backoff_seconds)
        self._condition = threading.Condition()
        self._closed = False
        self._reloading = False
        self._bindings = self._binding_map(bootstrap)
        self._cells = {
            name: _RegistrationCell(RegistrationState.UNINITIALIZED)
            for name in self._bindings
        }

    @staticmethod
    def _binding_map(bootstrap: ConfiguredHookBootstrap) -> dict[str, ConfiguredHookBinding]:
        """Return enabled configured selections keyed by known Hook name."""
        if not bootstrap.enabled:
            return {}
        return {item.hook_name: item for item in bootstrap.hooks if item.enabled}

    def start(self) -> RegistrationEnsureResult:
        """Eagerly register the complete startup snapshot or disable it wholly."""
        if not self._bootstrap.enabled:
            return RegistrationEnsureResult(RegistrationState.UNCONFIGURED)
        if self._bootstrap.registration_mode != "startup":
            return RegistrationEnsureResult(RegistrationState.UNINITIALIZED)
        newly_registered: list[str] = []
        for hook_name in tuple(self._bindings):
            prior_state = self.state(hook_name)
            result = self.ensure_registered(hook_name)
            if result.ready:
                if prior_state is not RegistrationState.READY:
                    newly_registered.append(hook_name)
                continue
            disable = self._bootstrap.startup_policy == "disable"
            retire_names = tuple(self._bindings) if disable else tuple(newly_registered)
            with self._condition:
                if disable:
                    for active_name in retire_names:
                        self._runtime.retire_configured(active_name, self._scope)
                    self._bindings = {}
                    for cell in self._cells.values():
                        cell.state = RegistrationState.UNCONFIGURED
                    self._condition.notify_all()
                    return RegistrationEnsureResult(RegistrationState.UNCONFIGURED)
                for active_name in retire_names:
                    cell = self._cells.get(active_name)
                    if cell is not None and cell.state is RegistrationState.READY:
                        cell.state = RegistrationState.INVALIDATED
                        cell.error_category = None
                        cell.retry_at = 0.0
                    self._runtime.retire_configured(active_name, self._scope)
                self._condition.notify_all()
            return result
        return RegistrationEnsureResult(RegistrationState.READY)

    def state(self, hook_name: str) -> RegistrationState:
        """Return the in-memory state without registration or filesystem work."""
        with self._condition:
            if self._closed:
                return RegistrationState.CLOSED
            cell = self._cells.get(hook_name)
            return RegistrationState.UNCONFIGURED if cell is None else cell.state

    def ensure_registered(self, hook_name: str) -> RegistrationEnsureResult:
        """Register one Hook through a sync/async shared singleflight cell."""
        with self._condition:
            while True:
                decision = self._registration_decision(hook_name)
                if type(decision) is RegistrationEnsureResult:
                    return decision
                if decision:
                    cell = self._cells[hook_name]
                    cell.state = RegistrationState.REGISTERING
                    cell.attempt += 1
                    binding = self._bindings[hook_name]
                    generation = self._bootstrap.configuration_generation
                    break
                self._condition.wait()
        result = self._register(binding)
        return self._publish_result(hook_name, generation, result)

    async def aensure_registered(self, hook_name: str) -> RegistrationEnsureResult:
        """Await shared registration without blocking the event loop."""
        return await asyncio.to_thread(self.ensure_registered, hook_name)

    def _registration_decision(self, hook_name: str) -> RegistrationEnsureResult | bool:
        """Return a terminal result, winner flag, or waiter flag under the lock."""
        if self._closed:
            return self._result(RegistrationState.CLOSED, failure=RegistrationFailureKind.CLOSED)
        cell = self._cells.get(hook_name)
        if cell is None:
            return self._result(RegistrationState.UNCONFIGURED)
        if cell.state is RegistrationState.READY:
            return self._result(RegistrationState.READY, attempt=cell.attempt)
        if cell.state is RegistrationState.FAILED_DETERMINISTIC:
            return self._result(cell.state, cell.error_category, RegistrationFailureKind.DETERMINISTIC, cell.attempt)
        if cell.state is RegistrationState.FAILED_TRANSIENT:
            if cell.attempt >= self._max_transient_attempts or time.monotonic() < cell.retry_at:
                return self._result(cell.state, cell.error_category, RegistrationFailureKind.TRANSIENT, cell.attempt)
            return True
        if cell.state is RegistrationState.REGISTERING:
            return False
        if cell.state in (RegistrationState.UNINITIALIZED, RegistrationState.INVALIDATED):
            return True
        return self._result(cell.state)

    def _register(self, binding: ConfiguredHookBinding) -> ConfiguredRegistrationResult:
        """Invoke the unchanged explicit Runtime registration API."""
        if binding.folder is not None:
            return self._runtime.register_configured(
                binding.hook_name, self._scope, folder=binding.folder
            )
        return self._runtime.register_configured(
            binding.hook_name, self._scope, scripts=binding.scripts
        )

    def _publish_result(
        self,
        hook_name: str,
        generation: int,
        result: ConfiguredRegistrationResult,
    ) -> RegistrationEnsureResult:
        """Publish one winner result only if ownership remains current."""
        retire = False
        with self._condition:
            cell = self._cells.get(hook_name)
            stale = generation != self._bootstrap.configuration_generation
            if self._closed or cell is None or stale:
                retire = result.accepted
                final = self._result(RegistrationState.CLOSED if self._closed else RegistrationState.INVALIDATED, failure=RegistrationFailureKind.CLOSED if self._closed else RegistrationFailureKind.DETERMINISTIC)
            elif result.accepted:
                cell.state = RegistrationState.READY
                cell.error_category = None
                final = self._result(cell.state, attempt=cell.attempt)
            else:
                category = result.errors[0] if result.errors else "registration_rejected"
                transient = category in _TRANSIENT_ERRORS
                cell.state = RegistrationState.FAILED_TRANSIENT if transient else RegistrationState.FAILED_DETERMINISTIC
                cell.error_category = category
                cell.retry_at = time.monotonic() + self._transient_backoff_seconds
                kind = RegistrationFailureKind.TRANSIENT if transient else RegistrationFailureKind.DETERMINISTIC
                final = self._result(cell.state, category, kind, cell.attempt)
            self._condition.notify_all()
        if retire:
            self._runtime.retire_configured(hook_name, self._scope)
        return final

    def reload(self, bootstrap: ConfiguredHookBootstrap) -> None:
        """Invalidate one same-trust snapshot without dropping active replacements."""
        if type(bootstrap) is not ConfiguredHookBootstrap or bootstrap.trust_identity != self._bootstrap.trust_identity:
            raise ValueError("configured trust change requires Runtime replacement")
        for binding in bootstrap.hooks:
            self._catalog.require(binding.hook_name)
        new_bindings = self._binding_map(bootstrap)
        with self._condition:
            while self._reloading and not self._closed:
                self._condition.wait()
            if self._closed:
                raise RuntimeError("configured Hook Registrar is closed")
            self._reloading = True
            try:
                old_bindings = self._bindings
                changed = {
                    name for name in set(old_bindings) | set(new_bindings)
                    if old_bindings.get(name) != new_bindings.get(name)
                }
                while any(
                    self._cells.get(name) is not None
                    and self._cells[name].state is RegistrationState.REGISTERING
                    for name in changed
                ) and not self._closed:
                    self._condition.wait()
                if self._closed:
                    raise RuntimeError("configured Hook Registrar is closed")
                self._bootstrap = bootstrap
                self._bindings = new_bindings
                for name in changed:
                    if name in new_bindings:
                        self._cells[name] = _RegistrationCell(RegistrationState.UNINITIALIZED)
                    else:
                        self._cells.pop(name, None)
                removed = sorted(set(old_bindings) - set(new_bindings))
            finally:
                self._reloading = False
                self._condition.notify_all()
        for name in removed:
            self._runtime.retire_configured(name, self._scope)
        if bootstrap.registration_mode == "startup":
            result = self.start()
            if not result.ready and bootstrap.startup_policy == "fail":
                raise RuntimeError(result.error_category or "configured Hook startup registration failed")

    def close(self) -> None:
        """Close registration admission, wake waiters, then close the owned Scope."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            for cell in self._cells.values():
                cell.state = RegistrationState.CLOSED
            self._condition.notify_all()
        self._scope.close()

    @staticmethod
    def _result(
        state: RegistrationState,
        error: str | None = None,
        failure: RegistrationFailureKind = RegistrationFailureKind.NONE,
        attempt: int = 0,
    ) -> RegistrationEnsureResult:
        """Build one immutable state result."""
        return RegistrationEnsureResult(state, error, failure, attempt)
