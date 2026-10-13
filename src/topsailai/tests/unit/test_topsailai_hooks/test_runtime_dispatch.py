"""Focused tests for unified hook dispatch and runtime lifecycle."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookSettings
from topsailai.hooks.process_state import WorkerResult
from topsailai.tests.unit.test_topsailai_hooks.reload_helpers import (
    invoke_thread, join_owned, wait_for_queue,
)

HANDLERS = "topsailai.tests.unit.test_topsailai_hooks.fixture_handlers"


def _definition() -> EventDefinition:
    """Return the event contract used by runtime tests."""
    return EventDefinition(
        "test.dispatched",
        1,
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
    )


def _binding(binding_id: str, handler: str = "sync_success", **changes: object) -> Binding:
    """Return one valid runtime binding."""
    return replace(
        Binding(binding_id, "test.dispatched", 1, f"{HANDLERS}:{handler}"),
        **changes,
    )


def _runtime(tmp_path: Path, **limit_changes: int):
    """Build one explicitly owned runtime and scope."""
    from topsailai.hooks import HookRuntime

    defaults = {"workers": 2, "queue_items": 8, "dispatch_timeout_ms": 2_000}
    defaults.update(limit_changes)
    limits = replace(HookLimits(), **defaults)
    runtime = HookRuntime(HookSettings(limits=limits), temp_root=str(tmp_path))
    scope = runtime.open_scope(metadata={"owner_id": "owner-1"})
    return runtime, scope


def _event(runtime, scope, value: int = 1):
    """Create one validated event in the supplied scope."""
    return runtime.make_event(
        scope,
        "test.dispatched",
        1,
        {"value": value},
        operation_id="operation-1",
        layer="test",
        purpose="unit",
    )


def report_evidence(report, runtime):
    """Summarize finite outcome metadata and exact remaining cleanup obligations."""
    evidence = {
        "elapsed_ms": report.elapsed_ms, "deadline_exhausted": report.deadline_exhausted,
        "rejection_reason": report.rejection_reason, "remaining_budget_ms": "unknown",
        "outcomes": [(item.binding_id[:128], item.status.value, item.error_category,
            item.duration_ms, item.started) for item in report.outcomes[:16]],
        "outcome_count": len(report.outcomes), "cleanup_debt_count": len(runtime.cleanup_debts()),
    }
    print("HOOK_REPORT_EVIDENCE " + json.dumps(evidence, sort_keys=True))
    return evidence


def test_dispatch_executes_sync_async_and_custom_awaitable_in_plan_order(tmp_path: Path) -> None:
    """One dispatcher must execute every supported handler shape in stable plan order."""
    runtime, scope = _runtime(tmp_path, handler_timeout_ms=2250, dispatch_timeout_ms=7000)
    try:
        assert runtime.register(_definition(), _binding("sync", priority=30, timeout_ms=2250), scope).accepted
        assert runtime.register(
            _definition(), _binding("async", "async_success", priority=20, timeout_ms=2250), scope
        ).accepted
        assert runtime.register(
            _definition(), _binding("awaitable", "custom_awaitable_success", priority=10, timeout_ms=2250), scope
        ).accepted
        report = runtime.dispatch(_event(runtime, scope))
        assert [item.binding_id for item in report.outcomes] == ["awaitable", "async", "sync"]
        assert [item.status.value for item in report.outcomes] == ["success"] * 3, report_evidence(report, runtime)
        assert report.rejection_reason is None
    finally:
        runtime.close()


def test_dependencies_skip_only_required_success_and_preserve_independent_work(tmp_path: Path) -> None:
    """A failed handler must skip required successors without suppressing independent nodes."""
    runtime, scope = _runtime(tmp_path, handler_timeout_ms=2250, dispatch_timeout_ms=7000)
    try:
        assert runtime.register(_definition(), _binding("failed", "raise_exception", timeout_ms=2250), scope).accepted
        assert runtime.register(
            _definition(), _binding("after", after=("failed",), timeout_ms=2250), scope
        ).accepted
        assert runtime.register(
            _definition(), _binding("required", requires_success=("failed",), timeout_ms=2250), scope
        ).accepted
        assert runtime.register(_definition(), _binding("independent", timeout_ms=2250), scope).accepted
        report = runtime.dispatch(_event(runtime, scope))
        statuses = {item.binding_id: item.status.value for item in report.outcomes}
        assert statuses == {
            "after": "success",
            "failed": "error",
            "independent": "success",
            "required": "skipped_dependency",
        }, report_evidence(report, runtime)
    finally:
        runtime.close()


def test_invalid_event_exception_timeout_and_worker_cancellation_are_isolated(tmp_path: Path) -> None:
    """All plugin and event failures must remain structured reports."""
    runtime, scope = _runtime(tmp_path, handler_timeout_ms=2250, dispatch_timeout_ms=7000)
    try:
        for binding in (
            _binding("error", "raise_exception", timeout_ms=2250),
            _binding("invalid", "return_invalid_value", timeout_ms=2250),
            _binding("cancelled", "raise_cancelled", timeout_ms=2250),
            _binding("timeout", "block_forever", priority=1_000, timeout_ms=100),
        ):
            assert runtime.register(_definition(), binding, scope).accepted
        report = runtime.dispatch(_event(runtime, scope))
        statuses = {item.binding_id: item.status.value for item in report.outcomes}
        assert statuses["error"] == "error"
        assert statuses["invalid"] == "invalid_output"
        assert statuses["cancelled"] == "error"
        assert statuses["timeout"] in ("timeout", "skipped_deadline")

        invalid = replace(_event(runtime, scope), payload={"value": "wrong"})
        rejected = runtime.dispatch(invalid)
        assert rejected.rejection_reason == "invalid_event"
    finally:
        runtime.close()


def test_scope_lifecycle_is_owned_hierarchical_and_idempotent(tmp_path: Path) -> None:
    """Closing a parent must close descendants without closing unrelated scopes."""
    runtime, parent = _runtime(tmp_path, handler_timeout_ms=2250, dispatch_timeout_ms=2500)
    child = runtime.open_scope(parent=parent)
    sibling = runtime.open_scope()
    try:
        assert runtime.register(_definition(), _binding("parent", timeout_ms=2250), parent).accepted
        assert runtime.register(_definition(), _binding("child"), child).accepted
        assert runtime.register(_definition(), _binding("sibling", timeout_ms=2250), sibling).accepted
        child_event = _event(runtime, child)
        assert child.close().closed_scope_ids == (child.scope_id,)
        assert child.close().already_closed
        assert runtime.dispatch(child_event).rejection_reason == "closed_scope"
        assert runtime.dispatch(_event(runtime, parent)).outcomes[0].binding_id == "parent"
        assert parent.close().closed_scope_ids == (parent.scope_id,)
        assert runtime.dispatch(_event(runtime, sibling)).outcomes[0].status.value == "success"
    finally:
        runtime.close()


def test_parent_close_closes_open_descendants(tmp_path: Path) -> None:
    """Parent ownership must recursively settle child registration lifetimes."""
    runtime, parent = _runtime(tmp_path)
    child = runtime.open_scope(parent=parent)
    try:
        assert runtime.register(_definition(), _binding("child"), child).accepted
        child_event = _event(runtime, child)
        closed = parent.close()
        assert closed.closed_scope_ids == (child.scope_id, parent.scope_id)
        assert runtime.dispatch(child_event).rejection_reason == "closed_scope"
    finally:
        runtime.close()


def test_dispatch_completion_is_observable(tmp_path: Path) -> None:
    """Waiting dispatch must publish completion diagnostics before owned shutdown."""
    records: list[dict[str, object]] = []
    from topsailai.hooks import HookRuntime

    settings = HookSettings(
        limits=replace(HookLimits(), workers=1, queue_items=8, handler_timeout_ms=2250, dispatch_timeout_ms=2500)
    )
    runtime = HookRuntime(
        settings,
        temp_root=str(tmp_path),
        diagnostic_observer=lambda record: records.append(record),
    )
    scope = runtime.open_scope()
    try:
        assert runtime.register(_definition(), _binding("sync", timeout_ms=2250), scope).accepted
        report = runtime.dispatch(_event(runtime, scope))
        assert report.rejection_reason is None
        assert report.outcomes[0].status.value == "success"
        end = time.monotonic() + 2
        while time.monotonic() < end and not any(
            item.get("kind") == "dispatch_completed" for item in records
        ):
            time.sleep(0.01)
        assert any(item.get("kind") == "dispatch_completed" for item in records)
    finally:
        runtime.close()


def test_dispatch_rejects_running_loop_and_adispatch_keeps_loop_responsive(tmp_path: Path) -> None:
    """Sync dispatch must reject an event loop while async dispatch remains cooperative."""
    runtime, scope = _runtime(tmp_path, handler_timeout_ms=2250, dispatch_timeout_ms=2500)
    assert runtime.register(_definition(), _binding("sync", timeout_ms=2250), scope).accepted

    async def exercise() -> None:
        rejected = runtime.dispatch(_event(runtime, scope))
        assert rejected.rejection_reason == "rejected_context"
        ticks = 0
        task = asyncio.create_task(runtime.adispatch(_event(runtime, scope)))
        while not task.done():
            ticks += 1
            await asyncio.sleep(0.005)
        assert (await task).outcomes[0].status.value == "success"
        assert ticks > 0

    try:
        asyncio.run(exercise())
    finally:
        runtime.close()


def test_host_async_cancellation_propagates_after_owned_cleanup(tmp_path: Path) -> None:
    """Host cancellation must propagate after the isolated delivery reaches cleanup."""
    runtime, scope = _runtime(tmp_path, dispatch_timeout_ms=300)
    assert runtime.register(
        _definition(), _binding("blocked", "block_forever", timeout_ms=200), scope
    ).accepted

    async def exercise() -> None:
        task = asyncio.create_task(runtime.adispatch(_event(runtime, scope)))
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(exercise())
    finally:
        runtime.close()
    assert runtime.cleanup_debts() == ()


def test_reentrancy_and_diagnostic_callback_failures_never_escape(tmp_path: Path) -> None:
    """Recursive diagnostic publication and observer failures must be isolated."""
    calls = 0
    callback_failed = threading.Event()
    runtime_ref: list[object] = []

    def observer(record: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        runtime = runtime_ref[0]
        if record.get("kind") == "dispatch_completed":
            assert runtime.dispatch(_event(runtime, scope)).rejection_reason == "rejected_context"
        callback_failed.set()
        raise RuntimeError("observer failure")

    from topsailai.hooks import HookRuntime

    runtime = HookRuntime(HookSettings(limits=replace(HookLimits(), handler_timeout_ms=2250, dispatch_timeout_ms=2500)),
        temp_root=str(tmp_path), diagnostic_observer=observer)
    runtime_ref.append(runtime)
    scope = runtime.open_scope()
    try:
        assert runtime.register(_definition(), _binding("sync", timeout_ms=2250), scope).accepted
        assert runtime.dispatch(_event(runtime, scope)).outcomes[0].status.value == "success"
        assert callback_failed.wait(1)
        assert calls > 0
        records = runtime.drain_diagnostics(20)
        assert records
        assert any(record.get("kind") == "diagnostics_dropped" for record in records)
    finally:
        runtime.close()


def test_concurrent_dispatch_is_bounded_and_returns_complete_reports(tmp_path: Path) -> None:
    """Concurrent callers must share finite worker slots without corrupting reports."""
    runtime, scope = _runtime(tmp_path)
    assert runtime.register(_definition(), _binding("sync", max_concurrency=1), scope).accepted
    reports: list[object] = []
    lock = threading.Lock()

    def invoke(value: int) -> None:
        report = runtime.dispatch(_event(runtime, scope, value))
        with lock:
            reports.append(report)

    threads = [threading.Thread(target=invoke, args=(index,)) for index in range(4)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(4)
        assert all(not thread.is_alive() for thread in threads)
        assert len(reports) == 4
        assert all(
            report.outcomes[0].status.value in ("success", "rejected_capacity")
            for report in reports
        )
        assert any(report.outcomes[0].status.value == "success" for report in reports)
    finally:
        runtime.close()


class _BlockingBackend:
    """Provide deterministic admission and cancellation synchronization."""

    def __init__(self) -> None:
        """Create externally controlled execution gates."""
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def execute(self, handler_ref, context, timeout_ms):
        """Block one delivery until released or its finite deadline expires."""
        del handler_ref, context
        self.calls += 1
        self.started.set()
        if self.release.wait(timeout_ms / 1_000):
            return WorkerResult("success", value={"released": True})
        return WorkerResult("timeout", error_category="deadline")

    def cleanup_debts(self):
        """Return no process cleanup debt for the deterministic fake."""
        return ()


def test_dispatch_captures_snapshot_and_rejects_bounded_queue_overload(tmp_path: Path) -> None:
    """Owned waiting callers must freeze state and reject excess queued work."""
    from topsailai.hooks import HookRuntime

    backend = _BlockingBackend()
    limits = replace(
        HookLimits(),
        workers=1,
        queue_items=1,
        queue_bytes=1_024,
        dispatch_timeout_ms=1_000,
    )
    runtime = HookRuntime(
        HookSettings(limits=limits),
        temp_root=str(tmp_path),
        process_backend=backend,
    )
    scope = runtime.open_scope()
    owned = []
    try:
        registration = runtime.register(_definition(), _binding("blocked"), scope)
        assert registration.accepted
        first = invoke_thread(lambda: runtime.dispatch(_event(runtime, scope, 1)))
        owned.append(first)
        assert backend.started.wait(1)
        second = invoke_thread(lambda: runtime.dispatch(_event(runtime, scope, 2)))
        owned.append(second)
        wait_for_queue(runtime, 1)
        third = runtime.dispatch(_event(runtime, scope, 3))
        assert third.rejection_reason == "rejected_capacity"
        assert runtime.unregister(registration.handle).accepted
        backend.release.set()
        for thread, reports, errors in owned:
            join_owned(thread)
            assert errors == []
            assert reports[0].outcomes[0].binding_id == "blocked"
            assert reports[0].outcomes[0].status.value == "success"
        assert backend.calls == 2
    finally:
        backend.release.set()
        try:
            for thread, _, _ in owned:
                join_owned(thread)
        finally:
            runtime.close()
        for _, reports, errors in owned:
            assert errors == []
            assert len(reports) == 1
        assert runtime.cleanup_debts() == ()
        assert runtime._scheduler._work == {}


def test_scope_close_cancels_queued_dispatch_without_affecting_sibling(tmp_path: Path) -> None:
    """Scope closure must cancel queued owned work while preserving sibling admission."""
    from topsailai.hooks import HookRuntime

    backend = _BlockingBackend()
    limits = replace(HookLimits(), workers=1, queue_items=2, dispatch_timeout_ms=1_000)
    runtime = HookRuntime(
        HookSettings(limits=limits),
        temp_root=str(tmp_path),
        process_backend=backend,
    )
    scope = runtime.open_scope()
    sibling = runtime.open_scope()
    owned = []
    try:
        assert runtime.register(_definition(), _binding("owned"), scope).accepted
        assert runtime.register(_definition(), _binding("sibling"), sibling).accepted
        owned.append(invoke_thread(lambda: runtime.dispatch(_event(runtime, scope, 1))))
        assert backend.started.wait(1)
        owned.append(invoke_thread(lambda: runtime.dispatch(_event(runtime, scope, 2))))
        wait_for_queue(runtime, 1)
        scope.close()
        backend.release.set()
        end = time.monotonic() + 2
        cancelled = False
        while time.monotonic() < end and not cancelled:
            cancelled = any(
                item.get("kind") == "dispatch_cancelled"
                and item.get("scope_id") == scope.scope_id
                for item in runtime.drain_diagnostics(50)
            )
            if not cancelled:
                time.sleep(0.01)
        assert cancelled
        end = time.monotonic() + 2
        while time.monotonic() < end:
            sibling_report = runtime.dispatch(_event(runtime, sibling))
            if sibling_report.outcomes[0].status.value == "success":
                break
            time.sleep(0.01)
        else:
            pytest.fail("sibling dispatch capacity was not released")
    finally:
        backend.release.set()
        try:
            for thread, _, _ in owned:
                join_owned(thread)
        finally:
            runtime.close()
        for _, reports, errors in owned:
            assert errors == []
            assert len(reports) == 1
        assert runtime.cleanup_debts() == ()
        assert runtime._scheduler._work == {}


def test_host_cancellation_waits_for_owned_dispatch_settlement(tmp_path: Path) -> None:
    """Async host cancellation must not escape before owned delivery settlement."""
    from topsailai.hooks import HookRuntime

    backend = _BlockingBackend()
    limits = replace(HookLimits(), workers=1, dispatch_timeout_ms=1_000)
    runtime = HookRuntime(
        HookSettings(limits=limits),
        temp_root=str(tmp_path),
        process_backend=backend,
    )
    scope = runtime.open_scope()
    assert runtime.register(_definition(), _binding("blocked"), scope).accepted

    async def exercise() -> None:
        task = asyncio.create_task(runtime.adispatch(_event(runtime, scope)))
        await asyncio.to_thread(backend.started.wait, 1)
        task.cancel()
        await asyncio.sleep(0.03)
        assert not task.done()
        backend.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(exercise())
    finally:
        backend.release.set()
        runtime.close()


def test_disabled_runtime_is_worker_free_and_rejects_optional_work(tmp_path: Path) -> None:
    """A disabled runtime must create no executor and reject all optional work cheaply."""
    from topsailai.hooks import HookRuntime

    runtime = HookRuntime(HookSettings(enabled=False), temp_root=str(tmp_path))
    scope = runtime.open_scope()
    try:
        registration = runtime.register(_definition(), _binding("disabled"), scope)
        assert not registration.accepted
        assert runtime._scheduler._executor is None
        event = _event(runtime, scope)
        assert runtime.dispatch(event).rejection_reason == "disabled"
        assert asyncio.run(runtime.adispatch(event)).rejection_reason == "disabled"
    finally:
        runtime.close()


def test_queue_bytes_account_for_the_complete_admission_envelope(tmp_path: Path) -> None:
    """Waiting admission must bound metadata and captured plan as well as payload."""
    from topsailai.hooks import HookRuntime

    limits = replace(HookLimits(), queue_bytes=128, event_bytes=4_096)
    runtime = HookRuntime(HookSettings(limits=limits), temp_root=str(tmp_path))
    scope = runtime.open_scope()
    try:
        assert runtime.register(_definition(), _binding("sync"), scope).accepted
        report = runtime.dispatch(_event(runtime, scope))
        assert report.rejection_reason == "rejected_capacity"
    finally:
        runtime.close()


def test_scope_close_marks_the_complete_tree_before_releasing_registrations(
    tmp_path: Path,
) -> None:
    """Concurrent admission must reject a scope as soon as owner closure begins."""
    runtime, parent = _runtime(tmp_path)
    child = runtime.open_scope(parent=parent)
    assert runtime.register(_definition(), _binding("child"), child).accepted
    event = _event(runtime, child)
    entered = threading.Event()
    release = threading.Event()
    original_cancel = runtime._scheduler.cancel_scope

    def blocking_cancel(scope_id: str) -> int:
        entered.set()
        assert release.wait(1)
        return original_cancel(scope_id)

    runtime._scheduler.cancel_scope = blocking_cancel
    closer = threading.Thread(target=parent.close)
    try:
        closer.start()
        assert entered.wait(1)
        assert runtime.dispatch(event).rejection_reason == "closed_scope"
    finally:
        release.set()
        closer.join(2)
        runtime.close()
    assert not closer.is_alive()


class _CleanupDebtBackend:
    """Expose one unresolved cleanup debt and then a confirmed resolution."""

    def __init__(self) -> None:
        """Start with no debt and make the first execution uncertain."""
        self.calls = 0
        self.debt_active = False

    def execute(self, handler_ref, context, timeout_ms):
        """Return one uncertain cleanup result followed by normal successes."""
        del handler_ref, context, timeout_ms
        self.calls += 1
        if self.calls == 1:
            self.debt_active = True
            return WorkerResult(
                "worker_lost",
                error_category="cleanup_unconfirmed",
                cleanup_confirmed=False,
                cleanup_debt="debt-1",
            )
        return WorkerResult("success", value={"call": self.calls})

    def cleanup_debts(self):
        """Return the exact active debt identity without process details."""
        if not self.debt_active:
            return ()
        from topsailai.hooks.process_state import CleanupDebt

        return (CleanupDebt("debt-1", "pending", None, "test debt"),)


def test_unconfirmed_cleanup_quarantines_capacity_until_exact_debt_resolves(
    tmp_path: Path,
) -> None:
    """An uncertain worker must prevent replacement until its exact debt disappears."""
    from topsailai.hooks import HookRuntime

    backend = _CleanupDebtBackend()
    limits = replace(HookLimits(), workers=1, dispatch_timeout_ms=1_000)
    runtime = HookRuntime(
        HookSettings(limits=limits), temp_root=str(tmp_path), process_backend=backend
    )
    scope = runtime.open_scope()
    try:
        assert runtime.register(_definition(), _binding("owned"), scope).accepted
        first = runtime.dispatch(_event(runtime, scope, 1))
        assert first.outcomes[0].status.value == "worker_lost"
        second = runtime.dispatch(_event(runtime, scope, 2))
        assert second.outcomes[0].status.value == "rejected_capacity"
        backend.debt_active = False
        third = runtime.dispatch(_event(runtime, scope, 3))
        assert third.outcomes[0].status.value == "success"
    finally:
        backend.debt_active = False
        runtime.close()


def test_queued_scope_cancellation_emits_one_aggregate_diagnostic(tmp_path: Path) -> None:
    """One cancelled queued delivery must produce one aggregate cancellation record."""
    from topsailai.hooks import HookRuntime

    backend = _BlockingBackend()
    limits = replace(HookLimits(), workers=1, queue_items=2, dispatch_timeout_ms=1_000)
    runtime = HookRuntime(
        HookSettings(limits=limits), temp_root=str(tmp_path), process_backend=backend
    )
    scope = runtime.open_scope()
    owned = []
    try:
        assert runtime.register(_definition(), _binding("owned"), scope).accepted
        owned.append(invoke_thread(lambda: runtime.dispatch(_event(runtime, scope, 1))))
        assert backend.started.wait(1)
        owned.append(invoke_thread(lambda: runtime.dispatch(_event(runtime, scope, 2))))
        wait_for_queue(runtime, 1)
        scope.close()
        records = runtime.drain_diagnostics(50)
        cancellations = [
            record
            for record in records
            if record.get("kind") == "dispatch_cancelled"
            and record.get("scope_id") == scope.scope_id
        ]
        assert cancellations == [
            {
                "kind": "dispatch_cancelled",
                "scope_id": scope.scope_id,
                "cancelled_count": 1,
            }
        ]
    finally:
        backend.release.set()
        try:
            for thread, _, _ in owned:
                join_owned(thread)
        finally:
            runtime.close()
        for _, reports, errors in owned:
            assert errors == []
            assert len(reports) == 1
        assert runtime.cleanup_debts() == ()
        assert runtime._scheduler._work == {}


def test_host_cancellation_prevents_later_bindings_from_starting(tmp_path: Path) -> None:
    """Host cancellation must cancel unstarted deliveries before it propagates."""
    from topsailai.hooks import HookRuntime

    backend = _BlockingBackend()
    limits = replace(HookLimits(), workers=1, dispatch_timeout_ms=1_000)
    runtime = HookRuntime(
        HookSettings(limits=limits), temp_root=str(tmp_path), process_backend=backend
    )
    scope = runtime.open_scope()
    assert runtime.register(_definition(), _binding("first", priority=1), scope).accepted
    assert runtime.register(_definition(), _binding("second", priority=2), scope).accepted

    async def exercise() -> None:
        task = asyncio.create_task(runtime.adispatch(_event(runtime, scope)))
        await asyncio.to_thread(backend.started.wait, 1)
        task.cancel()
        backend.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(exercise())
        assert backend.calls == 1
    finally:
        backend.release.set()
        runtime.close()


def test_scope_close_releases_scheduler_scope_state(tmp_path: Path) -> None:
    """Closing a scope must release its per-binding scheduler bookkeeping."""
    runtime, scope = _runtime(tmp_path, handler_timeout_ms=2250, dispatch_timeout_ms=2500)
    try:
        assert runtime.register(_definition(), _binding("sync", timeout_ms=2250), scope).accepted
        assert runtime.dispatch(_event(runtime, scope)).outcomes[0].status.value == "success"
        assert any(key[0] == scope.scope_id for key in runtime._scheduler._binding_slots)
        scope.close()
        assert all(key[0] != scope.scope_id for key in runtime._scheduler._binding_slots)
    finally:
        runtime.close()
