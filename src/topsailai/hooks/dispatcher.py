"""Deterministic bounded dispatch for the unified hooks runtime."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from typing import Callable

from topsailai.hooks.contracts import (
    DispatchReport,
    HookContext,
    HookEvent,
    HookOutcome,
    HookStatus,
    RegistrySnapshot,
    ValidationError,
)
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import WorkerResult
from topsailai.hooks.scheduler import HookScheduler
from topsailai.hooks.validation import validate_payload

_STATUS_MAP = {
    "success": HookStatus.SUCCESS,
    "error": HookStatus.ERROR,
    "timeout": HookStatus.TIMEOUT,
    "invalid_output": HookStatus.INVALID_OUTPUT,
    "worker_lost": HookStatus.WORKER_LOST,
    "cancelled": HookStatus.CANCELLED,
    "rejected_capacity": HookStatus.REJECTED_CAPACITY,
    "unsupported_backend": HookStatus.WORKER_LOST,
    "invalid_request": HookStatus.INVALID_OUTPUT,
}


class HookDispatcher:
    """Dispatch one immutable registry snapshot through isolated worker processes."""

    def __init__(
        self,
        backend: IsolatedProcessBackend,
        scheduler: HookScheduler,
        publish_diagnostic: Callable[..., None],
    ) -> None:
        """Bind explicit backend, scheduler, and safe diagnostic publication."""
        self._backend = backend
        self._scheduler = scheduler
        self._publish = publish_diagnostic

    def dispatch(
        self,
        event: HookEvent,
        snapshot: RegistrySnapshot,
        timeout_ms: int,
        scope_is_open: Callable[[], bool],
        *,
        handler_timeout_ms: int | None = None,
        started: float | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> DispatchReport:
        """Return a stable report while isolating every plugin-origin failure."""
        started = time.monotonic() if started is None else started
        try:
            if snapshot.definition is None:
                return self._report(event, snapshot, started, rejection_reason="invalid_event")
            payload = validate_payload(snapshot.definition, event.payload)
        except (ValidationError, ValueError, TypeError):
            return self._report(event, snapshot, started, rejection_reason="invalid_event")
        if not scope_is_open():
            return self._report(event, snapshot, started, rejection_reason="closed_scope")

        deadline = started + timeout_ms / 1_000
        outcomes: dict[str, HookOutcome] = {}
        for binding in snapshot.bindings:
            delivery_id = uuid.uuid4().hex
            if cancellation_requested is not None and cancellation_requested():
                outcomes[binding.binding_id] = self._outcome(
                    delivery_id, binding.binding_id, HookStatus.CANCELLED, "host_cancelled"
                )
                continue
            if not scope_is_open():
                outcomes[binding.binding_id] = self._outcome(
                    delivery_id, binding.binding_id, HookStatus.CANCELLED, "closed_scope"
                )
                continue
            failed_requirements = [
                dependency
                for dependency in binding.requires_success
                if outcomes.get(dependency) is None
                or outcomes[dependency].status is not HookStatus.SUCCESS
            ]
            if failed_requirements:
                outcomes[binding.binding_id] = self._outcome(
                    delivery_id,
                    binding.binding_id,
                    HookStatus.SKIPPED_DEPENDENCY,
                    "required_predecessor_failed",
                )
                continue
            remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1_000)
            if remaining_ms <= 0:
                outcomes[binding.binding_id] = self._outcome(
                    delivery_id, binding.binding_id, HookStatus.SKIPPED_DEADLINE, "deadline"
                )
                continue
            if not binding.enabled:
                outcomes[binding.binding_id] = self._outcome(
                    delivery_id, binding.binding_id, HookStatus.SKIPPED_DISABLED, "disabled"
                )
                continue
            allowed_event = event
            if binding.allowed_payload_fields is not None:
                filtered = {
                    key: value
                    for key, value in payload.items()
                    if key in binding.allowed_payload_fields
                }
                allowed_event = replace(event, payload=filtered)
            effective_handler_ms = min(
                remaining_ms,
                binding.timeout_ms,
                handler_timeout_ms if handler_timeout_ms is not None else binding.timeout_ms,
            )
            context = HookContext(
                allowed_event,
                delivery_id,
                binding.binding_id,
                snapshot.generation,
                effective_handler_ms,
            )
            delivery_started = time.monotonic()
            backend_started = False

            def execute_backend() -> WorkerResult:
                """Record the exact boundary where backend execution begins."""
                nonlocal backend_started
                backend_started = True
                return self._backend.execute(
                    binding.handler_ref,
                    context,
                    effective_handler_ms,
                )

            try:
                self._scheduler.reconcile_cleanup_debts(
                    {debt.debt_id for debt in self._backend.cleanup_debts()}
                )
                result = self._scheduler.execute(
                    event.scope_id,
                    binding.binding_id,
                    binding.max_concurrency,
                    execute_backend,
                )
            except Exception as exc:
                result = WorkerResult("worker_lost", error_category=type(exc).__name__)
            duration_ms = int((time.monotonic() - delivery_started) * 1_000)
            late_result_discarded = not scope_is_open()
            if late_result_discarded:
                outcome = HookOutcome(
                    delivery_id,
                    binding.binding_id,
                    HookStatus.CANCELLED,
                    duration_ms=duration_ms,
                    error_category="closed_scope",
                    started=backend_started,
                )
            else:
                outcome = self._worker_outcome(
                    delivery_id,
                    binding.binding_id,
                    result,
                    duration_ms,
                    backend_started,
                )
            outcomes[binding.binding_id] = outcome
            self._publish(
                "delivery_completed",
                event_name=event.name,
                binding_id=binding.binding_id,
                generation=snapshot.generation,
                scope_id=event.scope_id,
                status=outcome.status.value,
                duration_ms=outcome.duration_ms,
            )
            if late_result_discarded:
                self._publish(
                    "late_result_discarded",
                    event_name=event.name,
                    binding_id=binding.binding_id,
                    generation=snapshot.generation,
                    scope_id=event.scope_id,
                    error_category="closed_scope",
                )
        ordered = tuple(outcomes[binding.binding_id] for binding in snapshot.bindings)
        return DispatchReport(
            event.event_id,
            snapshot.generation,
            ordered,
            int((time.monotonic() - started) * 1_000),
            time.monotonic() >= deadline,
        )

    @staticmethod
    def _worker_outcome(
        delivery_id: str,
        binding_id: str,
        result: WorkerResult,
        duration_ms: int,
        started: bool,
    ) -> HookOutcome:
        """Convert one internal worker result into the public immutable outcome."""
        status = _STATUS_MAP.get(result.status, HookStatus.WORKER_LOST)
        return HookOutcome(
            delivery_id,
            binding_id,
            status,
            value=result.value,
            duration_ms=duration_ms,
            error_category=result.error_category,
            started=started,
        )

    @staticmethod
    def _outcome(
        delivery_id: str,
        binding_id: str,
        status: HookStatus,
        category: str,
    ) -> HookOutcome:
        """Build a non-started terminal scheduler outcome."""
        return HookOutcome(
            delivery_id,
            binding_id,
            status,
            error_category=category,
            started=False,
        )

    @staticmethod
    def _report(
        event: HookEvent,
        snapshot: RegistrySnapshot,
        started: float,
        *,
        rejection_reason: str,
    ) -> DispatchReport:
        """Build a bounded rejected report."""
        return DispatchReport(
            event.event_id,
            snapshot.generation,
            elapsed_ms=int((time.monotonic() - started) * 1_000),
            rejection_reason=rejection_reason,
        )
