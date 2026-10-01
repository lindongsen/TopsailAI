"""RED contracts for dynamic Hooks reload queue and worker capacity."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from topsailai.tests.unit.test_topsailai_hooks.reload_helpers import (
    GatedRecordingBackend,
    QuarantineBackend,
    assert_reload_result,
    binding,
    definition,
    event,
    invoke_thread,
    join_owned,
    reload_runtime,
    runtime_scope,
    settings,
    wait_for_queue,
)


@pytest.mark.parametrize("dimension", ["items", "bytes"])
def test_queue_capacity_shrink_preserves_waiters_and_rejects_only_new_reservations(
    tmp_path: Path, dimension: str
) -> None:
    """Queue shrink must retain admitted owners until the changed counter recovers."""
    backend = GatedRecordingBackend()
    initial = settings(queue_items=4, queue_bytes=65_536)
    runtime, scope = runtime_scope(tmp_path, initial=initial, backend=backend)
    threads: list[threading.Thread] = []
    errors: list[BaseException] = []
    try:
        assert runtime.register(definition(), binding(), scope).accepted
        running, _, running_errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope, 1))
        )
        threads.append(running)
        errors.extend(running_errors)
        assert backend.started.wait(1)
        queued_event = event(runtime, scope, 2)
        admission, rejection = runtime._prepare_admission(queued_event, None)
        assert rejection is None and admission is not None
        queued, _, queued_errors = invoke_thread(
            lambda: runtime.dispatch(queued_event)
        )
        threads.append(queued)
        errors.extend(queued_errors)
        wait_for_queue(runtime, 1)
        changes = (
            {"queue_items": 1, "queue_bytes": 65_536}
            if dimension == "items"
            else {"queue_items": 4, "queue_bytes": admission.size_bytes}
        )
        changed = reload_runtime(runtime, settings(**changes))
        assert_reload_result(changed, accepted=True)
        rejected = runtime.emit(event(runtime, scope, 3))
        assert not rejected.admitted
        assert rejected.rejection_reason == "rejected_capacity"
        with runtime._scheduler._lock:
            assert len(runtime._scheduler._work) == 2
            assert runtime._scheduler._queued_items == 1
            assert runtime._scheduler._queued_bytes == admission.size_bytes
        backend.release.set()
        for thread in threads:
            join_owned(thread)
        assert errors == []
        assert len(backend.calls) == 2
    finally:
        backend.release.set()
        for thread in threads:
            join_owned(thread)
        runtime.close(deadline_ms=100)


def test_queue_capacity_increase_allows_admission_after_atomic_publication(
    tmp_path: Path,
) -> None:
    """Increasing queue capacity must admit later work without replacing scheduler ownership."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(
        tmp_path,
        initial=settings(queue_items=1, queue_bytes=65_536),
        backend=backend,
    )
    threads: list[threading.Thread] = []
    try:
        assert runtime.register(definition(), binding(), scope).accepted
        first, _, _ = invoke_thread(lambda: runtime.dispatch(event(runtime, scope, 1)))
        threads.append(first)
        assert backend.started.wait(1)
        second, _, _ = invoke_thread(lambda: runtime.dispatch(event(runtime, scope, 2)))
        threads.append(second)
        wait_for_queue(runtime, 1)
        scheduler_identity = id(runtime._scheduler)
        assert not runtime.emit(event(runtime, scope, 3)).admitted
        changed = reload_runtime(runtime, settings(queue_items=2, queue_bytes=65_536))
        assert_reload_result(changed, accepted=True)
        assert id(runtime._scheduler) == scheduler_identity
        assert runtime.emit(event(runtime, scope, 4)).admitted
        wait_for_queue(runtime, 2)
    finally:
        backend.release.set()
        for thread in threads:
            join_owned(thread)
        runtime.close(deadline_ms=100)


