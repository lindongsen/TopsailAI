"""Public lifecycle facade for the standalone unified hooks runtime."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import threading
import time
import uuid
from concurrent.futures import CancelledError as FutureCancelledError
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from topsailai.hooks.ordinary_runtime import register_hook_point, dispatch_hook_point
from topsailai.hooks.configuration import HookSettings
from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy
from topsailai.hooks.configured_runtime import (
    adispatch_configured as _adispatch_configured,
    detach_configured_trust,
    dispatch_configured as _dispatch_configured,
    emit_configured as _emit_configured,
    get_configured_trust,
    prepare_configured as _prepare_configured,
    register_configured as _register_configured,
    retire_configured as _retire_configured,
    retire_configured_scope,
)
from topsailai.hooks.contracts import (
    Binding,
    DeliveryReceipt,
    DispatchReport,
    EventDefinition,
    HookEvent,
    RegistrationHandle,
    RegistrationResult,
    RegistrySnapshot,
    ReloadResult,
    ValidationError,
)
from topsailai.hooks.diagnostics import DiagnosticBuffer
from topsailai.hooks.dispatcher import HookDispatcher
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import CleanupDebt
from topsailai.hooks.registry import HookRegistry
from topsailai.hooks.hook_point_plan_publication import PublicationRecovery
from topsailai.hooks.scheduler import HookScheduler, ScheduledWork
from topsailai.hooks.validation import freeze_json, validate_payload


@dataclass(frozen=True, slots=True)
class CloseReport:
    """Describe bounded runtime or scope closure."""

    closed_scope_ids: tuple[str, ...] = ()
    cleanup_debts: tuple[CleanupDebt, ...] = ()
    already_closed: bool = False


@dataclass(slots=True)
class _DispatchAdmission:
    """Freeze registry, settings budgets, deadline, and accounting at admission."""

    event: HookEvent
    snapshot: RegistrySnapshot
    timeout_ms: int
    handler_timeout_ms: int
    started: float
    size_bytes: int
    cancellation_requested: threading.Event | None = None


class HookScope:
    """Own scope-local registrations and child-scope lifecycle."""

    def __init__(
        self,
        runtime: "HookRuntime",
        scope_id: str,
        parent_id: str | None,
        metadata: Mapping[str, Any],
    ) -> None:
        """Create a scope only through its owning runtime."""
        self._runtime = runtime
        self.scope_id = scope_id
        self.parent_id = parent_id
        self.metadata = metadata
        self._close_debt_id = "scope-close-" + uuid.uuid4().hex

    @property
    def closed(self) -> bool:
        """Return whether the owning runtime has closed this scope."""
        return not self._runtime._scope_is_open(self.scope_id)

    def close(self, deadline_ms: int | None = None) -> CloseReport:
        """Close this scope and every descendant idempotently."""
        return self._runtime._close_scope(self.scope_id, deadline_ms)

    def __enter__(self) -> "HookScope":
        """Enter a synchronously owned scope."""
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close the scope independently of body success."""
        self.close()


