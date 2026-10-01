"""Deterministic helpers for operational Hooks reload RED contracts."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookRuntime, HookSettings
from topsailai.hooks.process_state import CleanupDebt, WorkerResult

HANDLER_REF = "topsailai.tests.unit.test_topsailai_hooks.fixture_handlers:sync_success"


def settings(*, enabled: bool = True, **changes: int) -> HookSettings:
    """Build valid settings with explicit finite test limits."""
    defaults = {
        "workers": 1,
        "queue_items": 4,
        "queue_bytes": 65_536,
        "event_bytes": 4_096,
        "bindings_per_event": 4,
        "handler_timeout_ms": 800,
        "dispatch_timeout_ms": 1_000,
        "shutdown_timeout_ms": 100,
    }
    defaults.update(changes)
    return HookSettings(enabled=enabled, limits=replace(HookLimits(), **defaults))


def definition() -> EventDefinition:
    """Return the reload test event definition."""
    return EventDefinition(
        "test.reload",
        1,
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
    )


def binding(binding_id: str = "reload", **changes: object) -> Binding:
    """Return one valid reload test binding."""
    return replace(
        Binding(binding_id, "test.reload", 1, HANDLER_REF, timeout_ms=900),
        **changes,
    )


def runtime_scope(
    tmp_path: Path,
    *,
    initial: HookSettings | None = None,
    backend: Any | None = None,
) -> tuple[HookRuntime, Any]:
    """Create one explicitly owned runtime and scope."""
    runtime = HookRuntime(
        initial or settings(),
        temp_root=str(tmp_path),
        process_backend=backend,
    )
    return runtime, runtime.open_scope(metadata={"owner_id": "reload-owner"})


def event(runtime: HookRuntime, scope: Any, value: int = 1) -> Any:
    """Create one valid reload event."""
    return runtime.make_event(
        scope,
        "test.reload",
        1,
        {"value": value},
        operation_id=f"reload-operation-{value}",
        layer="test",
        purpose="reload-red",
    )


def reload_runtime(runtime: HookRuntime, candidate: object) -> Any:
    """Require the future public reload API inside a test body."""
    reload_method = getattr(runtime, "reload", None)
    assert callable(reload_method), (
        "R3 operational contract missing: HookRuntime.reload(HookSettings) -> ReloadResult"
    )
    return reload_method(candidate)


def assert_reload_result(
    result: Any,
    *,
    accepted: bool,
    generation: int | None = None,
) -> None:
    """Assert the public structured reload result contract."""
    assert type(result).__name__ == "ReloadResult"
    assert result.accepted is accepted
    assert type(result.generation) is int
    assert type(result.errors) is tuple
    if generation is not None:
        assert result.generation == generation


def wait_for_queue(runtime: HookRuntime, items: int, timeout: float = 1.0) -> None:
    """Wait for an exact queue reservation at the real scheduler boundary."""
    deadline = time.monotonic() + timeout
    with runtime._scheduler._changed:
        reached = runtime._scheduler._changed.wait_for(
            lambda: runtime._scheduler._queued_items == items,
            max(0.0, deadline - time.monotonic()),
        )
    assert reached, f"queue did not reach {items} item(s)"


def invoke_thread(target: Callable[[], Any]) -> tuple[threading.Thread, list[Any], list[BaseException]]:
    """Start one owned call and retain its result and exception."""
    results: list[Any] = []
    errors: list[BaseException] = []

    def invoke() -> None:
        """Capture all outcomes for owner-thread assertions."""
        try:
            results.append(target())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    return thread, results, errors


def join_owned(thread: threading.Thread, timeout: float = 2.0) -> None:
    """Join one owned thread with an explicit anti-hang bound."""
    thread.join(timeout)
    assert not thread.is_alive(), "owned reload test thread did not terminate"


class GatedRecordingBackend:
    """Record immutable delivery inputs behind deterministic per-call gates."""

    def __init__(self) -> None:
        """Create call observation and release controls."""
        self.started = threading.Event()
        self.release = threading.Event()
        self.second_started = threading.Event()
        self._changed = threading.Condition()
        self.calls: list[tuple[Any, int]] = []
        self.active = 0

    def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
        """Record the context and timeout, then wait for owned release."""
        del handler_ref
        with self._changed:
            self.calls.append((context, timeout_ms))
            self.active += 1
            call_number = len(self.calls)
            self._changed.notify_all()
        self.started.set()
        if call_number > 1:
            self.second_started.set()
        try:
            if self.release.wait(timeout_ms / 1_000):
                return WorkerResult("success", value={"call": call_number})
            return WorkerResult("timeout", error_category="deadline")
        finally:
            with self._changed:
                self.active -= 1
                self._changed.notify_all()

    def wait_calls(self, count: int, timeout: float = 1.0) -> bool:
        """Wait until an exact minimum number of calls has started."""
        with self._changed:
            return self._changed.wait_for(lambda: len(self.calls) >= count, timeout)

    def cleanup_debts(self) -> tuple[()]:
        """Return no process cleanup debt for this in-memory backend."""
        return ()


class QuarantineBackend:
    """Produce exact cleanup debts for dynamic worker-capacity contracts."""

    def __init__(self) -> None:
        """Create debt and call state."""
        self.calls = 0
        self.active_debts: set[str] = set()

    def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
        """Return an unresolved exact debt for each invocation."""
        del handler_ref, context, timeout_ms
        self.calls += 1
        debt_id = f"reload-debt-{self.calls}"
        self.active_debts.add(debt_id)
        return WorkerResult(
            "worker_lost",
            error_category="cleanup_unconfirmed",
            cleanup_confirmed=False,
            cleanup_debt=debt_id,
        )

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Expose every unresolved exact debt."""
        return tuple(
            CleanupDebt(debt_id, "pending", None, "reload test debt")
            for debt_id in sorted(self.active_debts)
        )
