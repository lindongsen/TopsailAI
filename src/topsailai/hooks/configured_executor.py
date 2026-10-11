"""Catalog-bound execution facade for configured Hooks."""

from __future__ import annotations

import asyncio

import uuid
import time
import threading
from dataclasses import dataclass, field
from typing import Any

from topsailai.hooks.configured_registration import ConfiguredHookRegistrar, RegistrationEnsureResult
from topsailai.hooks.contracts import DeliveryReceipt, DispatchReport, HookStatus
from topsailai.hooks.hook_point_catalog import HookPointCatalog, HookPointDeclaration
from topsailai.hooks.runtime import HookRuntime, HookScope
from topsailai.hooks.validation import validate_payload


@dataclass(frozen=True, slots=True)
class HookOperation:
    """Carry explicit correlation metadata for one Hook occurrence."""

    operation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_operation_id: str | None = None
    depth: int = 0

    def __post_init__(self) -> None:
        """Validate bounded correlation metadata without external I/O."""
        invalid = (
            type(self.operation_id) is not str
            or not self.operation_id
            or len(self.operation_id) > 256
            or (
                self.parent_operation_id is not None
                and (
                    type(self.parent_operation_id) is not str
                    or not self.parent_operation_id
                    or len(self.parent_operation_id) > 256
                )
            )
            or type(self.depth) is not int
            or not 0 <= self.depth <= 1_000
        )
        if invalid:
            raise ValueError("invalid Hook operation")


class HookPointBlockedError(RuntimeError):
    """Report an explicitly authorized blocking Hook-point failure."""

    def __init__(self, point_name: str, reason: str) -> None:
        """Create one bounded host-facing block result."""
        super().__init__(f"Hook point blocked: {point_name} ({reason})")
        self.point_name = point_name
        self.reason = reason