class HookRuntime:
    """Own registry, dispatcher, worker supervision, diagnostics, and scopes."""

    def __init__(
        self,
        settings: HookSettings,
        *,
        temp_root: str,
        process_backend: IsolatedProcessBackend | None = None,
        diagnostic_observer: Callable[[dict[str, object]], None] | None = None,
        configured_trust: ConfiguredTrustPolicy | None = None,
    ) -> None:
        """Build an explicit runtime without imports, workers, or environment discovery."""
        detached_trust = detach_configured_trust(configured_trust)
        if type(temp_root) is not str or not os.path.isabs(temp_root):
            raise ValueError("temp_root must be an absolute path")
        errors = settings.validate() if isinstance(settings, HookSettings) else ("invalid settings",)
        valid_settings = not errors
        active_settings = settings if valid_settings else HookSettings(enabled=False)
        self._settings = active_settings
        self._configured_trust = detached_trust
        self._registry = HookRegistry(
            bindings_per_event=active_settings.limits.bindings_per_event
        )
        self._backend = process_backend or IsolatedProcessBackend(temp_root=temp_root)
        self._scheduler = HookScheduler(
            active_settings.limits.workers,
            active_settings.limits.queue_items,
            active_settings.limits.queue_bytes,
            enabled=active_settings.enabled,
        )
        self._diagnostics = DiagnosticBuffer(
            capacity=active_settings.limits.queue_items,
            observer=diagnostic_observer if active_settings.enabled else None,
        )
        if errors:
            self._diagnostics.publish(
                "configuration_rejected", error_category="invalid_settings"
            )
        self._dispatcher = HookDispatcher(
            self._backend,
            self._scheduler,
            self._diagnostics.publish,
        )
        self._lock = threading.RLock()
        self._publication_recovery = PublicationRecovery(self._lock)
        self._state = "running"
        self._scopes: dict[str, HookScope] = {}
        self._children: dict[str, set[str]] = {}
        self._closing_scopes: set[str] = set()
        self._sequences: dict[str, int] = {}
        self._local = threading.local()
        self._ordinary_sources = {}

    register_hook_point = register_hook_point
    dispatch_hook_point = dispatch_hook_point

    configured_trust = property(get_configured_trust)
    prepare_configured = _prepare_configured
    register_configured = _register_configured
    retire_configured = _retire_configured
    dispatch_configured = _dispatch_configured
    adispatch_configured = _adispatch_configured
    emit_configured = _emit_configured

    def open_scope(
        self,
        parent: HookScope | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HookScope:
        """Open one scope whose parent controls cleanup ownership only."""
        frozen_metadata = freeze_json(dict(metadata or {}), max_bytes=16_384)
        if type(frozen_metadata) is not dict:
            raise ValueError("scope metadata must be an object")
        with self._lock:
            if self._state != "running":
                raise RuntimeError("hook runtime is not running")
            parent_id = parent.scope_id if parent is not None else None
            if parent is not None and (
                parent._runtime is not self or not self._scope_is_open(parent.scope_id)
            ):
                raise ValueError("parent scope is not open in this runtime")
            scope_id = uuid.uuid4().hex
            scope = HookScope(self, scope_id, parent_id, frozen_metadata)
            self._scopes[scope_id] = scope
            self._children.setdefault(scope_id, set())
            self._sequences[scope_id] = 0
            if parent_id is not None:
                self._children[parent_id].add(scope_id)
            return scope

    def register(
        self,
        definition: EventDefinition,
        binding: Binding,
        scope: HookScope,
    ) -> RegistrationResult:
        """Register only into an open scope owned by this runtime."""
        with self._lock:
            if not self._settings.enabled:
                return RegistrationResult(
                    False,
                    self._registry.generation,
                    errors=("hook runtime is disabled",),
                )
            if not self._owns_open_scope(scope):
                return RegistrationResult(
                    False,
                    self._registry.generation,
                    errors=("scope is not open in this runtime",),
                )
            return self._registry.register(definition, binding, scope.scope_id)

    def unregister(self, handle: RegistrationHandle) -> RegistrationResult:
        """Remove one exact registration for future admissions."""
        with self._lock:
            if not self._settings.enabled:
                return RegistrationResult(
                    False,
                    self._registry.generation,
                    errors=("hook runtime is disabled",),
                )
            return self._registry.unregister(handle)

    def reload(self, settings: HookSettings) -> ReloadResult:
        """Atomically publish validated operational settings without raising."""
        errors = settings.validate() if type(settings) is HookSettings else ("invalid settings",)
        with self._lock:
            generation = self._registry.generation
            if self._state != "running":
                return ReloadResult(False, generation, ("hook runtime is closed",))
            if errors:
                self._diagnostics.publish(
                    "configuration_rejected", error_category="invalid_settings"
                )
                return ReloadResult(False, generation, tuple(errors))
            if not self._registry.binding_cap_compatible(
                settings.limits.bindings_per_event
            ):
                self._diagnostics.publish(
                    "configuration_rejected", error_category="binding_capacity"
                )
                return ReloadResult(
                    False, generation, ("bindings_per_event limit is below active use",)
                )
            if settings == self._settings:
                return ReloadResult(True, generation)
            reconfigured = self._scheduler.reconfigure(
                enabled=settings.enabled,
                workers=settings.limits.workers,
                queue_items=settings.limits.queue_items,
                queue_bytes=settings.limits.queue_bytes,
            )
            if not reconfigured:
                self._diagnostics.publish(
                    "configuration_rejected", error_category="worker_start"
                )
                return ReloadResult(False, generation, ("worker start failed",))
            generation = self._registry.reconfigure(
                settings.limits.bindings_per_event
            )
            self._settings = settings
            return ReloadResult(True, generation)

    def make_event(
        self,
        scope: HookScope,
        name: str,
        major_version: int,
        payload: Any,
        *,
        operation_id: str,
        parent_operation_id: str | None = None,
        layer: str,
        purpose: str,
        owner_id: str | None = None,
    ) -> HookEvent:
        """Create one immutable event with a monotonic per-scope sequence."""
        if not self._owns_open_scope(scope):
            raise ValueError("scope is not open in this runtime")
        with self._lock:
            self._sequences[scope.scope_id] += 1
            sequence = self._sequences[scope.scope_id]
        resolved_owner = owner_id or str(scope.metadata.get("owner_id", scope.scope_id))
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return HookEvent(
            uuid.uuid4().hex,
            name,
            major_version,
            resolved_owner,
            scope.scope_id,
            operation_id,
            parent_operation_id,
            sequence,
            timestamp,
            layer,
            purpose,
            payload,
        )

    def dispatch(self, event: HookEvent, policy: Any = None) -> DispatchReport:
        """Synchronously dispatch through the scheduler-owned bounded path."""
        work, rejection = self._admit(event, policy, reject_running_loop=True)
        if rejection is not None:
            return rejection
        if work is None:
            return self._rejected(event, "rejected_capacity")
        return work.future.result()

    async def adispatch(self, event: HookEvent, policy: Any = None) -> DispatchReport:
        """Await one bounded scheduler-owned dispatch without blocking the event loop."""
        cancellation_requested = threading.Event()
        work, rejection = self._admit(
            event,
            policy,
            reject_running_loop=False,
            cancellation_requested=cancellation_requested,
        )
        if rejection is not None:
            return rejection
        if work is None:
            return self._rejected(event, "rejected_capacity")
        wrapped = asyncio.wrap_future(work.future)
        try:
            return await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            cancellation_requested.set()
            self._diagnostics.publish("dispatch_cancel_requested", event_id=event.event_id)
            settlement_deadline = time.monotonic() + self._settings.limits.shutdown_timeout_ms / 1_000
            while not work.future.done():
                remaining = settlement_deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(
                        asyncio.shield(wrapped), min(remaining, 0.05)
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            self._diagnostics.publish("dispatch_cancelled", event_id=event.event_id)
            raise

    def emit(self, event: HookEvent, policy: Any = None) -> DeliveryReceipt:
        """Admit bounded background dispatch without waiting for plugin execution."""
        work, rejection = self._admit(event, policy, reject_running_loop=False)
        if rejection is not None:
            event_id = event.event_id if type(event) is HookEvent else ""
            return DeliveryReceipt(False, event_id, rejection.rejection_reason)
        if work is None:
            self._diagnostics.publish(
                "event_rejected", event_id=event.event_id, reason="rejected_capacity"
            )
            return DeliveryReceipt(False, event.event_id, "rejected_capacity")
        work.future.add_done_callback(
            lambda completed: self._observe_background_completion(work, completed)
        )
        self._diagnostics.publish(
            "event_admitted", event_id=event.event_id, scope_id=event.scope_id
        )
        return DeliveryReceipt(True, event.event_id)

    def drain_diagnostics(self, limit: int) -> tuple[dict[str, object], ...]:
        """Return bounded safe diagnostic metadata."""
        return self._diagnostics.drain(limit)

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Return backend obligations first, followed by retained publication custody."""
        with self._lock:
            deferred = tuple(CleanupDebt(scope._close_debt_id, "scope_close_pending", None,
                "scope retirement deferred") for key, scope in self._scopes.items()
                if key in self._closing_scopes)
        return self._backend.cleanup_debts() + self._publication_recovery.cleanup_debts() + deferred

    def retry_cleanup(self, debt_id: str) -> bool:
        """Retry one exact backend or publication debt without holding Runtime locks."""
        if type(debt_id) is not str:
            return False
        with self._lock:
            scope_id = next((key for key, scope in self._scopes.items()
                if key in self._closing_scopes and scope._close_debt_id == debt_id), None)
        if scope_id is not None:
            self._close_scope(scope_id, None)
            return True
        if self._publication_recovery.owns_debt(debt_id):
            return self._publication_recovery.retry_cleanup(debt_id)
        if any(debt.debt_id == debt_id for debt in self._backend.cleanup_debts()):
            return self._backend.retry_cleanup(debt_id)
        return self._publication_recovery.retry_cleanup(debt_id)

    def close(self, deadline_ms: int | None = None) -> CloseReport:
        """Idempotently stop admission, close scopes, and report cleanup debt."""
        with self._lock:
            already_closed = self._state in {"closed", "closing"}
            if not already_closed:
                self._state = "closing"
                root_ids = sorted(
                    scope_id for scope_id, scope in self._scopes.items() if scope.parent_id is None
                )
                scope_ids: list[str] = []
                for scope_id in root_ids:
                    scope_ids.extend(self._scope_tree_ids(scope_id))
                self._closing_scopes.update(scope_ids)
        if already_closed:
            with self._lock:
                pending_scope_ids = tuple(self._closing_scopes)
            closed = self._close_scope_ids(pending_scope_ids)
            return CloseReport(tuple(closed), cleanup_debts=self.cleanup_debts(), already_closed=True)
        timeout_ms = self._deadline_ms(deadline_ms, self._settings.limits.shutdown_timeout_ms)
        deadline = time.monotonic() + timeout_ms / 1_000
        closed = self._close_scope_ids(tuple(scope_ids))
        pending = self._scheduler.close(max(0.0, deadline - time.monotonic()))
        if pending:
            self._diagnostics.publish("shutdown_debt", pending_host_work=len(pending))
        self._diagnostics.publish("runtime_closed", cleanup_debt_count=len(self.cleanup_debts()))
        self._diagnostics.close(max(0.0, deadline - time.monotonic()))
        with self._lock:
            self._state = "closed"
        return CloseReport(tuple(closed), self.cleanup_debts())

    def __enter__(self) -> "HookRuntime":
        """Enter a synchronously owned runtime."""
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close the runtime independently of body success."""
        self.close()

    def _admit(
        self,
        event: HookEvent,
        policy: Any,
        *,
        reject_running_loop: bool,
        cancellation_requested: threading.Event | None = None,
    ) -> tuple[ScheduledWork[DispatchReport] | None, DispatchReport | None]:
        """Validate, snapshot, and reserve scheduler ownership atomically with reload."""
        rejection = self._admission_rejection(
            event, reject_running_loop=reject_running_loop
        )
        if rejection is not None:
            return None, rejection
        with self._lock:
            rejection = self._admission_rejection(
                event, reject_running_loop=reject_running_loop
            )
            if rejection is not None:
                return None, rejection
            admission, rejection = self._prepare_admission(event, policy)
            if rejection is not None:
                return None, rejection
            admission.cancellation_requested = cancellation_requested
            return self._submit_admission(admission), None

    def _prepare_admission(
        self, event: HookEvent, policy: Any
    ) -> tuple[_DispatchAdmission | None, DispatchReport | None]:
        """Capture registry and immutable settings budgets in one owner transaction."""
        started = time.monotonic()
        try:
            with self._lock:
                settings = self._settings
                snapshot = self._registry.snapshot(
                    event.scope_id, event.name, event.major_version
                )
                if snapshot.definition is None:
                    return None, self._rejected(event, "invalid_event")
                payload = validate_payload(snapshot.definition, event.payload)
                size_bytes = self._admission_size(event, snapshot, payload)
                if size_bytes > settings.limits.event_bytes:
                    return None, self._rejected(event, "invalid_event")
                detached_event = replace(event, payload=payload)
                timeout_ms = self._policy_timeout(policy, settings)
                handler_timeout_ms = settings.limits.handler_timeout_ms
        except (ValidationError, ValueError, TypeError, OverflowError):
            return None, self._rejected(event, "invalid_event")
        return (
            _DispatchAdmission(
                detached_event,
                snapshot,
                timeout_ms,
                handler_timeout_ms,
                started,
                max(1, size_bytes),
            ),
            None,
        )

    def _submit_admission(
        self, admission: _DispatchAdmission
    ) -> ScheduledWork[DispatchReport] | None:
        """Submit one dispatch with queue accounting and immutable terminal reports."""
        deadline = admission.started + admission.timeout_ms / 1_000
        return self._scheduler.submit(
            admission.event.scope_id,
            admission.size_bytes,
            lambda: self._dispatch_guarded(admission),
            cancellation_result=lambda: self._cancelled_report(admission),
            deadline_seconds=deadline,
            deadline_result=lambda: self._deadline_report(admission),
        )

    @staticmethod
    def _terminal_report(
        admission: _DispatchAdmission,
        status: str,
        category: str,
        *,
        deadline_exhausted: bool = False,
    ) -> DispatchReport:
        """Build one structured non-started terminal report for queued work."""
        from topsailai.hooks.contracts import HookOutcome, HookStatus

        terminal_status = getattr(HookStatus, status)
        outcomes = tuple(
            HookOutcome(
                uuid.uuid4().hex,
                binding.binding_id,
                terminal_status,
                error_category=category,
                started=False,
            )
            for binding in admission.snapshot.bindings
        )
        return DispatchReport(
            admission.event.event_id,
            admission.snapshot.generation,
            outcomes,
            elapsed_ms=int((time.monotonic() - admission.started) * 1_000),
            deadline_exhausted=deadline_exhausted,
        )

    @classmethod
    def _deadline_report(cls, admission: _DispatchAdmission) -> DispatchReport:
        """Build the terminal report for work that expired while still queued."""
        return cls._terminal_report(
            admission, "SKIPPED_DEADLINE", "deadline", deadline_exhausted=True
        )

    @classmethod
    def _cancelled_report(cls, admission: _DispatchAdmission) -> DispatchReport:
        """Build the terminal report for queued work cancelled by lifecycle close."""
        return cls._terminal_report(admission, "CANCELLED", "closed_scope")

    def _dispatch_guarded(self, admission: _DispatchAdmission) -> DispatchReport:
        """Dispatch one admitted snapshot with recursion and completion guards."""
        event = admission.event
        if getattr(self._local, "dispatching", False) or self._diagnostics.in_observer():
            return self._rejected(event, "rejected_context")
        self._local.dispatching = True
        try:
            report = self._dispatcher.dispatch(
                event,
                admission.snapshot,
                admission.timeout_ms,
                lambda: self._scope_is_open(event.scope_id),
                handler_timeout_ms=admission.handler_timeout_ms,
                started=admission.started,
                cancellation_requested=(
                    admission.cancellation_requested.is_set
                    if admission.cancellation_requested is not None
                    else None
                ),
            )
            self._diagnostics.publish(
                "dispatch_completed",
                event_id=event.event_id,
                scope_id=event.scope_id,
                generation=report.generation,
                outcome_count=len(report.outcomes),
                deadline_exhausted=report.deadline_exhausted,
                rejection_reason=report.rejection_reason,
            )
            return report
        except Exception as exc:
            self._diagnostics.publish(
                "dispatch_failed", event_id=event.event_id, error_category=type(exc).__name__
            )
            return self._rejected(event, "dispatcher_error")
        finally:
            self._local.dispatching = False

    def _admission_rejection(
        self,
        event: HookEvent,
        *,
        reject_running_loop: bool,
    ) -> DispatchReport | None:
        """Return a structured admission rejection without raising into business flow."""
        if type(event) is not HookEvent:
            return DispatchReport("", self._registry.generation, rejection_reason="invalid_event")
        if os.environ.get("TOPSAILAI_HOOK_WORKER") == "1":
            return self._rejected(event, "rejected_context")
        if self._diagnostics.in_observer() or getattr(self._local, "dispatching", False):
            return self._rejected(event, "rejected_context")
        if reject_running_loop:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                return self._rejected(event, "rejected_context")
        with self._lock:
            if self._state != "running":
                return self._rejected(event, "closed")
            scope_open = (
                event.scope_id in self._scopes
                and event.scope_id not in self._closing_scopes
            )
        if not self._settings.enabled:
            return self._rejected(event, "disabled")
        if not scope_open:
            return self._rejected(event, "closed_scope")
        return None

    def _close_scope(self, scope_id: str, deadline_ms: int | None) -> CloseReport:
        """Resume closing scope custody without cleanup observation under locks."""
        del deadline_ms
        with self._lock:
            already_closed = scope_id not in self._scopes or scope_id in self._closing_scopes
            scope_ids = () if scope_id not in self._scopes else self._scope_tree_ids(scope_id)
            self._closing_scopes.update(scope_ids)
        closed = self._close_scope_ids(scope_ids)
        return CloseReport(tuple(closed), self.cleanup_debts(), already_closed=already_closed)

    def _scope_tree_ids(self, scope_id: str) -> tuple[str, ...]:
        """Return one descendant-first scope tree while the owner lock is held."""
        scope_ids: list[str] = []
        for child_id in sorted(self._children.get(scope_id, ())):
            scope_ids.extend(self._scope_tree_ids(child_id))
        scope_ids.append(scope_id)
        return tuple(scope_ids)

    def _close_scope_ids(self, scope_ids: tuple[str, ...]) -> list[str]:
        """Release every marked scope registration and queued host operation."""
        closed: list[str] = []
        for scope_id in scope_ids:
            cancelled = self._scheduler.cancel_scope(scope_id)
            if cancelled:
                self._diagnostics.publish(
                    "dispatch_cancelled", scope_id=scope_id, cancelled_count=cancelled
                )
            self._scheduler.release_scope(scope_id)
            if not retire_configured_scope(self, scope_id):
                continue
            self._registry.unregister_scope(scope_id)
            with self._lock:
                for key in tuple(self._ordinary_sources):
                    if key[0] == scope_id:
                        del self._ordinary_sources[key]
                scope = self._scopes.pop(scope_id, None)
                self._children.pop(scope_id, None)
                self._sequences.pop(scope_id, None)
                self._closing_scopes.discard(scope_id)
                if scope is not None and scope.parent_id in self._children:
                    self._children[scope.parent_id].discard(scope_id)
            if scope is not None:
                closed.append(scope_id)
        return closed

    def _scope_is_open(self, scope_id: str) -> bool:
        """Return whether one scope still accepts or completes admitted work."""
        with self._lock:
            return (
                scope_id in self._scopes
                and scope_id not in self._closing_scopes
                and self._state in ("running", "closing")
            )

    def _owns_open_scope(self, scope: HookScope) -> bool:
        """Return whether one scope belongs to and remains open in this runtime."""
        return type(scope) is HookScope and scope._runtime is self and self._scope_is_open(scope.scope_id)

    @staticmethod
    def _policy_timeout(policy: Any, settings: HookSettings) -> int:
        """Resolve only an explicit positive timeout against captured settings."""
        default = settings.limits.dispatch_timeout_ms
        if policy is None:
            return default
        if type(policy) is int and policy > 0:
            return min(policy, default)
        if type(policy) is dict and set(policy) <= {"timeout_ms"}:
            value = policy.get("timeout_ms", default)
            if type(value) is int and value > 0:
                return min(value, default)
        return default

    def _observe_background_completion(
        self, work: ScheduledWork[DispatchReport], completed: object
    ) -> None:
        """Convert background host failure into safe diagnostics."""
        del completed
        try:
            work.future.result()
        except FutureCancelledError:
            return
        except BaseException as exc:
            self._diagnostics.publish(
                "dispatch_failed", scope_id=work.scope_id, error_category=type(exc).__name__
            )

    def _rejected(self, event: HookEvent, reason: str) -> DispatchReport:
        """Build one structured admission rejection."""
        return DispatchReport(event.event_id, self._registry.generation, rejection_reason=reason)

    @staticmethod
    def _admission_size(
        event: HookEvent, snapshot: RegistrySnapshot, payload: Any
    ) -> int:
        """Measure the bounded event and captured-plan admission envelope."""
        envelope = {
            "event": {
                "event_id": event.event_id,
                "name": event.name,
                "major_version": event.major_version,
                "owner_id": event.owner_id,
                "scope_id": event.scope_id,
                "operation_id": event.operation_id,
                "parent_operation_id": event.parent_operation_id,
                "sequence": event.sequence,
                "timestamp": event.timestamp,
                "layer": event.layer,
                "purpose": event.purpose,
                "payload": payload,
            },
            "generation": snapshot.generation,
            "bindings": [binding.binding_id for binding in snapshot.bindings],
        }
        return len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    @staticmethod
    def _deadline_ms(value: int | None, default: int) -> int:
        """Return a finite positive close deadline."""
        return value if type(value) is int and value > 0 else default
