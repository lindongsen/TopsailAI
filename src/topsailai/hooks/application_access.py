"""Application-scoped access to one configured Hook executor."""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.contracts import DispatchReport
from topsailai.hooks.hook_point_catalog import HookPointDeclaration


@dataclass(frozen=True, slots=True)
class _Binding:
    """Bind an application to the thread that established its context."""

    application: "HookApplicationAccess | None"
    thread_id: int


_current_application: contextvars.ContextVar[_Binding | None] = contextvars.ContextVar(
    "topsailai_hook_application", default=None
)


class HookApplicationAccess:
    """Own admission state for one already-constructed application executor."""

    def __init__(self, executor: ConfiguredHookExecutor | None) -> None:
        """Validate and retain an existing configured executor without creating one."""
        if executor is not None and type(executor) is not ConfiguredHookExecutor:
            raise ValueError("invalid Hook application access")
        self._executor = executor
        self._lock = threading.Lock()
        self._admission_stopped = False
        self._in_flight = 0

    def stop_admission(self) -> None:
        """Stop new forwarding while leaving admitted work to the executor."""
        with self._lock:
            self._admission_stopped = True

    def _closed(self) -> bool:
        """Read the existing Scope state without owning or closing it."""
        return bool(self._executor._scope.closed)

    def _enter(self) -> str | None:
        """Reserve one forwarding slot or return its stable unavailable reason."""
        with self._lock:
            if self._admission_stopped or self._closed():
                return "application_closed"
            self._in_flight += 1
            return None

    def _leave(self) -> None:
        """Release one forwarding slot after the existing executor settles."""
        with self._lock:
            self._in_flight -= 1


class HookExecutorAccess:
    """Forwarding facade bound to one exact ContextVar binding."""

    def __init__(self, binding: _Binding | None) -> None:
        """Capture the binding so a cached facade cannot change owners."""
        self._binding = binding
        self._thread_id = threading.get_ident()

    def _validate(
        self, point: HookPointDeclaration, mode: str
    ) -> tuple[HookApplicationAccess | None, str | None]:
        """Validate declaration authority, owner identity, thread, and state."""
        if type(point) is not HookPointDeclaration:
            raise ValueError("invalid Hook-point declaration")
        if point.mode != mode:
            raise ValueError("Hook-point execution mode mismatch")
        binding = self._binding
        if binding is None:
            return None, "application_unbound"
        application = binding.application
        if application is not None and application._executor is not None:
            # Validate Catalog authority before any unavailable-state report.
            application._executor._require_point(point, mode)
        current = _current_application.get()
        current_thread = threading.get_ident()
        if (
            current is not binding
            or current_thread != binding.thread_id
            or current_thread != self._thread_id
        ):
            return application, "application_context_mismatch"
        if application is None or application._executor is None:
            return application, "application_disabled"
        return application, None

    @staticmethod
    def _report(point: HookPointDeclaration, reason: str) -> DispatchReport:
        """Create the bounded no-event report and enforce authorized blocking policy."""
        report = DispatchReport("", 0, rejection_reason=reason)
        if point.failure_policy == "block":
            ConfiguredHookExecutor._enforce_policy(point, report)
        return report

    def dispatch(
        self,
        point: HookPointDeclaration,
        *,
        payload: Any,
        operation: Any = None,
        cancellation: threading.Event | None = None,
    ) -> DispatchReport:
        """Forward one synchronous dispatch without holding access state across execution."""
        application, reason = self._validate(point, "sync")
        if reason is not None:
            return self._report(point, reason)
        assert application is not None
        reason = application._enter()
        if reason is not None:
            return self._report(point, reason)
        try:
            return application._executor.dispatch(
                point, payload=payload, operation=operation, cancellation=cancellation
            )
        finally:
            application._leave()

    async def adispatch(
        self,
        point: HookPointDeclaration,
        *,
        payload: Any,
        operation: Any = None,
    ) -> DispatchReport:
        """Forward one asynchronous dispatch after execution-time context validation."""
        application, reason = self._validate(point, "async")
        if reason is not None:
            return self._report(point, reason)
        assert application is not None
        reason = application._enter()
        if reason is not None:
            return self._report(point, reason)
        try:
            return await application._executor.adispatch(
                point, payload=payload, operation=operation
            )
        finally:
            application._leave()


@contextmanager
def bind_hook_application(application: HookApplicationAccess) -> Iterator[None]:
    """Bind one application to the current context and restore it exactly on exit."""
    if type(application) is not HookApplicationAccess:
        raise ValueError("invalid Hook application access")
    binding = _Binding(application, threading.get_ident())
    token = _current_application.set(binding)
    try:
        yield
    finally:
        _current_application.reset(token)


def get_hook_executor() -> HookExecutorAccess:
    """Return a facade bound to the current application context, if any."""
    return HookExecutorAccess(_current_application.get())
