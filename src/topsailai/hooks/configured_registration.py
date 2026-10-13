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
    desired_revision: int | None = None
    active_revision: int | None = None
    update_failed_using_last_known_good: bool = False

    @property
    def ready(self) -> bool:
        """Return whether configured dispatch may proceed."""
        return self.state is RegistrationState.READY or (
            self.active_revision is not None and self.state in (
                RegistrationState.FAILED_DETERMINISTIC, RegistrationState.FAILED_TRANSIENT))


@dataclass(slots=True)
class _RegistrationCell:
    """Hold mutable state protected by the Registrar condition."""

    state: RegistrationState
    attempt: int = 0
    error_category: str | None = None
    retry_at: float = 0.0
    exception: BaseException | None = None
    desired_revision: int | None = None
    active_revision: int | None = None


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
        self._prepared_result = None
        self._reloading = False
        self._bindings = self._binding_map(bootstrap)
        self._cells = {
            name: _RegistrationCell(RegistrationState.UNINITIALIZED,
                desired_revision=bootstrap.configuration_generation)
            for name in self._bindings
        }

    @classmethod
    def from_prepared(cls, runtime, scope, request, *, cancellation=None):
        """Publish an explicit catalog-owned request without a legacy bootstrap path."""
        from topsailai.hooks.configured_contracts import SummaryPreparationRequest
        from topsailai.hooks.configured_runtime import register_summary_prepared

        if type(request) is not SummaryPreparationRequest:
            raise ValueError("invalid summary preparation request")
        registrar = cls.__new__(cls)
        registrar._runtime = runtime
        registrar._scope = scope
        registrar._catalog = request.catalog
        registrar._condition = threading.Condition()
        registrar._closed = False
        registrar._reloading = False
        registrar._bindings = {}
        registrar._cells = {}
        registrar._prepared_result = register_summary_prepared(runtime, request, scope,
            cancellation=cancellation)
        for item in registrar._prepared_result.dispositions:
            ready = item.kind == "registered"
            _, owner = runtime._registry.configured_plan(scope.scope_id, item.hook_name)
            registrar._cells[item.hook_name] = _RegistrationCell(
                RegistrationState.READY if ready else RegistrationState.UNCONFIGURED,
                error_category=None if ready else item.reason,
                active_revision=owner.snapshot.active_version if ready and owner is not None else None)
        return registrar

    @property
    def dispositions(self):
        """Expose detached per-point state, not a process startup report."""
        return () if self._prepared_result is None else self._prepared_result.dispositions

    @staticmethod
    def _binding_map(bootstrap: ConfiguredHookBootstrap) -> dict[str, ConfiguredHookBinding]:
        """Return enabled configured selections keyed by known Hook name."""
        if not bootstrap.enabled:
            return {}
        return {item.hook_name: item for item in bootstrap.hooks if item.enabled}

    def start(self) -> RegistrationEnsureResult:
        """Eagerly register the complete startup snapshot or disable it wholly."""
        if self._prepared_result is not None:
            with self._condition:
                return self._result(RegistrationState.CLOSED, "scope_closed") if self._closed else self._result(RegistrationState.READY)
        if not self._bootstrap.enabled:
            return RegistrationEnsureResult(RegistrationState.UNCONFIGURED)
        if self._bootstrap.registration_mode != "startup":
            return RegistrationEnsureResult(RegistrationState.UNINITIALIZED)
        with self._condition:
            retained = {name for name, cell in self._cells.items()
                if cell.active_revision is not None}
        newly_registered: list[str] = []
        for hook_name in tuple(self._bindings):
            prior_state = self.state(hook_name)
            result = self.ensure_registered(hook_name)
            if result.ready:
                if hook_name not in retained and prior_state is not RegistrationState.READY:
                    newly_registered.append(hook_name)
                continue
            disable = self._bootstrap.startup_policy == "disable"
            retire_names = (tuple(name for name in self._bindings if name not in retained)
                if disable else tuple(newly_registered))
            with self._condition:
                if disable:
                    for active_name in retire_names:
                        self._runtime.retire_configured(active_name, self._scope)
                    self._bindings = {name: binding for name, binding in self._bindings.items()
                        if name in retained}
                    for active_name in retire_names:
                        self._cells[active_name].state = RegistrationState.UNCONFIGURED
                        self._cells[active_name].active_revision = None
                    self._condition.notify_all()
                    return RegistrationEnsureResult(RegistrationState.UNCONFIGURED)
                for active_name in retire_names:
                    cell = self._cells.get(active_name)
                    if cell is not None and cell.state is RegistrationState.READY:
                        cell.active_revision = None
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

    def ensure_registered(self, hook_name: str, *, deadline=None, cancellation=None) -> RegistrationEnsureResult:
        """Register one Hook through a sync/async shared singleflight cell."""
        if self._prepared_result is not None:
            with self._condition:
                if self._closed:
                    return self._result(RegistrationState.CLOSED, "scope_closed")
                cell = self._cells.get(hook_name)
                return self._result(RegistrationState.UNCONFIGURED) if cell is None else self._cell_result(cell)
        if deadline is not None or cancellation is not None:
            return self._ensure_budgeted(hook_name, deadline, cancellation)
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
                    break
                self._condition.wait()
        try:
            result = self._register(binding)
        except BaseException as exc:
            with self._condition:
                if self._cells.get(hook_name) is cell and cell.state is RegistrationState.REGISTERING:
                    cell.exception = exc
                    cell.state = RegistrationState.FAILED_DETERMINISTIC
                    cell.error_category = "registration_exception"
                self._condition.notify_all()
            raise
        return self._publish_result(hook_name, cell, result)

    def _ensure_budgeted(self, hook_name, deadline, cancellation):
        """Stop only this wait; the shared preparation owner completes independently."""
        with self._condition:
            while True:
                if cancellation is not None and cancellation.is_set():
                    return self._result(RegistrationState.REGISTERING, "cancelled")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return self._result(RegistrationState.REGISTERING, "deadline")
                decision = self._registration_decision(hook_name)
                if type(decision) is RegistrationEnsureResult:
                    return decision
                if decision:
                    cell = self._cells[hook_name]
                    cell.state = RegistrationState.REGISTERING
                    cell.attempt += 1
                    binding = self._bindings[hook_name]
                    owner = threading.Thread(target=self._prepare_shared,
                        args=(hook_name, binding, cell), daemon=True)
                    try:
                        owner.start()
                    except BaseException as exc:
                        cell.exception = exc
                        cell.state = RegistrationState.FAILED_DETERMINISTIC
                        cell.error_category = "registration_exception"
                        self._condition.notify_all()
                        raise
                self._condition.wait(.01 if remaining is None else min(.01, remaining))

    def _prepare_shared(self, hook_name, binding, cell):
        """Publish shared completion or original failure to all live waiters."""
        try:
            result = self._register(binding)
            self._publish_result(hook_name, cell, result)
        except BaseException as exc:
            with self._condition:
                if self._cells.get(hook_name) is cell and cell.state is RegistrationState.REGISTERING:
                    cell.exception = exc
                    cell.state = RegistrationState.FAILED_DETERMINISTIC
                    cell.error_category = "registration_exception"
                self._condition.notify_all()

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
        if cell.exception is not None:
            raise cell.exception
        if cell.state is RegistrationState.READY:
            return self._cell_result(cell)
        if cell.state is RegistrationState.FAILED_DETERMINISTIC:
            return self._cell_result(cell)
        if cell.state is RegistrationState.FAILED_TRANSIENT:
            if cell.active_revision is not None or cell.attempt >= self._max_transient_attempts or time.monotonic() < cell.retry_at:
                return self._cell_result(cell)
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
        expected_cell: _RegistrationCell,
        result: ConfiguredRegistrationResult,
    ) -> RegistrationEnsureResult:
        """Publish one winner result only if ownership remains current."""
        retire = False
        with self._condition:
            cell = self._cells.get(hook_name)
            stale = cell is not expected_cell
            if self._closed or cell is None or stale:
                retire = result.accepted
                final = self._result(RegistrationState.CLOSED if self._closed else RegistrationState.INVALIDATED, failure=RegistrationFailureKind.CLOSED if self._closed else RegistrationFailureKind.DETERMINISTIC)
            elif result.accepted:
                cell.state = RegistrationState.READY
                cell.active_revision = result.active_revision
                cell.error_category = None
                final = self._cell_result(cell)
            else:
                category = result.errors[0] if result.errors else "registration_rejected"
                transient = category in _TRANSIENT_ERRORS
                cell.state = RegistrationState.FAILED_TRANSIENT if transient else RegistrationState.FAILED_DETERMINISTIC
                cell.error_category = category
                cell.retry_at = time.monotonic() + self._transient_backoff_seconds
                final = self._cell_result(cell)
            self._condition.notify_all()
        if retire:
            self._runtime.retire_configured(hook_name, self._scope)
        return final

    def reload(self, bootstrap: ConfiguredHookBootstrap) -> None:
        """Invalidate one same-trust snapshot without dropping active replacements."""
        if self._prepared_result is not None:
            raise ValueError("prepared Registrar requires explicit replacement")
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
                changed.update(name for name, cell in self._cells.items()
                    if cell.state in (RegistrationState.FAILED_DETERMINISTIC,
                        RegistrationState.FAILED_TRANSIENT))
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
                        prior = self._cells.get(name)
                        self._cells[name] = _RegistrationCell(RegistrationState.UNINITIALIZED,
                            desired_revision=bootstrap.configuration_generation,
                            active_revision=None if prior is None else prior.active_revision)
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

    def stop_admission(self) -> None:
        """Stop registration and wake waiters without closing application resources."""
        with self._condition:
            self._closed = True
            for cell in self._cells.values():
                cell.active_revision = None
                cell.state = RegistrationState.CLOSED
            self._condition.notify_all()

    def close(self) -> None:
        """Stop registration admission and close the owned Scope compatibly."""
        self.stop_admission()
        with self._condition:
            if getattr(self, "_scope_close_requested", False):
                return
            self._scope_close_requested = True
        self._scope.close()

    @staticmethod
    def _cell_result(cell: _RegistrationCell) -> RegistrationEnsureResult:
        """Expose desired selection and exact active publication without authority."""
        failure = RegistrationFailureKind.NONE
        if cell.state is RegistrationState.FAILED_DETERMINISTIC:
            failure = RegistrationFailureKind.DETERMINISTIC
        elif cell.state is RegistrationState.FAILED_TRANSIENT:
            failure = RegistrationFailureKind.TRANSIENT
        return RegistrationEnsureResult(cell.state, cell.error_category, failure,
            cell.attempt, cell.desired_revision, cell.active_revision,
            cell.active_revision is not None and failure is not RegistrationFailureKind.NONE)

    @staticmethod
    def _result(
        state: RegistrationState,
        error: str | None = None,
        failure: RegistrationFailureKind = RegistrationFailureKind.NONE,
        attempt: int = 0,
    ) -> RegistrationEnsureResult:
        """Build one immutable state result."""
        return RegistrationEnsureResult(state, error, failure, attempt)