def test_queue_expiry_after_reload_releases_exact_reservation_without_late_start(
    tmp_path: Path,
) -> None:
    """Reload must not alter an admitted absolute deadline or allow expired late start."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(tmp_path, backend=backend)
    threads: list[threading.Thread] = []
    reports: list[Any] = []
    errors: list[BaseException] = []
    try:
        assert runtime.register(definition(), binding(), scope).accepted
        first, _, first_errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope, 1))
        )
        threads.append(first)
        errors.extend(first_errors)
        assert backend.started.wait(1)
        second, second_reports, second_errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope, 2), {"timeout_ms": 60})
        )
        threads.append(second)
        reports.extend(second_reports)
        errors.extend(second_errors)
        wait_for_queue(runtime, 1)
        changed = reload_runtime(runtime, settings(dispatch_timeout_ms=2_000))
        assert_reload_result(changed, accepted=True)
        join_owned(second)
        assert second_errors == []
        assert second_reports[0].outcomes[0].status.value == "skipped_deadline"
        with runtime._scheduler._lock:
            assert runtime._scheduler._queued_items == 0
            assert runtime._scheduler._queued_bytes == 0
        backend.release.set()
        join_owned(first)
        assert len(backend.calls) == 1
        assert not backend.second_started.is_set()
    finally:
        backend.release.set()
        for thread in threads:
            join_owned(thread)
        runtime.close(deadline_ms=100)


def test_worker_capacity_shrink_keeps_old_waiters_until_active_use_falls_below_cap(
    tmp_path: Path,
) -> None:
    """Worker shrink must not consume old queued work merely to reject its backend start."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(
        tmp_path,
        initial=settings(workers=2, queue_items=4),
        backend=backend,
    )
    threads: list[threading.Thread] = []
    try:
        assert runtime.register(
            definition(), binding(max_concurrency=3), scope
        ).accepted
        for value in (1, 2):
            thread, _, _ = invoke_thread(
                lambda current=value: runtime.dispatch(event(runtime, scope, current))
            )
            threads.append(thread)
        assert backend.wait_calls(2)
        changed = reload_runtime(runtime, settings(workers=1, queue_items=4))
        assert_reload_result(changed, accepted=True)
        third, _, third_errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope, 3))
        )
        threads.append(third)
        wait_for_queue(runtime, 1)
        assert len(backend.calls) == 2
        assert runtime.emit(event(runtime, scope, 4)).admitted
        wait_for_queue(runtime, 2)
        backend.release.set()
        for thread in threads:
            join_owned(thread)
        assert third_errors == []
        assert len(backend.calls) >= 3
    finally:
        backend.release.set()
        for thread in threads:
            join_owned(thread)
        runtime.close(deadline_ms=100)


def test_worker_capacity_increase_does_not_replace_or_multiply_scheduler(
    tmp_path: Path,
) -> None:
    """Worker increase must reconfigure one authority and permit later concurrent starts."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(tmp_path, backend=backend)
    threads: list[threading.Thread] = []
    try:
        assert runtime.register(
            definition(), binding(max_concurrency=2), scope
        ).accepted
        first, _, _ = invoke_thread(lambda: runtime.dispatch(event(runtime, scope, 1)))
        threads.append(first)
        assert backend.started.wait(1)
        second, _, _ = invoke_thread(lambda: runtime.dispatch(event(runtime, scope, 2)))
        threads.append(second)
        wait_for_queue(runtime, 1)
        scheduler_identity = id(runtime._scheduler)
        changed = reload_runtime(runtime, settings(workers=2))
        assert_reload_result(changed, accepted=True)
        assert id(runtime._scheduler) == scheduler_identity
        assert backend.wait_calls(2)
    finally:
        backend.release.set()
        for thread in threads:
            join_owned(thread)
        runtime.close(deadline_ms=100)


def test_initial_worker_start_failure_releases_exact_queue_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first worker start failure must reject without retained work or phantom workers."""
    runtime, scope = runtime_scope(tmp_path)
    original_start = threading.Thread.start

    def fail_hook_worker_start(thread: threading.Thread) -> None:
        """Fail only scheduler worker startup while preserving the test runner thread."""
        if thread.name.startswith("hook-delivery-"):
            raise RuntimeError("injected worker start failure")
        original_start(thread)

    try:
        assert runtime.register(definition(), binding(), scope).accepted
        generation = runtime._registry.generation
        monkeypatch.setattr(threading.Thread, "start", fail_hook_worker_start)
        report = runtime.dispatch(event(runtime, scope))
        assert report.rejection_reason == "rejected_capacity"
        assert runtime._registry.generation == generation
        with runtime._scheduler._lock:
            assert runtime._scheduler._executor == ()
            assert runtime._scheduler._work == {}
            assert tuple(runtime._scheduler._waiting) == ()
            assert runtime._scheduler._queued_items == 0
            assert runtime._scheduler._queued_bytes == 0
    finally:
        monkeypatch.setattr(threading.Thread, "start", original_start)
        runtime.close(deadline_ms=100)