class ConfiguredHookExecutor:
    """Execute known Hook points through one shared Registrar and Runtime."""

    def __init__(
        self,
        runtime: HookRuntime,
        scope: HookScope,
        registrar: ConfiguredHookRegistrar,
        catalog: HookPointCatalog,
    ) -> None:
        """Bind one application Scope and immutable declaration catalog."""
        runtime_methods = ("make_event", "dispatch_configured", "adispatch_configured", "emit_configured")
        registrar_methods = ("ensure_registered", "aensure_registered")
        invalid = (
            any(not callable(getattr(runtime, name, None)) for name in runtime_methods)
            or type(getattr(scope, "scope_id", None)) is not str
            or any(not callable(getattr(registrar, name, None)) for name in registrar_methods)
            or type(catalog) is not HookPointCatalog
        )
        if invalid:
            raise ValueError("invalid configured Hook Executor")
        self._runtime = runtime
        self._scope = scope
        self._registrar = registrar
        self._catalog = catalog

    def dispatch(
        self,
        point: HookPointDeclaration,
        *,
        payload: Any,
        operation: HookOperation | None = None,
        cancellation: threading.Event | None = None,
    ) -> DispatchReport:
        """Ensure and synchronously dispatch one catalog-owned sync point."""
        declaration = self._require_point(point, "sync")
        if cancellation is not None and type(cancellation) is not threading.Event:
            raise ValueError("invalid cancellation signal")
        deadline = None
        if isinstance(self._runtime, HookRuntime) and isinstance(self._registrar, ConfiguredHookRegistrar):
            deadline = time.monotonic() + self._runtime._settings.limits.dispatch_timeout_ms / 1000
        event = self._make_event(declaration, payload, operation)
        signal = threading.Event() if cancellation is None else cancellation
        ensured = self._registrar.ensure_registered(declaration.name) if deadline is None else self._registrar.ensure_registered(
            declaration.name, deadline=deadline, cancellation=signal)
        if not ensured.ready:
            report = DispatchReport(event.event_id, 0, rejection_reason=self._ensure_reason(ensured))
        else:
            report = self._runtime.dispatch_configured(declaration.name, event) if deadline is None else self._runtime.dispatch_configured(
                declaration.name, event, deadline=deadline, cancellation=signal)
        self._enforce_policy(declaration, report)
        return report

    async def adispatch(
        self,
        point: HookPointDeclaration,
        *,
        payload: Any,
        operation: HookOperation | None = None,
    ) -> DispatchReport:
        """Await registration and execution under one deadline without blocking the loop."""
        declaration = self._require_point(point, "async")
        event = self._make_event(declaration, payload, operation)
        if not isinstance(self._runtime, HookRuntime) or not isinstance(self._registrar, ConfiguredHookRegistrar):
            ensured = await self._registrar.aensure_registered(declaration.name)
            report = DispatchReport(event.event_id, 0, rejection_reason=self._ensure_reason(ensured)) if not ensured.ready else await self._runtime.adispatch_configured(declaration.name, event)
        else:
            deadline = time.monotonic() + self._runtime._settings.limits.dispatch_timeout_ms / 1000
            signal = threading.Event()
            try:
                ensured = await asyncio.to_thread(self._registrar.ensure_registered,
                    declaration.name, deadline=deadline, cancellation=signal)
                report = DispatchReport(event.event_id, 0, rejection_reason=self._ensure_reason(ensured)) if not ensured.ready else await self._runtime.adispatch_configured(
                    declaration.name, event, deadline=deadline, cancellation=signal)
            except asyncio.CancelledError:
                signal.set()
                raise
        self._enforce_policy(declaration, report)
        return report

    async def aemit(
        self,
        point: HookPointDeclaration,
        *,
        payload: Any,
        operation: HookOperation | None = None,
    ) -> DeliveryReceipt:
        """Ensure asynchronously, then use existing fast background admission."""
        declaration = self._require_point(point, "background")
        event = self._make_event(declaration, payload, operation)
        ensured = await self._registrar.aensure_registered(declaration.name)
        if not ensured.ready:
            receipt = DeliveryReceipt(False, event.event_id, self._ensure_reason(ensured))
        else:
            receipt = self._runtime.emit_configured(declaration.name, event)
        if declaration.failure_policy == "block" and not receipt.admitted:
            raise HookPointBlockedError(declaration.name, receipt.rejection_reason or "not_admitted")
        return receipt

    def _require_point(self, point: HookPointDeclaration, mode: str) -> HookPointDeclaration:
        """Require an exact catalog declaration with the requested execution mode."""
        if type(point) is not HookPointDeclaration:
            raise ValueError("invalid Hook-point declaration")
        declaration = self._catalog.require(point.name)
        if declaration != point:
            raise ValueError("Hook-point declaration is not catalog-owned")
        if declaration.mode != mode:
            raise ValueError("Hook-point execution mode mismatch")
        return declaration

    def _make_event(
        self,
        point: HookPointDeclaration,
        payload: Any,
        operation: HookOperation | None,
    ):
        """Validate payload and create one immutable Runtime event."""
        resolved = HookOperation() if operation is None else operation
        if type(resolved) is not HookOperation:
            raise ValueError("invalid Hook operation")
        detached = validate_payload(point.definition, payload)
        return self._runtime.make_event(
            self._scope,
            point.definition.name,
            point.definition.major_version,
            detached,
            operation_id=resolved.operation_id,
            parent_operation_id=resolved.parent_operation_id,
            layer="hooks",
            purpose=point.phase,
        )

    @staticmethod
    def _ensure_reason(result: RegistrationEnsureResult) -> str:
        """Map a typed registration state to one stable public rejection category."""
        return result.error_category or result.state.value

    @staticmethod
    def _enforce_policy(point: HookPointDeclaration, report: DispatchReport) -> None:
        """Raise only for catalog-authorized block declarations that did not succeed."""
        if point.failure_policy != "block":
            return
        reason = report.rejection_reason
        if reason is None:
            failure = next(
                (outcome for outcome in report.outcomes if outcome.status is not HookStatus.SUCCESS),
                None,
            )
            reason = None if failure is None else failure.error_category or failure.status.value
        if reason is not None:
            raise HookPointBlockedError(point.name, reason)
