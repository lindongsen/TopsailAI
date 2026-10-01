"""Shared deterministic helpers for unified Hooks runtime RED tests."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookRuntime, HookSettings
from topsailai.hooks.process_state import WorkerResult

HANDLERS = "topsailai.tests.unit.test_topsailai_hooks.fixture_handlers"


def definition() -> EventDefinition:
    """Return the event definition shared by the RED tests."""
    return EventDefinition(
        "test.red",
        1,
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
    )


def binding(binding_id: str = "blocked", **changes: object) -> Binding:
    """Return one valid binding for the RED tests."""
    value = Binding(binding_id, "test.red", 1, f"{HANDLERS}:sync_success")
    return replace(value, **changes)


def runtime_and_scope(
    tmp_path: Path,
    *,
    backend: Any | None = None,
    observer: Any | None = None,
    **limit_changes: int,
):
    """Build an explicitly owned runtime and one registered scope."""
    defaults = {
        "workers": 1,
        "queue_items": 2,
        "queue_bytes": 16_384,
        "dispatch_timeout_ms": 1_000,
        "shutdown_timeout_ms": 50,
    }
    defaults.update(limit_changes)
    settings = HookSettings(limits=replace(HookLimits(), **defaults))
    runtime = HookRuntime(
        settings,
        temp_root=str(tmp_path),
        process_backend=backend,
        diagnostic_observer=observer,
    )
    scope = runtime.open_scope(metadata={"owner_id": "red-owner"})
    return runtime, scope


def event(runtime: HookRuntime, scope: Any, value: int = 1):
    """Create one valid immutable event."""
    return runtime.make_event(
        scope,
        "test.red",
        1,
        {"value": value},
        operation_id=f"operation-{value}",
        layer="test",
        purpose="red",
    )


class BlockingBackend:
    """Block each backend call behind externally controlled events."""

    def __init__(self) -> None:
        """Create call, activity, completion, and release controls."""
        self.started = threading.Event()
        self.release = threading.Event()
        self.second_started = threading.Event()
        self.completed = threading.Event()
        self._changed = threading.Condition()
        self.calls = 0
        self.active = 0
        self.completed_calls = 0

    def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
        """Wait for release while retaining deterministic lifecycle evidence."""
        del handler_ref, context
        with self._changed:
            self.completed.clear()
            self.calls += 1
            self.active += 1
            call_number = self.calls
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
                self.completed_calls += 1
                if self.active == 0:
                    self.completed.set()
                self._changed.notify_all()

    def snapshot(self) -> tuple[int, int, int]:
        """Return started, active, and completed call counts under one lock."""
        with self._changed:
            return self.calls, self.active, self.completed_calls

    def wait_idle(self, timeout: float) -> bool:
        """Wait boundedly until every started call has completed."""
        with self._changed:
            return self._changed.wait_for(
                lambda: self.active == 0 and self.completed_calls == self.calls,
                timeout,
            )

    def cleanup_debts(self) -> tuple[()]:
        """Return no process cleanup debt for this in-memory fake."""
        return ()