def test_partial_worker_growth_failure_rejects_reload_without_mixed_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial growth failure must retain only started workers and old published limits."""
    backend = GatedRecordingBackend()
    initial = settings(workers=1)
    runtime, scope = runtime_scope(tmp_path, initial=initial, backend=backend)
    dispatch_threads: list[threading.Thread] = []
    started_growth: list[threading.Thread] = []
    original_start = threading.Thread.start
    hook_start_calls = 0

    def partially_fail_growth(thread: threading.Thread) -> None:
        """Start one growth worker and fail the next candidate deterministically."""
        nonlocal hook_start_calls
        if thread.name.startswith("hook-delivery-"):
            hook_start_calls += 1
            if hook_start_calls == 2:
                raise RuntimeError("injected partial worker start failure")
            original_start(thread)
            started_growth.append(thread)
            return
        original_start(thread)

    try:
        assert runtime.register(
            definition(), binding(max_concurrency=2), scope
        ).accepted
        first, _, _ = invoke_thread(lambda: runtime.dispatch(event(runtime, scope, 1)))
        dispatch_threads.append(first)
        assert backend.started.wait(1)
        second, _, _ = invoke_thread(lambda: runtime.dispatch(event(runtime, scope, 2)))
        dispatch_threads.append(second)
        wait_for_queue(runtime, 1)
        generation = runtime._registry.generation
        scheduler_identity = id(runtime._scheduler)
        monkeypatch.setattr(threading.Thread, "start", partially_fail_growth)
        rejected = reload_runtime(runtime, settings(workers=3))
        assert_reload_result(rejected, accepted=False, generation=generation)
        assert rejected.errors == ("worker start failed",)
        assert runtime._settings == initial
        assert id(runtime._scheduler) == scheduler_identity
        with runtime._scheduler._lock:
            assert runtime._scheduler._worker_limit == 1
            assert len(runtime._scheduler._executor) == 2
            assert all(thread.ident is not None for thread in runtime._scheduler._executor)
            assert runtime._scheduler._queued_items == 1
    finally:
        monkeypatch.setattr(threading.Thread, "start", original_start)
        backend.release.set()
        for thread in dispatch_threads:
            join_owned(thread)
        runtime.close(deadline_ms=100)
        for thread in started_growth:
            thread.join(1)
            assert not thread.is_alive()

def test_live_plus_quarantined_capacity_survives_reload_and_exact_reconciliation(
    tmp_path: Path,
) -> None:
    """Every unresolved exact cleanup debt must remain charged across worker reload."""
    backend = QuarantineBackend()
    runtime, scope = runtime_scope(
        tmp_path,
        initial=settings(workers=2),
        backend=backend,
    )
    try:
        assert runtime.register(
            definition(), binding(max_concurrency=3), scope
        ).accepted
        first = runtime.dispatch(event(runtime, scope, 1))
        second = runtime.dispatch(event(runtime, scope, 2))
        assert [first.outcomes[0].status.value, second.outcomes[0].status.value] == [
            "worker_lost",
            "worker_lost",
        ]
        changed = reload_runtime(runtime, settings(workers=1))
        assert_reload_result(changed, accepted=True)
        blocked = runtime.dispatch(event(runtime, scope, 3))
        assert blocked.outcomes[0].status.value == "rejected_capacity"
        backend.active_debts.remove("reload-debt-1")
        still_blocked = runtime.dispatch(event(runtime, scope, 4))
        assert still_blocked.outcomes[0].status.value == "rejected_capacity"
        backend.active_debts.remove("reload-debt-2")
        recovered = runtime.dispatch(event(runtime, scope, 5))
        assert recovered.outcomes[0].status.value == "worker_lost"
        assert backend.calls == 3
    finally:
        backend.active_debts.clear()
        runtime._scheduler.reconcile_cleanup_debts(set())
        runtime.close(deadline_ms=100)
